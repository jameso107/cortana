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

    data = {
        "cpu":         round(cpu, 1),
        "ram_pct":     round(ram_pct, 1),
        "ram_used_gb": round(ram_used_gb, 1),
        "ram_total_gb": round(ram_total_gb, 1),
        "model":       model_label,
        "uptime":      uptime,
    }
    return web.json_response(data, headers={"Access-Control-Allow-Origin": "*"})


async def serve(host: str = "localhost", port: int = 8767):
    app = web.Application()
    app.router.add_get("/files", handle_files)
    app.router.add_get("/file",  handle_read)
    app.router.add_get("/stats", handle_stats)

    # Serve the built React UI.
    # Priority: ~/cortana/ui/dist (live, editable by self_editor) → bundled copy in .app Resources
    import pathlib
    live_dist    = pathlib.Path.home() / "cortana" / "ui" / "dist"
    bundled_dist = pathlib.Path(__file__).parent.parent.parent / "ui" / "dist"
    dist = live_dist if live_dist.exists() else bundled_dist
    if dist.exists():
        app.router.add_static("/assets", dist / "assets")

        # Inject runtime config so the UI knows the right ports
        _html_template = (dist / "index.html").read_text()
        _config_snippet = """<script>
window.CORTANA_CONFIG = {
  wsChat:     "ws://127.0.0.1:8765",
  wsTerm:     "ws://127.0.0.1:8766",
  apiBase:    "http://127.0.0.1:8767",
  searxng:    "http://127.0.0.1:8888",
};
</script>"""
        _injected_html = _html_template.replace("</head>", _config_snippet + "\n</head>", 1)

        async def index(req):
            return web.Response(
                text=_injected_html,
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
