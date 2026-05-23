from backend.core import rag


def test_chunk_text_uses_overlap():
    chunks = rag.chunk_text("a" * 1200, chunk_chars=500, overlap=100)

    assert len(chunks) == 3
    assert chunks[0] == "a" * 500


def test_ingest_and_retrieve_text(tmp_path, monkeypatch):
    monkeypatch.setattr(rag.database, "DB_PATH", tmp_path / "rag.db")

    result = rag.ingest_text("notes.txt", "Acme interview focuses on API testing and SQL.")
    hits = rag.retrieve("API testing", top_k=2)

    assert result["source"] == "notes.txt"
    assert result["source_type"] == "text"
    assert result["title"] == "notes.txt"
    assert result["chunks"] == 1
    assert hits
    assert hits[0]["source"] == "notes.txt"
    assert "API testing" in hits[0]["text"]
    assert hits[0]["citation"] == "notes.txt#0"


def test_retrieve_can_filter_by_session_source_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(rag.database, "DB_PATH", tmp_path / "rag-session.db")

    source = rag.session_file_source("session-one", "model.py")
    rag.ingest_text(source, "CNN rewrite uses Conv2D and MaxPooling.", source_type="session_file", title="model.py")
    rag.ingest_text(rag.session_file_source("session-two", "other.py"), "Unrelated SQL notes.", source_type="session_file", title="other.py")

    hits = rag.retrieve("CNN Conv2D", source_prefix=rag.session_source_prefix("session-one"))

    assert hits
    assert hits[0]["source"] == source
    assert hits[0]["title"] == "model.py"


def test_ingest_url_extracts_page_text(tmp_path, monkeypatch):
    monkeypatch.setattr(rag.database, "DB_PATH", tmp_path / "rag-url.db")

    class Response:
        text = "<html><head><title>Acme Notes</title></head><body><script>x()</script><p>API testing SQL prep.</p></body></html>"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(rag.requests, "get", lambda *args, **kwargs: Response())

    result = rag.ingest_url("https://example.com/acme")
    hits = rag.retrieve("SQL prep")

    assert result["source_type"] == "url"
    assert result["title"] == "Acme Notes"
    assert hits[0]["source"] == "https://example.com/acme"


def test_cleanup_older_than_removes_old_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(rag.database, "DB_PATH", tmp_path / "rag-retention.db")
    rag.ingest_text("old.txt", "old API testing notes")
    with rag._conn() as conn:
        conn.execute("UPDATE rag_chunks SET created_at = datetime('now', '-10 days')")
        conn.commit()

    deleted = rag.cleanup_older_than(5)

    assert deleted["rag_chunks"] == 1
    assert rag.retrieve("API testing") == []
