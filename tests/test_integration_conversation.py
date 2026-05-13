from fastapi.testclient import TestClient

from backend.api.routes import conversation as conversation_route
from backend.api.routes import app_data
from backend.core import auth
from backend.data import database
from backend.main import app


def test_conversation_request_routes_to_handler_and_saves_memory(monkeypatch):
    calls = {}

    def fake_execute(route, context=None):
        calls["route"] = route
        calls["context"] = context
        return {
            "success": True,
            "message": "handled",
            "data": [],
            "action": "chat",
            "meta": {},
            "timestamp": "now",
        }

    monkeypatch.setattr(database, "init_all_tables", lambda: None)
    monkeypatch.setattr(conversation_route.universal_agent, "execute", fake_execute)
    monkeypatch.setattr(conversation_route.mem, "save_exchange", lambda *args, **kwargs: None)
    monkeypatch.setattr(conversation_route.rag, "ingest_text", lambda *args, **kwargs: {"chunks": 0})

    client = TestClient(app)
    response = client.post(
        "/api/conversation",
        data={"instruction": "Hello", "session_id": "test-session"},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "handled"
    assert calls["route"]["action"] == "read_data"
    assert calls["route"]["module"] is None
    assert calls["route"]["parameters"]["raw_instruction"] == "Hello"
    assert calls["context"] == {"session_id": "test-session"}


def test_api_key_protects_sensitive_endpoint(monkeypatch):
    monkeypatch.setattr(auth, "API_KEY", "secret")
    client = TestClient(app)

    blocked = client.get("/api/memory/sessions/list")
    allowed = client.get("/api/memory/sessions/list", headers={"X-API-Key": "secret"})

    assert blocked.status_code == 401
    assert allowed.status_code == 200


def test_chat_stream_emits_sse_for_non_streamed_action(monkeypatch):
    monkeypatch.setattr(database, "init_all_tables", lambda: None)
    monkeypatch.setattr(
        app_data.universal_agent,
        "execute",
        lambda route, context=None: {
            "success": True,
            "message": "saved",
            "data": [],
            "action": "save_data",
            "meta": {},
        },
    )
    monkeypatch.setattr(app_data.mem, "save_exchange", lambda *args, **kwargs: None)

    client = TestClient(app)
    response = client.post(
        "/api/chat/stream",
        json={"instruction": "Add expense $5 coffee", "session_id": "test-session"},
    )

    assert response.status_code == 200
    assert "event: meta" in response.text
    assert "event: final" in response.text
    assert "saved" in response.text
