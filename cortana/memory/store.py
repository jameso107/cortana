"""Dual memory store: ChromaDB (episodic) + SQLite (structured)."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


class MemoryStore:
    def __init__(self):
        from cortana.config import get_config
        cfg = get_config().memory
        self._episodic_path = Path(cfg.episodic_path).expanduser()
        self._db_path = Path(cfg.structured_path).expanduser()
        self._chroma = None
        self._collection = None

    async def init(self):
        self._episodic_path.mkdir(parents=True, exist_ok=True)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_sqlite()
        self._init_chroma()
        log.info("Memory store initialized.")

    def _init_sqlite(self):
        conn = sqlite3.connect(self._db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS user_facts (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS task_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT,
                outcome TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS plugin_state (
                plugin TEXT,
                key TEXT,
                value TEXT,
                PRIMARY KEY (plugin, key)
            );
        """)
        conn.commit()
        conn.close()

    def _init_chroma(self):
        try:
            import chromadb
            self._chroma = chromadb.PersistentClient(path=str(self._episodic_path))
            self._collection = self._chroma.get_or_create_collection(
                name="episodic",
                metadata={"hnsw:space": "cosine"},
            )
        except ImportError:
            log.warning("chromadb not installed — episodic memory disabled.")

    async def retrieve(self, query: str, n_results: int = 5) -> str:
        """Return relevant past context as a formatted string."""
        if self._collection is None:
            return ""
        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=n_results,
            )
            docs = results.get("documents", [[]])[0]
            return "\n".join(docs) if docs else ""
        except Exception as exc:
            log.debug("Memory retrieval error: %s", exc)
            return ""

    async def save(self, user_text: str, assistant_text: str):
        """Persist a conversation turn to episodic memory."""
        if self._collection is None:
            return
        ts = datetime.utcnow().isoformat()
        doc = f"[{ts}] User: {user_text}\nCortana: {assistant_text}"
        try:
            self._collection.add(documents=[doc], ids=[ts])
        except Exception as exc:
            log.debug("Memory save error: %s", exc)

    def set_fact(self, key: str, value: str):
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "INSERT OR REPLACE INTO user_facts VALUES (?, ?, ?)",
            (key, value, datetime.utcnow().isoformat()),
        )
        conn.commit()
        conn.close()

    def get_fact(self, key: str) -> str | None:
        conn = sqlite3.connect(self._db_path)
        row = conn.execute("SELECT value FROM user_facts WHERE key=?", (key,)).fetchone()
        conn.close()
        return row[0] if row else None
