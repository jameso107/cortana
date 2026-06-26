"""
Self-editor plugin — gives Cortana the ability to read and modify her own codebase.

Rules enforced in code:
  1. write_file and apply_patch refuse to run if the git working tree is dirty.
     Cortana must call git_commit first to snapshot the current state.
  2. shell_run executes in the repo root with a 60s timeout.
  3. restart_daemon sends SIGUSR1 to the supervisor wrapper, which relaunches
     the Python daemon cleanly.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
from pathlib import Path

from cortana.plugins.base import PluginBase

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent.parent.resolve()  # ~/cortana/
SUPERVISOR_PID_FILE = Path.home() / ".cortana" / "supervisor.pid"


def _repo_path(rel: str) -> Path:
    """Resolve a path relative to the repo root, refusing to escape it."""
    p = (REPO_ROOT / rel).resolve()
    if not str(p).startswith(str(REPO_ROOT)):
        raise ValueError(f"Path escapes repo root: {rel}")
    return p


def _git(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        **kwargs,
    )


def _is_tree_clean() -> bool:
    result = _git(["status", "--porcelain"])
    return result.stdout.strip() == ""


class Plugin(PluginBase):
    name = "self_editor"
    description = (
        "Read, write, and manage Cortana's own source code. "
        "Use this to self-improve, fix bugs, add features, or refactor. "
        "ALWAYS call git_commit before any write_file or apply_patch call."
    )

    def register(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "read_file",
                                "write_file",
                                "list_dir",
                                "git_status",
                                "git_diff",
                                "git_log",
                                "git_commit",
                                "shell_run",
                                "restart_daemon",
                            ],
                            "description": "Action to perform.",
                        },
                        "path": {
                            "type": "string",
                            "description": "File or directory path relative to the repo root (e.g. 'cortana/core/orchestrator.py').",
                        },
                        "content": {
                            "type": "string",
                            "description": "Full file content for write_file.",
                        },
                        "message": {
                            "type": "string",
                            "description": "Commit message for git_commit.",
                        },
                        "command": {
                            "type": "string",
                            "description": "Shell command to run (e.g. 'cd ui && npm run build').",
                        },
                        "n": {
                            "type": "integer",
                            "description": "Number of log entries for git_log (default 10).",
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    async def handle(self, intent: str, args: dict) -> str:
        action = args.get("action")
        try:
            if action == "read_file":
                return self._read_file(args)
            if action == "write_file":
                return self._write_file(args)
            if action == "list_dir":
                return self._list_dir(args)
            if action == "git_status":
                return self._git_status()
            if action == "git_diff":
                return self._git_diff(args)
            if action == "git_log":
                return self._git_log(args)
            if action == "git_commit":
                return self._git_commit(args)
            if action == "shell_run":
                return await self._shell_run(args)
            if action == "restart_daemon":
                return self._restart_daemon()
            return f"Unknown action: {action}"
        except ValueError as e:
            return f"Error: {e}"
        except subprocess.TimeoutExpired:
            return "Error: command timed out."
        except Exception as e:
            log.exception("self_editor error")
            return f"Error: {e}"

    # ── Actions ──────────────────────────────────────────────────────────────

    def _read_file(self, args: dict) -> str:
        path = _repo_path(args.get("path", ""))
        if not path.is_file():
            return f"File not found: {path.relative_to(REPO_ROOT)}"
        text = path.read_text(errors="replace")
        # Return up to 8000 chars; note truncation so Cortana knows
        if len(text) > 8000:
            return text[:8000] + f"\n\n[… truncated — file is {len(text)} chars total]"
        return text

    def _write_file(self, args: dict) -> str:
        path    = _repo_path(args.get("path", ""))
        content = args.get("content")
        if content is None:
            return "Error: content is required for write_file."

        # Gate: working tree must be clean before any edit
        if not _is_tree_clean():
            return (
                "BLOCKED: working tree is dirty. "
                "Call git_commit with a descriptive message FIRST, then retry write_file."
            )

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        log.info("self_editor: wrote %s (%d chars)", path.relative_to(REPO_ROOT), len(content))
        return f"Written: {path.relative_to(REPO_ROOT)} ({len(content)} chars)"

    def _list_dir(self, args: dict) -> str:
        rel  = args.get("path", ".")
        path = _repo_path(rel)
        if not path.is_dir():
            return f"Not a directory: {rel}"
        entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
        lines = []
        for e in entries:
            if e.name.startswith(".") or e.name in ("node_modules", "__pycache__", ".venv", "dist"):
                continue
            prefix = "📁 " if e.is_dir() else "   "
            lines.append(f"{prefix}{e.name}")
        return "\n".join(lines) or "(empty)"

    def _git_status(self) -> str:
        r = _git(["status", "--short"])
        return r.stdout.strip() or "Clean working tree."

    def _git_diff(self, args: dict) -> str:
        path = args.get("path")
        cmd  = ["diff", "HEAD"]
        if path:
            cmd.append(path)
        r = _git(cmd)
        out = r.stdout.strip()
        if len(out) > 6000:
            out = out[:6000] + "\n[… diff truncated]"
        return out or "No changes."

    def _git_log(self, args: dict) -> str:
        n = args.get("n", 10)
        r = _git(["log", f"-{n}", "--oneline", "--decorate"])
        return r.stdout.strip() or "No commits yet."

    def _git_commit(self, args: dict) -> str:
        message = args.get("message", "").strip()
        if not message:
            return "Error: a commit message is required."

        # Stage all tracked + new files (excluding .gitignore'd)
        _git(["add", "-A"])

        status = _git(["status", "--porcelain"])
        if not status.stdout.strip():
            return "Nothing to commit — working tree is already clean."

        full_message = message + "\n\nCo-Authored-By: Cortana <cortana@local>"
        r = _git(["commit", "-m", full_message])
        if r.returncode != 0:
            return f"Commit failed:\n{r.stderr.strip()}"
        # Return the short hash + message
        head = _git(["log", "-1", "--oneline"])
        return f"Committed: {head.stdout.strip()}"

    async def _shell_run(self, args: dict) -> str:
        command = args.get("command", "").strip()
        if not command:
            return "Error: command is required."

        log.info("self_editor shell_run: %s", command)
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=REPO_ROOT,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
            text = out.decode("utf-8", errors="replace").strip()
            if len(text) > 4000:
                text = text[:4000] + "\n[… output truncated]"
            rc = proc.returncode
            return f"[exit {rc}]\n{text}" if text else f"[exit {rc}] (no output)"
        except asyncio.TimeoutError:
            return "Error: command timed out after 120s."

    def _restart_daemon(self) -> str:
        """Signal the supervisor to restart the daemon process."""
        pid_file = SUPERVISOR_PID_FILE
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                os.kill(pid, signal.SIGUSR1)
                return "Restart signal sent to supervisor. Daemon will reload in ~2 seconds."
            except (ProcessLookupError, ValueError):
                pass
        # Fallback: send SIGTERM to self — supervisor loop will relaunch
        os.kill(os.getpid(), signal.SIGTERM)
        return "Sent SIGTERM — supervisor will relaunch the daemon."
