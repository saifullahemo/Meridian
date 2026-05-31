from backend.core import brain


def test_ask_falls_back_from_groq_to_ollama(monkeypatch):
    calls = []
    monkeypatch.setattr(brain, "MODEL_BACKEND", "auto")
    monkeypatch.setattr(brain, "GROQ_API_KEY", "key")
    monkeypatch.setattr(brain, "is_ollama_available", lambda: True)
    monkeypatch.setattr(brain, "_ask_groq", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("groq down")))

    def fake_ollama(*args, **kwargs):
        calls.append("ollama")
        return "local answer"

    monkeypatch.setattr(brain, "_ask_ollama", fake_ollama)

    assert brain.ask("hello") == "local answer"
    assert calls == ["ollama"]


def test_ask_stream_uses_ollama_when_configured(monkeypatch):
    monkeypatch.setattr(brain, "MODEL_BACKEND", "ollama")
    monkeypatch.setattr(brain, "is_ollama_available", lambda: True)
    monkeypatch.setattr(brain, "_stream_ollama", lambda *args, **kwargs: iter(["a", "b"]))

    assert list(brain.ask_stream("hello")) == ["a", "b"]


def test_stream_groq_parses_openai_sse(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_lines(self):
            return iter([
                b'data: {"choices":[{"delta":{"content":"hi"}}]}',
                b'data: {"choices":[{"delta":{"content":" there"}}]}',
                b"data: [DONE]",
            ])

    monkeypatch.setattr(brain.requests, "post", lambda *args, **kwargs: Response())

    assert list(brain._stream_groq("hello", None, 0.1)) == ["hi", " there"]


def test_status_reports_configured_backends(monkeypatch):
    monkeypatch.setattr(brain, "MODEL_BACKEND", "auto")
    monkeypatch.setattr(brain, "GROQ_API_KEY", "")
    monkeypatch.setattr(brain, "is_ollama_available", lambda: True)

    status = brain.get_status()

    assert status["ready"] is True
    assert status["active_backend"] == "ollama"
    assert status["ollama_available"] is True
