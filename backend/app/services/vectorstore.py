"""Vector storage behind a narrow interface.

Chroma is the implementation promised in the Phase 1 document. The interface is
here so that swapping it costs one class, not a refactor - the corpus for a single
course is small enough that a brute-force numpy scan would also be fine.

Retrieval is always filtered by course_id AND by the set of approved source ids
supplied by the caller. An unapproved source cannot be returned, so it cannot be
cited: "confine to limited sources" enforced at the storage layer rather than by
asking the model nicely.
"""
from __future__ import annotations

from typing import Protocol

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import CHROMA_DIR, get_settings

COLLECTION = "course_chunks"


class VectorStore(Protocol):
    def add(self, chunk_ids, embeddings, metadatas) -> None: ...
    def query(self, embedding, course_id, source_ids, top_k) -> list[int]: ...
    def delete_document(self, document_id: int) -> None: ...


class ChromaStore:
    def __init__(self, path: str | None = None):
        get_settings()  # ensures the data directories exist
        self._client = chromadb.PersistentClient(
            path=path or str(CHROMA_DIR),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION, metadata={"hnsw:space": "cosine"}
        )

    def add(self, chunk_ids: list[int], embeddings: list[list[float]], metadatas: list[dict]):
        if not chunk_ids:
            return
        self._collection.add(
            ids=[str(cid) for cid in chunk_ids],
            embeddings=embeddings,
            metadatas=metadatas,
        )

    def query(
        self, embedding: list[float], course_id: int, source_ids: list[int], top_k: int
    ) -> list[int]:
        """Return chunk ids ordered best-first, restricted to approved sources."""
        if not source_ids:
            return []
        where = {
            "$and": [
                {"course_id": {"$eq": course_id}},
                {"source_id": {"$in": list(source_ids)}},
            ]
        }
        result = self._collection.query(
            query_embeddings=[embedding], n_results=top_k, where=where
        )
        ids = (result.get("ids") or [[]])[0]
        return [int(i) for i in ids]

    def delete_document(self, document_id: int) -> None:
        self._collection.delete(where={"document_id": {"$eq": document_id}})


_store: ChromaStore | None = None


def get_store() -> ChromaStore:
    global _store
    if _store is None:
        _store = ChromaStore()
    return _store
