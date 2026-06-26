"""Dual memory store: ChromaDB (episodic) + SQLite (structured)."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


class _LlamaEmbeddingFunction:
    """
    Chroma embedding function backed by an OpenAI-compatible /v1/embeddings
    endpoint (llama.cpp / a dedicated embedding server) running the configured
    embedding model (PRD: nomic-embed-text).

    If the endpoint is unreachable, MemoryStore falls back to Chroma's bundled
    local embedder, so memory keeps working fully offline.
    """

    def __init__(self, base_url: str, model: str):
        self._url = base_url.rstrip("/") + "/embeddings"
        self._model = model

    # Chroma calls this as ef(input=[...]) and expects list[list[float]].
    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002 (Chroma's signature)
        import httpx

        resp = httpx.post(
            self._url,
            json={"model": self._model, "input": input},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        # Preserve request order
        data = sorted(data, key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in data]

    # Chroma >=0.5 requires a stable name for persistence.
    def name(self) -> str:
        return f"llama:{self._model}"


class MemoryStore:
    def __init__(self):
        from cortana.config import get_config
        cfg = get_config()
        self._episodic_path = Path(cfg.memory.episodic_path).expanduser()
        self._db_path = Path(cfg.memory.structured_path).expanduser()
        self._embedding_model = cfg.memory.embedding_model
        # llama.cpp exposes an OpenAI-compatible API; reuse the inference host/port.
        self._embeddings_base = f"http://{cfg.inference.host}:{cfg.inference.port}/v1"
        self._chroma = None
        self._collection = None
        self._embeddings_backend = "none"

    async def init(self):
        self._episodic_path.mkdir(parents=True, exist_ok=True)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_sqlite()
        self._init_chroma()
        _set_store(self)
        log.info("Memory store initialized (embeddings: %s).", self._embeddings_backend)

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

    def _resolve_embedding_function(self):
        """Use the configured embedding endpoint if it answers; else Chroma default."""
        ef = _LlamaEmbeddingFunction(self._embeddings_base, self._embedding_model)
        try:
            ef(["ping"])  # probe
            self._embeddings_backend = ef.name()
            return ef
        except Exception as exc:
            log.warning(
                "Embedding endpoint %s unavailable (%s) — using Chroma's local embedder.",
                self._embeddings_base, exc,
            )
            self._embeddings_backend = "chroma-default (local)"
            return None  # Chroma falls back to its bundled local model

    def _init_chroma(self):
        try:
            import chromadb
        except ImportError:
            log.warning("chromadb not installed — episodic memory disabled.")
            return
        self._chroma = chromadb.PersistentClient(path=str(self._episodic_path))
        ef = self._resolve_embedding_function()
        kwargs = {"name": "episodic", "metadata": {"hnsw:space": "cosine"}}
        if ef is not None:
            kwargs["embedding_function"] = ef
        self._collection = self._chroma.get_or_create_collection(**kwargs)

    # ── Episodic memory ────────────────────────────────────────────────────────

    async def retrieve(self, query: str, n_results: int = 5) -> str:
        """Return relevant past context as a formatted string."""
        if self._collection is None:
            return ""
        try:
            results = self._collection.query(query_texts=[query], n_results=n_results)
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
            # Store ts in metadata so recency-weighted retrieval is possible later.
            self._collection.add(documents=[doc], ids=[ts], metadatas=[{"ts": ts}])
        except Exception as exc:
            log.debug("Memory save error: %s", exc)

    # ── Structured facts (SQLite) ────────────────────────────────────────────────

    def set_fact(self, key: str, value: str):
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "INSERT OR REPLACE INTO user_facts VALUES (?, ?, ?)",
            (key.strip().lower(), value, datetime.utcnow().isoformat()),
        )
        conn.commit()
        conn.close()

    def get_fact(self, key: str) -> str | None:
        conn = sqlite3.connect(self._db_path)
        row = conn.execute(
            "SELECT value FROM user_facts WHERE key=?", (key.strip().lower(),)
        ).fetchone()
        conn.close()
        return row[0] if row else None

    def forget_fact(self, key: str) -> bool:
        conn = sqlite3.connect(self._db_path)
        cur = conn.execute("DELETE FROM user_facts WHERE key=?", (key.strip().lower(),))
        conn.commit()
        deleted = cur.rowcount > 0
        conn.close()
        return deleted

    def all_facts(self) -> dict[str, str]:
        conn = sqlite3.connect(self._db_path)
        rows = conn.execute(
            "SELECT key, value FROM user_facts ORDER BY updated_at DESC"
        ).fetchall()
        conn.close()
        return {k: v for k, v in rows}

    def facts_block(self, limit: int = 40) -> str:
        """Formatted facts for system-prompt injection."""
        facts = self.all_facts()
        if not facts:
            return ""
        lines = [f"- {k}: {v}" for k, v in list(facts.items())[:limit]]
        return "\n".join(lines)


# ── Shared-instance accessor (so plugins can reach the live store) ───────────────
_store: "MemoryStore | None" = None


def _set_store(store: "MemoryStore"):
    global _store
    _store = store


def get_store() -> "MemoryStore | None":
    return _store
