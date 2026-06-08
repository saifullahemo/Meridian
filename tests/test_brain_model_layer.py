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


def test_ask_allows_larger_outputs_for_large_token_budget(monkeypatch):
    monkeypatch.setattr(brain, "_available_backends", lambda: ["groq"])
    monkeypatch.setattr(brain, "_ask_groq", lambda **kwargs: "x" * 15000)

    result = brain.ask("rewrite code", max_tokens=6000)

    assert len(result) == 15000


def test_status_reports_configured_backends(monkeypatch):
    monkeypatch.setattr(brain, "MODEL_BACKEND", "auto")
    monkeypatch.setattr(brain, "MODEL_ORDER", ["groq", "ollama", "openrouter", "gemini"])
    monkeypatch.setattr(brain, "GROQ_API_KEY", "")
    monkeypatch.setattr(brain, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(brain, "GEMINI_API_KEY", "")
    monkeypatch.setattr(brain, "is_ollama_available", lambda: True)

    status = brain.get_status()

    assert status["ready"] is True
    assert status["active_backend"] == "ollama"
    assert status["ollama_available"] is True


def test_ask_falls_back_to_openrouter(monkeypatch):
    calls = []
    monkeypatch.setattr(brain, "MODEL_BACKEND", "auto")
    monkeypatch.setattr(brain, "MODEL_ORDER", ["groq", "ollama", "openrouter"])
    monkeypatch.setattr(brain, "GROQ_API_KEY", "key")
    monkeypatch.setattr(brain, "OPENROUTER_API_KEY", "router-key")
    monkeypatch.setattr(brain, "is_ollama_available", lambda: False)
    monkeypatch.setattr(brain, "_ask_groq", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("rate limited")))

    def fake_openrouter(*args, **kwargs):
        calls.append("openrouter")
        return "router answer"

    monkeypatch.setattr(brain, "_ask_openrouter", fake_openrouter)

    assert brain.ask("hello") == "router answer"
    assert calls == ["openrouter"]


def test_ask_falls_back_to_gemini(monkeypatch):
    calls = []
    monkeypatch.setattr(brain, "MODEL_BACKEND", "auto")
    monkeypatch.setattr(brain, "MODEL_ORDER", ["groq", "gemini"])
    monkeypatch.setattr(brain, "GROQ_API_KEY", "key")
    monkeypatch.setattr(brain, "GEMINI_API_KEY", "gemini-key")
    monkeypatch.setattr(brain, "_ask_groq", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("rate limited")))

    def fake_gemini(*args, **kwargs):
        calls.append("gemini")
        return "gemini answer"

    monkeypatch.setattr(brain, "_ask_gemini", fake_gemini)

    assert brain.ask("hello") == "gemini answer"
    assert calls == ["gemini"]


def test_openrouter_chat_completion_parses_response(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "router ok"}}]}

    monkeypatch.setattr(brain, "OPENROUTER_API_KEY", "key")
    monkeypatch.setattr(brain.requests, "post", lambda *args, **kwargs: Response())

    assert brain._ask_openrouter("hello", None, 0.1, 50) == "router ok"


def test_gemini_generate_content_parses_response(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "gemini ok"}]}}]}

    monkeypatch.setattr(brain, "GEMINI_API_KEY", "key")
    monkeypatch.setattr(brain.requests, "post", lambda *args, **kwargs: Response())

    assert brain._ask_gemini("hello", None, 0.1, 50) == "gemini ok"
