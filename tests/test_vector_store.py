from backend.core import vector_store


def test_vector_store_disabled_for_sqlite(monkeypatch):
    monkeypatch.setattr(vector_store, "BACKEND", "sqlite")

    result = vector_store.upsert_chunks([])

    assert result == {"backend": "sqlite", "upserted": 0, "enabled": False}
    assert vector_store.query([0.0], 3) == []


def test_vector_store_status_reports_missing_chroma(monkeypatch):
    monkeypatch.setattr(vector_store, "BACKEND", "chroma")
    monkeypatch.setattr(vector_store, "_chroma_collection", lambda: (_ for _ in ()).throw(RuntimeError("missing")))

    status = vector_store.status()

    assert status["backend"] == "chroma"
    assert status["ready"] is False
