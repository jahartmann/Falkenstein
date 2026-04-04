from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

try:
    import chromadb
    HAS_CHROMADB = True
except ImportError:
    HAS_CHROMADB = False


class RAGEngine:
    """Episodic Memory via ChromaDB for task summaries and agent interactions."""

    def __init__(self, persist_path: Path | None = None):
        self._available = HAS_CHROMADB
        self._client = None
        self._collection = None
        self._persist_path = persist_path

    @property
    def available(self) -> bool:
        return self._available

    async def init(self):
        if not self._available:
            return
        def _init():
            if self._persist_path:
                self._client = chromadb.PersistentClient(path=str(self._persist_path))
            else:
                self._client = chromadb.Client()
            self._collection = self._client.get_or_create_collection(
                name="falkenstein_episodes",
                metadata={"hnsw:space": "cosine"},
            )
        await asyncio.to_thread(_init)

    def _make_id(self, text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()[:16]

    async def store_episode(self, text: str, metadata: dict | None = None):
        """Store a completed task summary or interaction as an episode."""
        if not self._available or not self._collection:
            return
        doc_id = self._make_id(text)
        meta = metadata or {}
        # ChromaDB metadata must be str/int/float and non-empty
        clean_meta = {k: str(v) for k, v in meta.items()}
        if not clean_meta:
            clean_meta = {"type": "episode"}
        def _store():
            self._collection.upsert(
                ids=[doc_id],
                documents=[text],
                metadatas=[clean_meta],
            )
        await asyncio.to_thread(_store)

    async def query(self, query_text: str, n_results: int = 3) -> list[dict]:
        """Retrieve most relevant episodes for a query."""
        if not self._available or not self._collection:
            return []
        def _query():
            results = self._collection.query(
                query_texts=[query_text],
                n_results=n_results,
            )
            episodes = []
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]
            for doc, meta, dist in zip(docs, metas, distances):
                episodes.append({
                    "text": doc,
                    "metadata": meta,
                    "relevance": 1.0 - dist,  # cosine distance → similarity
                })
            return episodes
        return await asyncio.to_thread(_query)

    async def store_task_completion(self, agent_id: str, task_title: str,
                                     task_description: str, result: str,
                                     success: bool):
        """Store a completed task as an episode."""
        summary = (
            f"Agent {agent_id} hat Task '{task_title}' "
            f"{'erfolgreich' if success else 'nicht erfolgreich'} abgeschlossen. "
            f"Beschreibung: {task_description[:200]}. "
            f"Ergebnis: {result[:300]}"
        )
        await self.store_episode(summary, {
            "type": "task_completion",
            "agent_id": agent_id,
            "task_title": task_title,
            "success": str(success),
        })

    async def get_context_for_task(self, task_description: str) -> str:
        """Get relevant past episodes as context for a new task."""
        episodes = await self.query(task_description, n_results=3)
        if not episodes:
            return ""
        lines = ["Relevante vergangene Erfahrungen:"]
        for ep in episodes:
            if ep["relevance"] > 0.3:
                lines.append(f"- {ep['text'][:200]}")
        return "\n".join(lines) if len(lines) > 1 else ""

    async def count(self) -> int:
        if not self._available or not self._collection:
            return 0
        def _count():
            return self._collection.count()
        return await asyncio.to_thread(_count)
