"""Plugin registry — loads, hot-reloads, and dispatches to plugins."""
from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.util
import json
import logging
import time
from pathlib import Path

from cortana.plugins.base import PluginBase

log = logging.getLogger(__name__)

APPROVED_FILE = Path.home() / ".cortana" / "approved_plugins.json"

# Circuit-breaker tuning: after this many failures within the window, a plugin
# is skipped for a cooldown so one bad dependency can't degrade every turn.
_BREAKER_THRESHOLD = 3
_BREAKER_WINDOW = 120.0     # seconds over which failures accumulate
_BREAKER_COOLDOWN = 90.0    # seconds a tripped plugin is skipped
_DISPATCH_TIMEOUT = 30.0    # hard cap on a single tool call (safety net for hangs)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

BUILTIN_PLUGINS = [
    "cortana.plugins.builtin.web_search",
    "cortana.plugins.builtin.calendar",
    "cortana.plugins.builtin.file_manager",
    "cortana.plugins.builtin.system_control",
    "cortana.plugins.builtin.weather",
    "cortana.plugins.builtin.notes",
    "cortana.plugins.builtin.clipboard",
    "cortana.plugins.builtin.web_fetch",
    "cortana.plugins.builtin.news",
    "cortana.plugins.builtin.self_editor",
    "cortana.plugins.builtin.memory",
    "cortana.plugins.builtin.email",
    "cortana.plugins.builtin.reminders",
    "cortana.plugins.builtin.code_assistant",
    "cortana.plugins.builtin.briefing",
    "cortana.plugins.builtin.perception",
    "cortana.plugins.builtin.scheduler",
]


class PluginRegistry:
    def __init__(self):
        self._plugins: dict[str, PluginBase] = {}
        self._enabled: set[str] = set()
        self._disabled: set[str] = set()
        # name -> {"fails": [timestamps], "open_until": monotonic_ts}
        self._breaker: dict[str, dict] = {}

    async def load_all(self):
        from cortana.config import get_config
        cfg = get_config().plugins
        self._enabled = set(cfg.enabled)
        self._disabled = set(cfg.disabled)

        for module_path in BUILTIN_PLUGINS:
            self._load_plugin(module_path, trusted=True)

        if cfg.load_third_party:
            self._load_third_party(Path(cfg.directory).expanduser())

        # Capability disclosure (PRD 8.2): log what each plugin can reach.
        for p in self._plugins.values():
            caps = ", ".join(sorted(p.capabilities)) or "none"
            log.info("plugin %-16s caps=[%s]", p.name, caps)
        log.info("Loaded %d plugins.", len(self._plugins))
        _set_registry(self)

    def _gated(self, name: str) -> bool:
        """Return True if a plugin name is disabled by config."""
        if name in self._disabled:
            log.info("Plugin %s disabled by config — skipping.", name)
            return True
        if self._enabled and name not in self._enabled:
            log.info("Plugin %s not in enabled allowlist — skipping.", name)
            return True
        return False

    def _register(self, plugin: PluginBase) -> bool:
        if self._gated(plugin.name):
            return False
        self._plugins[plugin.name] = plugin
        log.debug("Loaded plugin: %s", plugin.name)
        return True

    def _load_plugin(self, module_path: str, trusted: bool = False):
        try:
            mod = importlib.import_module(module_path)
            self._register(mod.Plugin())
        except Exception as exc:
            log.warning("Failed to load plugin %s: %s", module_path, exc)

    # ── Third-party plugins (hash-approved; PRD 8.2) ────────────────────────────
    def _load_third_party(self, directory: Path):
        if not directory.is_dir():
            return
        approved = self._read_approved()
        changed = False
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("_"):
                continue
            digest = _sha256(path)
            if approved.get(path.name) != digest:
                log.warning(
                    "Unsigned/changed third-party plugin %s (sha256=%s) — NOT loaded. "
                    "Approve it by adding its hash to %s.",
                    path.name, digest[:12], APPROVED_FILE,
                )
                # Record as pending so the user can review and approve.
                approved.setdefault("_pending", {})[path.name] = digest
                changed = True
                continue
            self._load_from_path(path)
        if changed:
            self._write_approved(approved)

    def _load_from_path(self, path: Path):
        try:
            spec = importlib.util.spec_from_file_location(f"cortana_ext_{path.stem}", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            self._register(mod.Plugin())
        except Exception as exc:
            log.warning("Failed to load third-party plugin %s: %s", path.name, exc)

    @staticmethod
    def _read_approved() -> dict:
        try:
            return json.loads(APPROVED_FILE.read_text())
        except Exception:
            return {}

    @staticmethod
    def _write_approved(data: dict):
        try:
            APPROVED_FILE.parent.mkdir(parents=True, exist_ok=True)
            APPROVED_FILE.write_text(json.dumps(data, indent=2))
        except Exception as exc:
            log.debug("Could not write approved-plugins file: %s", exc)

    def manifests(self) -> list[dict]:
        """All loaded plugins' capability manifests (for a plugin manager UI)."""
        return [p.manifest() for p in self._plugins.values()]

    def spawn_background_tasks(self) -> list:
        """Spawn background_task() loops for plugins that override the default."""
        tasks = []
        for p in self._plugins.values():
            if type(p).background_task is not PluginBase.background_task:
                tasks.append(asyncio.create_task(p.background_task()))
                log.info("Spawned background task for plugin %s.", p.name)
        return tasks

    def get_tool_schemas(self) -> list[dict]:
        return [p.register() for p in self._plugins.values()]

    async def dispatch(self, tool_calls: list[dict]) -> list[dict]:
        """Execute tool calls and return tool result messages."""
        results = []
        for call in tool_calls:
            name = call["name"]
            try:
                args = json.loads(call.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}

            plugin = self._plugins.get(name)
            if plugin is None:
                content = f"Unknown tool: {name}"
            elif self._breaker_open(name):
                content = (
                    f"{name} is temporarily unavailable (it failed repeatedly and is "
                    "in a cooldown). Proceed without it or try again shortly."
                )
                log.warning("Plugin %s skipped — circuit breaker open.", name)
            else:
                try:
                    content = await asyncio.wait_for(
                        plugin.handle(name, args), timeout=_DISPATCH_TIMEOUT
                    )
                    self._breaker_reset(name)
                except asyncio.TimeoutError:
                    self._breaker_record(name)
                    log.error("Plugin %s timed out after %.0fs.", name, _DISPATCH_TIMEOUT)
                    content = f"{name} timed out. Proceed without its result."
                except Exception as exc:
                    self._breaker_record(name)
                    log.error("Plugin %s error: %s", name, exc)
                    content = f"Error in {name}: {exc}"

            results.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": content,
            })
        return results

    # ── Circuit breaker ─────────────────────────────────────────────────────────
    def _breaker_open(self, name: str) -> bool:
        st = self._breaker.get(name)
        return bool(st and st.get("open_until", 0) > time.monotonic())

    def _breaker_record(self, name: str):
        now = time.monotonic()
        st = self._breaker.setdefault(name, {"fails": [], "open_until": 0})
        st["fails"] = [t for t in st["fails"] if now - t < _BREAKER_WINDOW] + [now]
        if len(st["fails"]) >= _BREAKER_THRESHOLD:
            st["open_until"] = now + _BREAKER_COOLDOWN
            st["fails"] = []
            log.warning("Plugin %s circuit breaker tripped — cooling down %.0fs.", name, _BREAKER_COOLDOWN)

    def _breaker_reset(self, name: str):
        if name in self._breaker:
            self._breaker[name] = {"fails": [], "open_until": 0}


# Shared accessor so HTTP endpoints can list plugins.
_active_registry: "PluginRegistry | None" = None


def _set_registry(reg: "PluginRegistry"):
    global _active_registry
    _active_registry = reg


def get_registry() -> "PluginRegistry | None":
    return _active_registry
