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


def test_conversation_upload_uses_document_ingestion(monkeypatch):
    calls = {}

    def fake_execute(route, context=None):
        calls["route"] = route
        return {
            "success": True,
            "message": "handled file",
            "data": [],
            "action": "chat",
            "meta": {},
            "timestamp": "now",
        }

    monkeypatch.setattr(database, "init_all_tables", lambda: None)
    monkeypatch.setattr(conversation_route.universal_agent, "execute", fake_execute)
    monkeypatch.setattr(conversation_route.mem, "save_exchange", lambda *args, **kwargs: None)
    ingested = {}

    def fake_ingest(source, text, **kwargs):
        ingested["source"] = source
        ingested["text"] = text
        ingested["kwargs"] = kwargs
        return {"chunks": 1}

    monkeypatch.setattr(conversation_route.rag, "ingest_text", fake_ingest)

    client = TestClient(app)
    response = client.post(
        "/api/conversation",
        data={"instruction": "Summarize this", "session_id": "test-session"},
        files={"files": ("notes.txt", b"Acme interview is Friday.", "text/plain")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "handled file"
    assert payload["meta"]["documents"][0]["success"] is True
    assert ingested["source"] == "session:test-session:file:notes.txt"
    assert ingested["kwargs"]["source_type"] == "session_file"
    assert "--- FILE: notes.txt ---" in calls["route"]["parameters"]["raw_instruction"]
    assert "Acme interview is Friday" in calls["route"]["parameters"]["raw_instruction"]


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


def test_proactive_api_endpoints(monkeypatch, tmp_path):
    monkeypatch.setattr(app_data.database, "DB_PATH", tmp_path / "api-proactive.db")
    monkeypatch.setattr(auth, "API_KEY", "")

    client = TestClient(app)
    created = client.post(
        "/api/scheduled-tasks",
        json={"name": "Weekly search", "instruction": "Every Monday search QA jobs", "frequency": "weekly"},
    )
    listed = client.get("/api/scheduled-tasks")
    briefing = client.get("/api/proactive/briefing")

    assert created.status_code == 200
    assert created.json()["task"]["name"] == "Weekly search"
    assert listed.status_code == 200
    assert listed.json()["tasks"]
    assert briefing.status_code == 200
    assert "briefing" in briefing.json()["message"].lower()


def test_dynamic_module_api_crud(monkeypatch, tmp_path):
    config_path = tmp_path / "modules.json"
    config_path.write_text('{"modules": {}}')
    monkeypatch.setattr(app_data, "CONFIG", config_path)
    monkeypatch.setattr(app_data.schema_engine, "CONFIG_PATH", config_path)
    monkeypatch.setattr(app_data.schema_engine, "_create_excel_file", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_data.database, "DB_PATH", tmp_path / "modules.db")

    client = TestClient(app)
    schema = {
        "label": "Pet Care",
        "icon": "",
        "description": "Track pets without a hardcoded category",
        "fields": [
            {"name": "pet_name", "type": "text", "required": True},
            {"name": "status", "type": "enum", "required": True, "options": ["planned", "done"]},
        ],
    }

    created = client.post("/api/modules", json={"key": "pets", "schema": schema})
    assert created.status_code == 200
    assert created.json()["module_key"] == "pets"

    record = client.post("/api/modules/pets/records", json={"data": {"pet_name": "Milo", "status": "planned"}})
    assert record.status_code == 200
    assert record.json()["record"]["pet_name"] == "Milo"

    schema["fields"].append({"name": "vaccine_date", "type": "date", "required": False})
    updated = client.put("/api/modules/pets", json={"key": "pets", "schema": schema})
    assert updated.status_code == 200

    listed = client.get("/api/modules/pets/records")
    assert listed.status_code == 200
    assert listed.json()["records"][0]["pet_name"] == "Milo"

    deleted = client.delete("/api/modules/pets?drop_data=true")
    assert deleted.status_code == 200
    assert deleted.json()["dropped_data"] is True
