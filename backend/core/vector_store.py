from __future__ import annotations

import os
from typing import Any

BACKEND = os.getenv("PERSONAL_OS_VECTOR_BACKEND", "sqlite").lower()
CHROMA_DIR = os.getenv("PERSONAL_OS_CHROMA_DIR", "./data/chroma")
CHROMA_COLLECTION = os.getenv("PERSONAL_OS_CHROMA_COLLECTION", "personal_os_rag")


def backend_name() -> str:
    return BACKEND


def is_external_enabled() -> bool:
    return BACKEND == "chroma"


def status() -> dict:
    if BACKEND != "chroma":
        return {"backend": BACKEND, "ready": True, "external": False}
    try:
        collection = _chroma_collection()
        return {
            "backend": "chroma",
            "ready": True,
            "external": True,
            "collection": CHROMA_COLLECTION,
            "count": collection.count(),
        }
    except Exception as e:
        return {
            "backend": "chroma",
            "ready": False,
            "external": True,
            "collection": CHROMA_COLLECTION,
            "error": str(e),
        }


def upsert_chunks(chunks: list[dict[str, Any]]) -> dict:
    if BACKEND != "chroma":
        return {"backend": "sqlite", "upserted": 0, "enabled": False}
    try:
        collection = _chroma_collection()
        ids = [str(chunk["id"]) for chunk in chunks]
        collection.upsert(
            ids=ids,
            embeddings=[chunk["embedding"] for chunk in chunks],
            documents=[chunk["text"] for chunk in chunks],
            metadatas=[chunk["metadata"] for chunk in chunks],
        )
        return {"backend": "chroma", "upserted": len(chunks), "enabled": True}
    except Exception as e:
        if os.getenv("PERSONAL_OS_VECTOR_REQUIRED", "false").lower() == "true":
            raise RuntimeError("Chroma vector backend is required but unavailable: " + str(e)) from e
        return {"backend": "chroma", "upserted": 0, "enabled": False, "error": str(e)}


def query(query_embedding: list[float], top_k: int) -> list[dict]:
    if BACKEND != "chroma":
        return []
    try:
        collection = _chroma_collection()
        result = collection.query(query_embeddings=[query_embedding], n_results=top_k)
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        documents = result.get("documents", [[]])[0]
        rows = []
        for index, chunk_id in enumerate(ids):
            rows.append(
                {
                    "id": int(chunk_id),
                    "distance": distances[index] if index < len(distances) else None,
                    "metadata": metadatas[index] if index < len(metadatas) else {},
                    "text": documents[index] if index < len(documents) else "",
                }
            )
        return rows
    except Exception:
        return []


def _chroma_collection():
    import chromadb

    client = chromadb.PersistentClient(path=CHROMA_DIR)
    return client.get_or_create_collection(CHROMA_COLLECTION)
