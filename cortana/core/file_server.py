"""
HTTP API server on port 8767:
  GET /files?path=  — directory listing
  GET /file?path=   — file content
  GET /stats        — real CPU, RAM, model info
"""
from __future__ import annotations

import logging
import os
import stat
import time

import psutil
from aiohttp import web

log = logging.getLogger(__name__)


def _human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


async def handle_files(request: web.Request) -> web.Response:
    raw = request.rel_url.query.get("path", "~")
    path = os.path.expanduser(raw)

    if not os.path.isabs(path):
        path = os.path.join(os.path.expanduser("~"), path)

    if not os.path.isdir(path):
        return web.json_response({"error": f"Not a directory: {path}"}, status=400)

    entries = []
    try:
        for name in sorted(os.listdir(path), key=lambda n: (not os.path.isdir(os.path.join(path, n)), n.lower())):
            full = os.path.join(path, name)
            try:
                st = os.stat(full)
                is_dir = stat.S_ISDIR(st.st_mode)
                entries.append({
                    "name": name,
                    "size": "" if is_dir else _human(st.st_size),
                    "isDir": is_dir,
                    "path": full,
                })
            except PermissionError:
                entries.append({"name": name, "size": "—", "isDir": False, "path": full})
    except PermissionError:
        return web.json_response({"error": "Permission denied"}, status=403)

    return web.json_response(entries, headers={"Access-Control-Allow-Origin": "*"})


async def handle_read(request: web.Request) -> web.Response:
    raw = request.rel_url.query.get("path", "")
    path = os.path.expanduser(raw)
    if not os.path.isfile(path):
        return web.json_response({"error": "Not a file"}, status=400)
    try:
        with open(path, "r", errors="replace") as f:
            content = f.read(1_000_000)  # cap at 1 MB
        return web.json_response({"content": content}, headers={"Access-Control-Allow-Origin": "*"})
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)


def _model_display(model_filename: str) -> str:
    """Turn 'Qwen3-30B-A3B-Q6_K.gguf' into a readable label."""
    name = model_filename.replace(".gguf", "")
    # Extract quant suffix (Q4_K, Q6_K, etc.)
    parts = name.split("-")
    quant = next((p for p in reversed(parts) if p.upper().startswith("Q")), "")
    # Find the size token (e.g. 30B, 27B, 7B)
    size  = next((p for p in parts if p.endswith("B") and p[:-1].isdigit()), "")
    # Base name (everything before the size token)
    base_parts = []
    for p in parts:
        if p == size:
            break
        base_parts.append(p)
    base = "-".join(base_parts)
    label = base
    if size:
        label += f"-{size}"
    if quant:
        label += f" {quant}"
    return label


_boot_time = psutil.boot_time()


async def _port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    import asyncio
    try:
        fut = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout)
        writer.close()
        return True
    except Exception:
        return False


async def handle_stats(request: web.Request) -> web.Response:
    from cortana.config import get_config
    cfg = get_config()

    cpu = psutil.cpu_percent(interval=0.2)
    vm  = psutil.virtual_memory()
    ram_pct = vm.percent
    ram_used_gb = vm.used / 1024**3
    ram_total_gb = vm.total / 1024**3

    uptime_secs = int(time.time() - _boot_time)
    h, rem = divmod(uptime_secs, 3600)
    m, _   = divmod(rem, 60)
    uptime = f"{h}h {m}m"

    model_label = _model_display(cfg.inference.model)
    llama_up = await _port_open(cfg.inference.host, cfg.inference.port)

    data = {
        "cpu":         round(cpu, 1),
        "ram_pct":     round(ram_pct, 1),
        "ram_used_gb": round(ram_used_gb, 1),
        "ram_total_gb": round(ram_total_gb, 1),
        "model":       model_label,
        "uptime":      uptime,
        "llama_up":    llama_up,
    }
    return web.json_response(data, headers={"Access-Control-Allow-Origin": "*"})


async def handle_plugins(request: web.Request) -> web.Response:
    """List loaded plugins and their declared capabilities."""
    from cortana.plugins.registry import get_registry
    reg = get_registry()
    plugins = reg.manifests() if reg is not None else []
    return web.json_response({"plugins": plugins},
                             headers={"Access-Control-Allow-Origin": "*"})


async def handle_config(request: web.Request) -> web.Response:
    """GET current runtime config; POST {reasoning: ...} to change it live."""
    from cortana.core.orchestrator import get_orchestrator
    orch = get_orchestrator()
    if request.method == "POST":
        body = await request.json()
        if orch is not None and "reasoning" in body:
            ok = orch.set_reasoning(str(body["reasoning"]))
            return web.json_response({"ok": ok, "reasoning": orch.reasoning},
                                     headers={"Access-Control-Allow-Origin": "*"})
        return web.json_response({"ok": False}, status=400,
                                 headers={"Access-Control-Allow-Origin": "*"})
    return web.json_response(
        {"reasoning": orch.reasoning if orch else "auto"},
        headers={"Access-Control-Allow-Origin": "*"},
    )


async def handle_memory(request: web.Request) -> web.Response:
    """Return stored facts + recent episodic memories for the memory viewer."""
    from cortana.memory.store import get_store
    store = get_store()
    if store is None:
        return web.json_response({"facts": {}, "episodic": []},
                                 headers={"Access-Control-Allow-Origin": "*"})
    return web.json_response(
        {"facts": store.all_facts(), "episodic": store.recent_episodic(25)},
        headers={"Access-Control-Allow-Origin": "*"},
    )


async def handle_forget(request: web.Request) -> web.Response:
    """Forget a single fact by key."""
    from cortana.memory.store import get_store
    key = request.rel_url.query.get("key", "")
    store = get_store()
    if store is None or not key:
        return web.json_response({"ok": False}, status=400,
                                 headers={"Access-Control-Allow-Origin": "*"})
    ok = store.forget_fact(key)
    return web.json_response({"ok": ok}, headers={"Access-Control-Allow-Origin": "*"})


async def serve(host: str = "localhost", port: int = 8767):
    app = web.Application()
    app.router.add_get("/files", handle_files)
    app.router.add_get("/file",  handle_read)
    app.router.add_get("/stats", handle_stats)
    app.router.add_get("/memory", handle_memory)
    app.router.add_delete("/memory/fact", handle_forget)
    app.router.add_get("/plugins", handle_plugins)
    app.router.add_get("/config", handle_config)
    app.router.add_post("/config", handle_config)

    # Serve the built React UI.
    # Priority: ~/cortana/ui/dist (live, editable by self_editor) → bundled copy in .app Resources
    import pathlib
    live_dist    = pathlib.Path.home() / "cortana" / "ui" / "dist"
    bundled_dist = pathlib.Path(__file__).parent.parent.parent / "ui" / "dist"
    dist = live_dist if live_dist.exists() else bundled_dist
    if dist.exists():
        app.router.add_static("/assets", dist / "assets")

        _index_path = dist / "index.html"
        _config_snippet = """<script>
window.CORTANA_CONFIG = {
  wsChat:     "ws://127.0.0.1:8765",
  wsTerm:     "ws://127.0.0.1:8766",
  apiBase:    "http://127.0.0.1:8767",
  searxng:    "http://127.0.0.1:8888",
};
</script>"""

        async def index(req):
            # Read fresh each request so npm rebuilds take effect without restart
            html = _index_path.read_text()
            injected = html.replace("</head>", _config_snippet + "\n</head>", 1)
            return web.Response(
                text=injected,
                content_type="text/html",
                headers={"Access-Control-Allow-Origin": "*"},
            )
        app.router.add_get("/", index)
        log.info("Serving UI from %s", dist)
    else:
        log.warning("ui/dist not found — UI not served (run: cd ui && npm run build)")

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info("File API server on http://%s:%d", host, port)

    import asyncio
    await asyncio.Future()  # run forever
