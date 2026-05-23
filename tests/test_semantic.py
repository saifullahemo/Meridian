from backend.core import semantic


def test_local_embedding_fallback_when_ollama_fails(monkeypatch):
    monkeypatch.setattr(semantic, "EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setattr(semantic, "_embed_ollama", lambda text: (_ for _ in ()).throw(RuntimeError("offline")))

    vector = semantic.embed_text("api testing sql")

    assert len(vector) == semantic.DIMENSIONS
    assert semantic.cosine(vector, vector) > 0.99


def test_cosine_returns_zero_for_mixed_dimensions():
    assert semantic.cosine([1.0, 0.0], [1.0]) == 0.0


def test_semantic_status_reports_provider():
    status = semantic.status()

    assert status["provider"]
    assert "ready" in status
    assert "dimensions" in status
