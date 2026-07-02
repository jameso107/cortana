"""Dual memory store: ChromaDB (episodic) + SQLite (structured)."""
from __future__ import annotations

import asyncio
import itertools
import logging
import math
import sqlite3
from datetime import datetime, timezone
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
        self._half_life_days = cfg.memory.decay_half_life_days
        self._min_similarity = cfg.memory.min_similarity
        self._min_query_words = cfg.memory.min_query_words
        # Monotonic counter so two turns in the same instant get distinct doc ids.
        self._id_counter = itertools.count()
        # llama.cpp exposes an OpenAI-compatible API; reuse the inference host/port.
        self._embeddings_base = f"http://{cfg.inference.host}:{cfg.inference.port}/v1"
        self._encrypt = cfg.safety.encrypt_memory
        self._cipher = None
        self._chroma = None
        self._collection = None
        self._embeddings_backend = "none"

    async def init(self):
        from cortana.core.secrets import Cipher
        self._cipher = Cipher(enabled=self._encrypt)
        self._episodic_path.mkdir(parents=True, exist_ok=True)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_sqlite()
        self._init_chroma()
        _set_store(self)
        log.info(
            "Memory store initialized (embeddings: %s, encryption: %s).",
            self._embeddings_backend, "on" if self._cipher.active else "off",
        )

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
        """
        Return relevant past context, re-ranked by similarity *and* recency.

        We over-fetch candidates, then score each by combining vector similarity
        with an exponential recency decay (half-life from config) so that recent
        memories outweigh equally-similar older ones (PRD 4.4). Candidates below
        a configurable similarity floor are dropped so an irrelevant top-n is
        never injected, and very short / pronoun-only turns skip retrieval
        entirely (their raw text is a poor query vector and history already
        covers them).
        """
        if self._collection is None:
            return ""
        if len(query.split()) < self._min_query_words:
            return ""
        try:
            candidates = max(n_results * 4, n_results)
            # Chroma's query() embeds + runs an HNSW search synchronously; keep it
            # off the event loop so a slow embedding endpoint can't freeze the daemon.
            results = await asyncio.to_thread(
                self._collection.query,
                query_texts=[query],
                n_results=candidates,
                include=["documents", "distances", "metadatas"],
            )
            docs = results.get("documents", [[]])[0]
            if not docs:
                return ""
            dists = results.get("distances", [[]])[0] or [0.0] * len(docs)
            metas = results.get("metadatas", [[]])[0] or [{}] * len(docs)

            now = datetime.now(timezone.utc)
            half_life = max(self._half_life_days, 1)
            scored = []
            for doc, dist, meta in zip(docs, dists, metas):
                similarity = 1.0 - float(dist)          # cosine distance → similarity
                if similarity < self._min_similarity:
                    continue                            # below relevance floor — skip
                recency = self._recency_weight(meta.get("ts"), now, half_life)
                score = similarity * recency
                scored.append((score, doc))
            scored.sort(key=lambda x: x[0], reverse=True)
            return "\n".join(doc for _, doc in scored[:n_results])
        except Exception as exc:
            log.debug("Memory retrieval error: %s", exc)
            return ""

    @staticmethod
    def _recency_weight(ts: str | None, now: datetime, half_life_days: int) -> float:
        if not ts:
            return 0.5  # unknown age — neutral-ish
        try:
            when = datetime.fromisoformat(ts)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
        except ValueError:
            return 0.5
        age_days = max((now - when).total_seconds() / 86400.0, 0.0)
        return math.pow(0.5, age_days / half_life_days)

    def recent_episodic(self, n: int = 20) -> list[dict]:
        """Return the most recent episodic memories (for the memory viewer)."""
        if self._collection is None:
            return []
        try:
            got = self._collection.get(include=["documents", "metadatas"])
            ids = got.get("ids", [])
            docs = got.get("documents", []) or []
            metas = got.get("metadatas", []) or [{}] * len(docs)
            rows = [
                {"ts": (m or {}).get("ts", i), "text": d}
                for i, d, m in zip(ids, docs, metas)
            ]
            rows.sort(key=lambda r: r["ts"], reverse=True)
            return rows[:n]
        except Exception as exc:
            log.debug("recent_episodic error: %s", exc)
            return []

    async def save(self, user_text: str, assistant_text: str):
        """Persist a conversation turn to episodic memory."""
        if self._collection is None:
            return
        ts = datetime.now(timezone.utc).isoformat()
        # Unique id (ts + counter) so two turns in the same instant don't collide
        # and silently overwrite each other on add().
        doc_id = f"{ts}#{next(self._id_counter)}"
        doc = f"[{ts}] User: {user_text}\nCortana: {assistant_text}"
        try:
            # add() is a synchronous C call; run it off the event loop.
            await asyncio.to_thread(
                self._collection.add,
                documents=[doc], ids=[doc_id], metadatas=[{"ts": ts}],
            )
        except Exception as exc:
            log.debug("Memory save error: %s", exc)

    # ── Structured facts (SQLite) ────────────────────────────────────────────────

    def _enc(self, value: str) -> str:
        return self._cipher.encrypt(value) if self._cipher else value

    def _dec(self, value: str) -> str:
        return self._cipher.decrypt(value) if self._cipher else value

    def set_fact(self, key: str, value: str):
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "INSERT OR REPLACE INTO user_facts VALUES (?, ?, ?)",
            (key.strip().lower(), self._enc(value), datetime.utcnow().isoformat()),
        )
        conn.commit()
        conn.close()

    def get_fact(self, key: str) -> str | None:
        conn = sqlite3.connect(self._db_path)
        row = conn.execute(
            "SELECT value FROM user_facts WHERE key=?", (key.strip().lower(),)
        ).fetchone()
        conn.close()
        return self._dec(row[0]) if row else None

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
        return {k: self._dec(v) for k, v in rows}

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
