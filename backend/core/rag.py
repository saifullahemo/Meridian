from __future__ import annotations

import sqlite3
import os
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import requests

from backend.core import brain, document_ingestion, observability, prompt_templates, semantic, safeguards, vector_store
from backend.data import database

CHUNK_CHARS = 1000
CHUNK_OVERLAP = 150
logger = observability.get_logger(__name__)


def session_file_source(session_id: str, filename: str) -> str:
    safe_session = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in session_id or "default")
    safe_filename = (filename or "uploaded_file").replace("/", "_").replace("\\", "_")
    return "session:" + safe_session + ":file:" + safe_filename


def session_source_prefix(session_id: str) -> str:
    safe_session = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in session_id or "default")
    return "session:" + safe_session + ":"


def _conn() -> sqlite3.Connection:
    conn = database.get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rag_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'text',
            title TEXT,
            chunk_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            embedding TEXT NOT NULL,
            embedding_provider TEXT NOT NULL DEFAULT 'local',
            embedding_dimensions INTEGER NOT NULL DEFAULT 128,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    _ensure_column(conn, "rag_chunks", "source_type", "TEXT NOT NULL DEFAULT 'text'")
    _ensure_column(conn, "rag_chunks", "title", "TEXT")
    _ensure_column(conn, "rag_chunks", "embedding_provider", "TEXT NOT NULL DEFAULT 'local'")
    _ensure_column(conn, "rag_chunks", "embedding_dimensions", "INTEGER NOT NULL DEFAULT 128")
    conn.commit()
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def chunk_text(text: str, chunk_chars: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    clean = " ".join(text.split())
    if not clean:
        return []
    chunks = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + chunk_chars)
        chunks.append(clean[start:end])
        if end == len(clean):
            break
        start = max(0, end - overlap)
    return chunks


def ingest_text(source: str, text: str, source_type: str = "text", title: str | None = None) -> dict:
    text = safeguards.truncate_text(text, 500000, "rag source")
    chunks = chunk_text(text)
    with _conn() as conn:
        conn.execute("DELETE FROM rag_chunks WHERE source = ?", (source,))
        vector_chunks = []
        for index, chunk in enumerate(chunks):
            embedding = semantic.embed_text(chunk)
            cursor = conn.execute(
                """
                INSERT INTO rag_chunks (
                    source, source_type, title, chunk_id, text, embedding,
                    embedding_provider, embedding_dimensions
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source,
                    source_type,
                    title or source,
                    index,
                    chunk,
                    semantic.dumps_vector(embedding),
                    semantic.embedding_provider(),
                    len(embedding),
                ),
            )
            row_id = cursor.lastrowid
            vector_chunks.append(
                {
                    "id": row_id,
                    "embedding": embedding,
                    "text": chunk,
                    "metadata": {
                        "source": source,
                        "source_type": source_type,
                        "title": title or source,
                        "chunk_id": index,
                        "embedding_provider": semantic.embedding_provider(),
                    },
                }
            )
        conn.commit()
    vector_result = vector_store.upsert_chunks(vector_chunks)
    observability.log_event(logger, "rag.ingest", source=source, source_type=source_type, chunks=len(chunks))
    return {
        "source": source,
        "source_type": source_type,
        "title": title or source,
        "chunks": len(chunks),
        "vector_backend": vector_result,
    }


def ingest_file(path: str | Path, source: str | None = None) -> dict:
    file_path = Path(path)
    extracted = document_ingestion.extract_path(file_path)
    if not extracted.success:
        return {
            "source": source or str(file_path),
            "source_type": "file",
            "title": file_path.name,
            "chunks": 0,
            "warnings": extracted.warnings,
            "vector_backend": vector_store.upsert_chunks([]),
        }
    result = ingest_text(source or str(file_path), extracted.text, source_type="file", title=file_path.name)
    result["warnings"] = extracted.warnings
    result["metadata"] = extracted.metadata
    return result


def ingest_url(url: str) -> dict:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Only http(s) URLs can be ingested.")
    html = _fetch_url_html(url)
    title, text = _html_to_text(html, url)
    return ingest_text(url, text, source_type="url", title=title)


def retrieve(query: str, top_k: int = 5, source_prefix: str | None = None) -> list[dict]:
    query_vector = semantic.embed_text(query)
    query_tokens = set(semantic.tokenize(query))
    external_rows = vector_store.query(query_vector, top_k * 4)
    with _conn() as conn:
        if external_rows:
            ids = [row["id"] for row in external_rows]
            placeholders = ", ".join(["?"] * len(ids))
            values = ids
            source_filter = ""
            if source_prefix:
                source_filter = " AND source LIKE ?"
                values = values + [source_prefix + "%"]
            rows = conn.execute(
                """
                SELECT id, source, source_type, title, chunk_id, text, embedding,
                       embedding_provider, embedding_dimensions
                FROM rag_chunks
                WHERE id IN (
                """
                + placeholders
                + ")"
                + source_filter,
                values,
            ).fetchall()
        else:
            source_filter = ""
            values = []
            if source_prefix:
                source_filter = " WHERE source LIKE ?"
                values.append(source_prefix + "%")
            rows = conn.execute(
                """
                SELECT id, source, source_type, title, chunk_id, text, embedding,
                       embedding_provider, embedding_dimensions
                FROM rag_chunks
                """
                + source_filter,
                values,
            ).fetchall()
    scored = []
    for row in rows:
        vector_score = semantic.cosine(query_vector, semantic.loads_vector(row["embedding"]))
        lexical_score = _lexical_score(query_tokens, row["text"])
        score = (0.75 * vector_score) + (0.25 * lexical_score)
        if score > 0:
            scored.append(
                {
                    "id": row["id"],
                    "source": row["source"],
                    "source_type": row["source_type"],
                    "title": row["title"] or row["source"],
                    "chunk_id": row["chunk_id"],
                    "text": row["text"],
                    "score": round(score, 4),
                    "vector_score": round(vector_score, 4),
                    "lexical_score": round(lexical_score, 4),
                    "citation": _citation(row["title"] or row["source"], row["chunk_id"]),
                    "embedding_provider": row["embedding_provider"],
                }
            )
    ranked = sorted(scored, key=lambda item: item["score"], reverse=True)[: top_k * 2]
    return _rerank(query, ranked)[:top_k]


def answer(query: str, top_k: int = 5, source_prefix: str | None = None) -> dict:
    passages = retrieve(query, top_k=top_k, source_prefix=source_prefix)
    if not passages:
        return {
            "success": False,
            "message": "No grounded passages found for that query.",
            "sources": [],
        }
    cfg = prompt_templates.config_for("rag_answer")
    response = brain.ask(
        prompt_templates.rag_answer_prompt(query, passages),
        temperature=cfg["temperature"],
        max_tokens=cfg["max_tokens"],
    )
    return {
        "success": True,
        "message": response,
        "sources": [
            {
                "source": item["source"],
                "source_type": item["source_type"],
                "title": item["title"],
                "chunk_id": item["chunk_id"],
                "score": item["score"],
                "citation": item["citation"],
            }
            for item in passages
        ],
    }


def list_sources() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT source, source_type, title, embedding_provider,
                   MAX(embedding_dimensions) as embedding_dimensions,
                   COUNT(*) as chunks, MAX(created_at) as last_ingested_at
            FROM rag_chunks
            GROUP BY source, source_type, title, embedding_provider
            ORDER BY last_ingested_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def cleanup_older_than(days: int) -> dict:
    with _conn() as conn:
        deleted = conn.execute(
            "DELETE FROM rag_chunks WHERE datetime(created_at) < datetime('now', ?)",
            (f"-{days} days",),
        ).rowcount
        conn.commit()
    return {"rag_chunks": deleted}


def _lexical_score(query_tokens: set[str], text: str) -> float:
    if not query_tokens:
        return 0.0
    text_tokens = set(semantic.tokenize(text))
    if not text_tokens:
        return 0.0
    return len(query_tokens & text_tokens) / len(query_tokens)


def _rerank(query: str, passages: list[dict]) -> list[dict]:
    mode = os.getenv("PERSONAL_OS_RERANKER", "lexical").lower()
    if mode != "llm" or len(passages) < 2:
        return passages
    try:
        prompt = (
            "Rerank passages for the query. Return JSON only: "
            '{"order": [passage_id_numbers_best_first]}.\n'
            "Query: " + query + "\n"
            "Passages:\n"
            + "\n".join(str(item["id"]) + ": " + item["text"][:500] for item in passages)
        )
        order = brain.ask_json(prompt, temperature=0.0).get("order", [])
        by_id = {item["id"]: item for item in passages}
        reranked = [by_id[item_id] for item_id in order if item_id in by_id]
        reranked.extend([item for item in passages if item not in reranked])
        for index, item in enumerate(reranked):
            item["rerank_position"] = index + 1
        return reranked
    except Exception:
        return passages


def _citation(title: str, chunk_id: int) -> str:
    return title + "#" + str(chunk_id)


def _fetch_url_html(url: str) -> str:
    response = requests.get(url, timeout=15, headers={"User-Agent": "PersonalOS/1.0"})
    response.raise_for_status()
    html = response.text
    if len(_html_to_text(html, url)[1]) >= 500 or os.getenv("PERSONAL_OS_PLAYWRIGHT_SCRAPE", "false").lower() != "true":
        return html
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=20000)
            html = page.content()
            browser.close()
            return html
    except Exception:
        return html


def _html_to_text(html: str, fallback_title: str) -> tuple[str, str]:
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        title = soup.title.string.strip() if soup.title and soup.title.string else fallback_title
        text = " ".join(soup.get_text(" ").split())
        return title, text
    except ModuleNotFoundError:
        parser = _TextExtractor(fallback_title)
        parser.feed(html)
        return parser.title or fallback_title, " ".join(parser.parts).strip()


class _TextExtractor(HTMLParser):
    def __init__(self, fallback_title: str):
        super().__init__()
        self.title = ""
        self.parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self._fallback_title = fallback_title

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        text = data.strip()
        if not text or self._skip_depth:
            return
        if self._in_title:
            self.title = text
        else:
            self.parts.append(text)
