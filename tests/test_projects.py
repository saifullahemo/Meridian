from fastapi.testclient import TestClient

from backend.core import auth
from backend.core import projects as project_core
from backend.main import app


def _use_tmp_project_db(monkeypatch, tmp_path):
    db_path = tmp_path / "projects.db"
    monkeypatch.setattr(project_core.database, "DB_PATH", db_path)
    monkeypatch.setattr(project_core.memory, "DB_PATH", db_path)
    monkeypatch.setattr(auth, "API_KEY", "")


def test_project_crud_and_history(tmp_path, monkeypatch):
    _use_tmp_project_db(monkeypatch, tmp_path)
    monkeypatch.setattr(project_core.brain, "ask", lambda *args, **kwargs: "Project answer")
    monkeypatch.setattr(project_core, "retrieve_project_sources", lambda *args, **kwargs: [])

    client = TestClient(app)
    created = client.post(
        "/api/projects",
        json={
            "name": "CNN Rewrite",
            "description": "Rewrite uploaded model code",
            "instructions": "Produce runnable Python when possible.",
        },
    )

    assert created.status_code == 200
    project_id = created.json()["project"]["id"]

    chat = client.post(
        f"/api/projects/{project_id}/chat",
        data={"instruction": "What is this project about?"},
    )
    history = client.get(f"/api/projects/{project_id}/history")

    assert chat.status_code == 200
    assert chat.json()["message"] == "Project answer"
    assert history.status_code == 200
    assert [item["role"] for item in history.json()["history"]][-2:] == ["user", "assistant"]


def test_project_file_upload_is_project_scoped(tmp_path, monkeypatch):
    _use_tmp_project_db(monkeypatch, tmp_path)
    prompts = []

    def fake_ask(prompt, **kwargs):
        prompts.append(prompt)
        return "Contains CNN code."

    monkeypatch.setattr(project_core.brain, "ask", fake_ask)

    client = TestClient(app)
    project_id = client.post("/api/projects", json={"name": "Code Files"}).json()["project"]["id"]
    uploaded = client.post(
        f"/api/projects/{project_id}/files",
        files={"files": ("model.py", b"import torch\nclass CNN: pass", "text/x-python")},
    )
    detail = client.get(f"/api/projects/{project_id}")

    assert uploaded.status_code == 200
    file_info = uploaded.json()["files"][0]
    assert file_info["filename"] == "model.py"
    assert file_info["status"] == "indexed"
    assert file_info["source"].startswith(f"project:{project_id}:file:")
    assert detail.json()["project"]["files"][0]["filename"] == "model.py"


def test_project_chat_prompt_includes_project_context(tmp_path, monkeypatch):
    _use_tmp_project_db(monkeypatch, tmp_path)
    captured = {}

    def fake_ask(prompt, **kwargs):
        captured["prompt"] = prompt
        return "Use Conv2D layers."

    monkeypatch.setattr(project_core.brain, "ask", fake_ask)

    client = TestClient(app)
    project_id = client.post(
        "/api/projects",
        json={
            "name": "CNN Research",
            "description": "Turn uploaded Python code into a CNN.",
            "instructions": "Do not ask me to re-upload files if project context has them.",
        },
    ).json()["project"]["id"]

    response = client.post(
        f"/api/projects/{project_id}/chat",
        data={"instruction": "Rewrite the code I uploaded earlier."},
    )

    assert response.status_code == 200
    assert "Project workspace:" in captured["prompt"]
    assert "CNN Research" in captured["prompt"]
    assert "Do not ask me to re-upload" in captured["prompt"]
    assert "Rewrite the code I uploaded earlier" in captured["prompt"]


def test_project_memory_and_actions(tmp_path, monkeypatch):
    _use_tmp_project_db(monkeypatch, tmp_path)
    monkeypatch.setattr(project_core.brain, "ask", lambda *args, **kwargs: "normal answer")

    client = TestClient(app)
    project_id = client.post("/api/projects", json={"name": "Memory Project"}).json()["project"]["id"]

    remembered = client.post(
        f"/api/projects/{project_id}/chat",
        data={"instruction": "Remember that I prefer short explanations"},
    )
    listed = client.post(
        f"/api/projects/{project_id}/chat",
        data={"instruction": "show project memory"},
    )

    assert remembered.status_code == 200
    assert remembered.json()["action"] == "project_memory_save"
    assert listed.status_code == 200
    assert "short explanations" in listed.json()["message"]


def test_project_delete_requires_confirm_name(tmp_path, monkeypatch):
    _use_tmp_project_db(monkeypatch, tmp_path)

    client = TestClient(app)
    project_id = client.post("/api/projects", json={"name": "Delete Me"}).json()["project"]["id"]

    blocked = client.delete(f"/api/projects/{project_id}")
    deleted = client.delete(f"/api/projects/{project_id}?confirm_name=Delete%20Me")

    assert blocked.status_code == 409
    assert deleted.status_code == 200


def test_project_file_toggle_excludes_source_from_retrieval(tmp_path, monkeypatch):
    _use_tmp_project_db(monkeypatch, tmp_path)
    monkeypatch.setattr(project_core.brain, "ask", lambda *args, **kwargs: "summary")

    client = TestClient(app)
    project_id = client.post("/api/projects", json={"name": "Sources"}).json()["project"]["id"]
    file_info = client.post(
        f"/api/projects/{project_id}/files",
        files={"files": ("notes.txt", b"CNN layer notes with Conv2D.", "text/plain")},
    ).json()["files"][0]

    before = client.post(f"/api/projects/{project_id}/query", json={"query": "Conv2D", "answer": False})
    disabled = client.put(f"/api/projects/{project_id}/files/{file_info['id']}", json={"enabled": False})
    after = client.post(f"/api/projects/{project_id}/query", json={"query": "Conv2D", "answer": False})

    assert before.status_code == 200
    assert before.json()["results"]
    assert disabled.status_code == 200
    assert disabled.json()["file"]["enabled"] is False
    assert after.json()["results"] == []
