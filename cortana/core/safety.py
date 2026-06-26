"""
Terminal safety (PRD 5.2 / 8.3) for Cortana-initiated shell execution.

- Detects destructive commands so they can be gated behind explicit confirmation.
- Writes a full audit log of every command Cortana runs to
  ~/.cortana/terminal_history.jsonl.

User-typed commands in the browser PTY are inherently typed-by-the-user; this
module guards the commands Cortana chooses to run on the user's behalf.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

AUDIT_LOG = Path.home() / ".cortana" / "terminal_history.jsonl"

# Patterns that are destructive / irreversible / privileged.
_DESTRUCTIVE = [
    r"\brm\s+(-[a-zA-Z]*\s+)*-?[rRfF]",   # rm -rf / rm -r / rm -f
    r"\bsudo\b",
    r"\bdd\b\s+if=",
    r"\bmkfs\b",
    r"\b(shutdown|reboot|halt)\b",
    r"\bkillall\b",
    r">\s*/dev/(sd|disk|null)?",            # writing to devices
    r"\bchmod\s+-R\s+777\b",
    r"\bchown\s+-R\b",
    r"\bgit\s+push\b.*--force|\bgit\s+push\b.*\s-f\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-[a-zA-Z]*f",
    r":\(\)\s*\{",                          # fork bomb
    r"\bbrew\s+uninstall\b",
    r"\bnpm\s+(uninstall|prune)\b",
    r"\bpip\s+uninstall\b",
    r"\btruncate\b",
    r"\bdiskutil\b",
]
_COMPILED = [re.compile(p) for p in _DESTRUCTIVE]


def is_destructive(command: str) -> bool:
    """Return True if the command matches a destructive pattern or the config blocklist."""
    cmd = command.strip()
    if any(rx.search(cmd) for rx in _COMPILED):
        return True
    try:
        from cortana.config import get_config
        for pat in get_config().safety.terminal_blocklist:
            if pat and pat in cmd:
                return True
    except Exception:
        pass
    return False


def audit_log(command: str, source: str, allowed: bool, destructive: bool, note: str = ""):
    """Append one structured entry to the terminal audit log."""
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "command": command,
            "destructive": destructive,
            "allowed": allowed,
            "note": note,
        }
        with AUDIT_LOG.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as exc:  # never let logging break execution
        log.debug("audit_log failed: %s", exc)
