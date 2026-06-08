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


def test_project_review_uploaded_notebook_uses_file_content(tmp_path, monkeypatch):
    _use_tmp_project_db(monkeypatch, tmp_path)
    prompts = []

    def fake_ask(prompt, **kwargs):
        prompts.append(prompt)
        if "Uploaded file content:" in prompt:
            return "Review: preprocessing should avoid leakage before train/test split."
        return "Notebook with stress prediction code."

    monkeypatch.setattr(project_core.brain, "ask", fake_ask)

    notebook = (
        b'{"cells":[{"cell_type":"code","source":["from catboost import CatBoostClassifier\\n",'
        b'"scaler.fit_transform(X)\\n"]}]}'
    )
    client = TestClient(app)
    project_id = client.post("/api/projects", json={"name": "Notebook Review"}).json()["project"]["id"]
    uploaded = client.post(
        f"/api/projects/{project_id}/files",
        files={"files": ("catboost_stress_predict (1).ipynb", notebook, "application/x-ipynb+json")},
    )

    response = client.post(
        f"/api/projects/{project_id}/chat",
        data={"instruction": "catboost_stress_predict (1).ipynb check the full code"},
    )

    assert uploaded.status_code == 200
    assert response.status_code == 200
    assert response.json()["action"] == "project_file_review"
    assert "preprocessing" in response.json()["message"]
    review_prompt = prompts[-1]
    assert "catboost_stress_predict (1).ipynb" in review_prompt
    assert "scaler.fit_transform" in review_prompt


def test_project_rewrite_uploaded_notebook_creates_code_artifact(tmp_path, monkeypatch):
    _use_tmp_project_db(monkeypatch, tmp_path)
    prompts = []
    complete_code = """```python
import numpy as np
from sklearn.ensemble import RandomForestClassifier

def make_features(values):
    return np.asarray(values, dtype=float).reshape(-1, 1)

def train_random_forest(X, y):
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X, y)
    return model

def main():
    X = make_features([1, 2, 3, 4, 5, 6])
    y = np.asarray([0, 0, 1, 1, 0, 1])
    model = train_random_forest(X, y)
    print(model.predict(X))

if __name__ == '__main__':
    main()
```"""

    def fake_ask(prompt, **kwargs):
        prompts.append(prompt)
        if "complete rewritten implementation" in prompt:
            return complete_code
        return "Notebook with CatBoost code."

    monkeypatch.setattr(project_core.brain, "ask", fake_ask)

    notebook = (
        b'{"cells":[{"cell_type":"code","source":["from catboost import CatBoostClassifier\\n",'
        b'"model = CatBoostClassifier()\\n"]}]}'
    )
    client = TestClient(app)
    project_id = client.post("/api/projects", json={"name": "Random Forest Rewrite"}).json()["project"]["id"]
    uploaded = client.post(
        f"/api/projects/{project_id}/files",
        files={"files": ("catboost_mmash (1).ipynb", notebook, "application/x-ipynb+json")},
    )

    response = client.post(
        f"/api/projects/{project_id}/chat",
        data={"instruction": "rewrite the code for random forest"},
    )

    assert uploaded.status_code == 200
    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "project_file_rewrite"
    assert "RandomForestClassifier" in body["message"]
    assert body["meta"]["artifacts"][0]["type"] == "code"
    rewrite_prompt = prompts[1]
    assert "CatBoostClassifier" in rewrite_prompt
    assert "complete rewritten implementation" in rewrite_prompt


def test_project_complete_code_followup_returns_latest_code_artifact(tmp_path, monkeypatch):
    _use_tmp_project_db(monkeypatch, tmp_path)
    calls = {"ask": 0}

    def fake_ask(prompt, **kwargs):
        calls["ask"] += 1
        if "complete rewritten implementation" in prompt:
            return "```python\nfrom sklearn.ensemble import RandomForestClassifier\nmodel = RandomForestClassifier()\n```"
        return "Notebook with CatBoost code."

    monkeypatch.setattr(project_core.brain, "ask", fake_ask)

    notebook = b'{"cells":[{"cell_type":"code","source":["from catboost import CatBoostClassifier\\n"]}]}'
    client = TestClient(app)
    project_id = client.post("/api/projects", json={"name": "Followup Code"}).json()["project"]["id"]
    client.post(
        f"/api/projects/{project_id}/files",
        files={"files": ("catboost_mmash.ipynb", notebook, "application/x-ipynb+json")},
    )
    client.post(f"/api/projects/{project_id}/chat", data={"instruction": "rewrite the code for random forest"})
    calls_after_rewrite = calls["ask"]

    response = client.post(f"/api/projects/{project_id}/chat", data={"instruction": "write me the complete code"})

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "project_code_artifact"
    assert "RandomForestClassifier" in body["message"]
    assert body["meta"]["artifacts"][0]["type"] == "code"
    assert calls["ask"] == calls_after_rewrite


def test_project_chat_model_error_returns_json_error(tmp_path, monkeypatch):
    _use_tmp_project_db(monkeypatch, tmp_path)
    monkeypatch.setattr(project_core.brain, "ask", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("backend down")))

    client = TestClient(app)
    project_id = client.post("/api/projects", json={"name": "Model Error"}).json()["project"]["id"]
    response = client.post(f"/api/projects/{project_id}/chat", data={"instruction": "hello"})

    assert response.status_code == 502
    assert "Project chat failed" in response.json()["detail"]


def test_project_chat_rate_limit_returns_actionable_error(tmp_path, monkeypatch):
    _use_tmp_project_db(monkeypatch, tmp_path)
    monkeypatch.setattr(
        project_core.brain,
        "ask",
        lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError("No model backend available. groq: 429 Too Many Requests")),
    )

    client = TestClient(app)
    project_id = client.post("/api/projects", json={"name": "Rate Limit"}).json()["project"]["id"]
    response = client.post(f"/api/projects/{project_id}/chat", data={"instruction": "hello"})

    assert response.status_code == 429
    assert "start Ollama" in response.json()["detail"]


def test_project_rewrite_continues_truncated_code(tmp_path, monkeypatch):
    _use_tmp_project_db(monkeypatch, tmp_path)
    calls = []

    def fake_ask(prompt, **kwargs):
        calls.append({"prompt": prompt, "max_tokens": kwargs.get("max_tokens")})
        if "Continue the incomplete code response" in prompt:
            return "    n_estimators=100,\n    random_state=42,\n)\nprint('done')\n```"
        if "failed validation" in prompt:
            return """```python
import numpy as np
from sklearn.ensemble import RandomForestClassifier

def main():
    X = np.asarray([[1.0], [2.0], [3.0], [4.0], [5.0], [6.0]])
    y = np.asarray([0, 0, 1, 1, 0, 1])
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X, y)
    print('done')

if __name__ == '__main__':
    main()
```"""
        if "complete rewritten implementation" in prompt:
            return "```python\nfrom sklearn.ensemble import RandomForestClassifier\nmodel = RandomForestClassifier(\n"
        return "Notebook with CatBoost code."

    monkeypatch.setattr(project_core.brain, "ask", fake_ask)

    notebook = b'{"cells":[{"cell_type":"code","source":["from catboost import CatBoostClassifier\\n"]}]}'
    client = TestClient(app)
    project_id = client.post("/api/projects", json={"name": "Continue Rewrite"}).json()["project"]["id"]
    client.post(
        f"/api/projects/{project_id}/files",
        files={"files": ("catboost_mmash.ipynb", notebook, "application/x-ipynb+json")},
    )

    response = client.post(f"/api/projects/{project_id}/chat", data={"instruction": "rewrite complete code for random forest"})

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "project_file_rewrite"
    assert "print('done')" in body["message"]
    assert "[Note: The generated code may still be incomplete" not in body["message"]
    assert any(call["max_tokens"] == project_core.CODE_REWRITE_CONTINUATION_TOKENS for call in calls)


def test_project_continue_code_followup_appends_latest_artifact(tmp_path, monkeypatch):
    _use_tmp_project_db(monkeypatch, tmp_path)
    calls = []

    def fake_ask(prompt, **kwargs):
        calls.append(prompt)
        if "Continue the latest project code artifact" in prompt:
            return "    f1 = f1_score(y_test, y_pred, average='weighted')\nprint('complete')\n```"
        if "complete rewritten implementation" in prompt:
            return (
                "```python\nfrom sklearn.ensemble import RandomForestClassifier\n"
                "fold_f1s = []\nfor train_idx, test_idx in splits:\n    f1 =\n\n"
                "[Note: The generated code may still be incomplete because the model output ended before a clean stopping point. Ask: continue the code from the last line.]"
            )
        return "Notebook with code."

    monkeypatch.setattr(project_core.brain, "ask", fake_ask)

    notebook = b'{"cells":[{"cell_type":"code","source":["from catboost import CatBoostClassifier\\n"]}]}'
    client = TestClient(app)
    project_id = client.post("/api/projects", json={"name": "Continue Artifact"}).json()["project"]["id"]
    client.post(
        f"/api/projects/{project_id}/files",
        files={"files": ("catboost_mmash.ipynb", notebook, "application/x-ipynb+json")},
    )
    client.post(f"/api/projects/{project_id}/chat", data={"instruction": "rewrite the code for random forest"})

    response = client.post(f"/api/projects/{project_id}/chat", data={"instruction": "continue the code from the last line"})

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "project_code_continue"
    assert "print('complete')" in body["message"]
    assert "Continue the latest project code artifact" in calls[-1]
    artifact_content = body["meta"]["artifacts"][0]["content"]
    assert "[Note: The generated code may still be incomplete" not in artifact_content
    assert "print('complete')" in artifact_content


def test_project_rewrite_repairs_generic_placeholder_code(tmp_path, monkeypatch):
    _use_tmp_project_db(monkeypatch, tmp_path)
    calls = []

    bad_code = """```python
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

def load_dataset(path):
    return pd.read_csv(path + '/mmash_dataset.csv')

model = RandomForestClassifier()
```"""
    good_code = """```python
import os
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score

MMASH_PATH = '/real/mmash/path'

def load_rr(path):
    df = pd.read_csv(path)
    return df.iloc[:, -1].dropna().to_numpy()

def load_actigraph(path):
    return pd.read_csv(path)

def extract_features_for_subject(subject_dir):
    rr = load_rr(os.path.join(subject_dir, 'RR_interval.csv'))
    acti = load_actigraph(os.path.join(subject_dir, 'Actigraph.csv'))
    return np.array([[float(np.mean(rr)), float(acti.shape[0])]])

def main():
    subjects = [p for p in os.listdir(MMASH_PATH) if os.path.isdir(os.path.join(MMASH_PATH, p))]
    X = []
    y = []
    for idx, sid in enumerate(subjects):
        X.append(extract_features_for_subject(os.path.join(MMASH_PATH, sid))[0])
        y.append(idx % 2)
    model = RandomForestClassifier(n_estimators=200, random_state=42)
    model.fit(np.asarray(X), np.asarray(y))
    print('Training accuracy:', accuracy_score(y, model.predict(np.asarray(X))))

if __name__ == '__main__':
    main()
```"""

    def fake_ask(prompt, **kwargs):
        calls.append(prompt)
        if "failed validation" in prompt:
            return good_code
        if "complete rewritten implementation" in prompt:
            return bad_code
        return "Notebook summary"

    monkeypatch.setattr(project_core.brain, "ask", fake_ask)

    notebook = (
        b'{"cells":[{"cell_type":"code","source":["MMASH_PATH = \'/real/mmash/path\'\\n",'
        b'"def load_rr(path): pass\\n","def load_actigraph(path): pass\\n",'
        b'"for sid in SUBJECT_IDS: pass\\n"]}]}'
    )
    client = TestClient(app)
    project_id = client.post("/api/projects", json={"name": "Repair Placeholder"}).json()["project"]["id"]
    client.post(
        f"/api/projects/{project_id}/files",
        files={"files": ("catboost_mmash.ipynb", notebook, "application/x-ipynb+json")},
    )

    response = client.post(
        f"/api/projects/{project_id}/chat",
        data={"instruction": "rewrite the complete code for random forest as one runnable python script, do not use placeholders"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "project_file_rewrite"
    assert "mmash_dataset.csv" not in body["message"]
    assert "load_rr" in body["message"]
    assert body["meta"]["code_quality"]["ok"] is True
    assert any("failed validation" in call for call in calls)


def test_project_not_complete_repairs_latest_code_artifact(tmp_path, monkeypatch):
    _use_tmp_project_db(monkeypatch, tmp_path)
    calls = []

    bad_code = """```python
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
data = pd.read_csv('mmash_dataset.csv')
model = RandomForestClassifier()
```"""
    repaired_code = """```python
import os
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

def load_rr(path):
    return pd.read_csv(path).iloc[:, -1].to_numpy()

def main():
    rows = []
    labels = []
    for sid in SUBJECT_IDS:
        rr = load_rr(os.path.join(MMASH_PATH, sid, 'RR_interval.csv'))
        rows.append([float(np.mean(rr))])
        labels.append(0)
    RandomForestClassifier(random_state=42).fit(np.asarray(rows), np.asarray(labels))

if __name__ == '__main__':
    main()
```"""

    def fake_ask(prompt, **kwargs):
        calls.append(prompt)
        if "failed validation" in prompt:
            return repaired_code
        return "summary"

    monkeypatch.setattr(project_core.brain, "ask", fake_ask)

    notebook = b'{"cells":[{"cell_type":"code","source":["MMASH_PATH = \'/x\'\\n","SUBJECT_IDS = []\\n","def load_rr(path): pass\\n"]}]}'
    client = TestClient(app)
    project_id = client.post("/api/projects", json={"name": "Repair Latest"}).json()["project"]["id"]
    client.post(
        f"/api/projects/{project_id}/files",
        files={"files": ("catboost_mmash.ipynb", notebook, "application/x-ipynb+json")},
    )
    project_core._create_project_artifact(project_id, "Random Forest rewrite - catboost_mmash.ipynb", "code", bad_code)

    response = client.post(f"/api/projects/{project_id}/chat", data={"instruction": "its not complete code please fix"})

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "project_code_repair"
    assert "mmash_dataset.csv" not in body["message"]
    assert "load_rr" in body["message"]
    assert any("failed validation" in call for call in calls)


def test_project_code_completeness_check_is_direct(tmp_path, monkeypatch):
    _use_tmp_project_db(monkeypatch, tmp_path)
    monkeypatch.setattr(project_core.brain, "ask", lambda *args, **kwargs: "summary")

    client = TestClient(app)
    project_id = client.post("/api/projects", json={"name": "Completeness"}).json()["project"]["id"]
    project_core._create_project_artifact(
        project_id,
        "Random Forest rewrite - bad.py",
        "code",
        "```python\nimport pandas as pd\ndata = pd.read_csv('mmash_dataset.csv')\n```",
    )

    response = client.post(f"/api/projects/{project_id}/chat", data={"instruction": "is this code complete"})

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "project_code_check"
    assert "Short answer: no" in body["message"]
    assert "mmash_dataset.csv" in body["message"]


def test_project_simple_explanation_uses_plain_language(tmp_path, monkeypatch):
    _use_tmp_project_db(monkeypatch, tmp_path)
    monkeypatch.setattr(project_core.brain, "ask", lambda *args, **kwargs: "generic")

    client = TestClient(app)
    project_id = client.post("/api/projects", json={"name": "Explain"}).json()["project"]["id"]
    response = client.post(
        f"/api/projects/{project_id}/chat",
        data={"instruction": "i dont understand the CNN model, the Random Forest classifier"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "project_simple_explanation"
    assert "Simple version" in body["message"]
    assert "CNN model is a deep-learning model" in body["message"]
    assert "Random Forest classifier is a simpler" in body["message"]
