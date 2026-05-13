from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections import Counter

import requests

DIMENSIONS = 128
TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")
EMBEDDING_PROVIDER = os.getenv("PERSONAL_OS_EMBEDDING_PROVIDER", "local").lower()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", os.getenv("OLLAMA_MODEL", "llama3.2"))
EMBEDDING_TIMEOUT_SECONDS = float(os.getenv("PERSONAL_OS_EMBEDDING_TIMEOUT_SECONDS", "15"))


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def embed_text(text: str, dimensions: int = DIMENSIONS) -> list[float]:
    if EMBEDDING_PROVIDER == "ollama":
        try:
            return _embed_ollama(text)
        except Exception:
            return _embed_local(text, dimensions)
    return _embed_local(text, dimensions)


def embedding_provider() -> str:
    return EMBEDDING_PROVIDER


def embedding_dimensions() -> int:
    if EMBEDDING_PROVIDER == "ollama":
        try:
            return len(_embed_ollama("dimension probe"))
        except Exception:
            return DIMENSIONS
    return DIMENSIONS


def _embed_local(text: str, dimensions: int = DIMENSIONS) -> list[float]:
    counts: Counter[int] = Counter()
    for token in tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1 if digest[4] % 2 == 0 else -1
        counts[index] += sign
    vector = [0.0] * dimensions
    norm = math.sqrt(sum(value * value for value in counts.values()))
    if norm == 0:
        return vector
    for index, value in counts.items():
        vector[index] = value / norm
    return vector


def _embed_ollama(text: str) -> list[float]:
    response = requests.post(
        OLLAMA_BASE_URL + "/api/embeddings",
        json={"model": OLLAMA_EMBEDDING_MODEL, "prompt": text},
        timeout=EMBEDDING_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    vector = response.json().get("embedding", [])
    if not vector:
        raise ValueError("Ollama did not return an embedding.")
    return _normalize([float(value) for value in vector])


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def dumps_vector(vector: list[float]) -> str:
    return json.dumps(vector, separators=(",", ":"))


def loads_vector(raw: str) -> list[float]:
    return [float(value) for value in json.loads(raw)]


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    return sum(left * right for left, right in zip(a, b))
