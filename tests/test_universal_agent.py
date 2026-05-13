import pytest

from backend.agents import universal_agent


def route(action, module="jobs", **params):
    return {
        "action": action,
        "module": module,
        "parameters": {"raw_instruction": action, **params},
        "steps": [],
    }


def test_execute_unknown_action_falls_back_to_chat(monkeypatch):
    monkeypatch.setattr(universal_agent.brain, "ask", lambda *args, **kwargs: "chat response")

    result = universal_agent.execute(route("unknown_action", None, raw_instruction="hello"))

    assert result["success"] is True
    assert result["action"] == "chat"
    assert result["message"] == "chat response"


def test_execute_multi_step_stops_on_failure(monkeypatch):
    monkeypatch.setattr(universal_agent.database, "table_exists", lambda module: False)

    result = universal_agent.execute(
        {
            "action": "multi_step",
            "steps": [
                route("read_data", "jobs"),
                route("update_data", "jobs"),
            ],
        }
    )

    assert result["success"] is True
    assert result["action"] == "multi_step"
    assert "Step 1:" in result["message"]
    assert "Step 2:" in result["message"]
    assert "Stopped at step 2." in result["message"]


def test_save_handler(monkeypatch):
    monkeypatch.setattr(universal_agent.database, "table_exists", lambda module: True)
    monkeypatch.setattr(universal_agent.database, "insert", lambda module, data: 42)
    monkeypatch.setattr(universal_agent.database, "select_one", lambda module, record_id: {"id": record_id, "company": "Acme"})
    monkeypatch.setattr(universal_agent.excel_manager, "append_row", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        universal_agent,
        "_load_modules",
        lambda: {"jobs": {"fields": [{"name": "date_applied"}]}},
    )

    result = universal_agent.execute(route("save_data", company="Acme"))

    assert result["success"] is True
    assert result["action"] == "save_data"
    assert result["data"]["id"] == 42


def test_read_handler_with_module(monkeypatch):
    monkeypatch.setattr(universal_agent.database, "table_exists", lambda module: True)
    monkeypatch.setattr(universal_agent.database, "select", lambda *args, **kwargs: [{"id": 1}])
    monkeypatch.setattr(universal_agent.database, "count", lambda module: 1)
    monkeypatch.setattr(universal_agent.brain, "ask", lambda *args, **kwargs: "one record")

    result = universal_agent.execute(route("read_data"))

    assert result["success"] is True
    assert result["action"] == "read_data"
    assert result["meta"]["total"] == 1
    assert result["meta"]["returned"] == 1
    assert "latency_ms" in result["meta"]


def test_read_handler_without_module_uses_chat(monkeypatch):
    monkeypatch.setattr(universal_agent.brain, "ask", lambda *args, **kwargs: "hello")

    result = universal_agent.execute(route("read_data", None, raw_instruction="hello"))

    assert result["success"] is True
    assert result["action"] == "chat"


def test_update_handler(monkeypatch):
    monkeypatch.setattr(universal_agent.database, "update", lambda module, record_id, data: True)
    monkeypatch.setattr(universal_agent.database, "select_one", lambda module, record_id: {"id": record_id, "status": "interview"})
    monkeypatch.setattr(universal_agent.excel_manager, "sync_module", lambda module: None)

    result = universal_agent.execute(route("update_data", id=7, status="interview"))

    assert result["success"] is True
    assert result["action"] == "update_data"
    assert result["data"]["status"] == "interview"


def test_update_handler_infers_jobs_and_status_for_natural_language(monkeypatch):
    records = [
        {"id": 1, "company": "Acme", "position": "QA", "status": "applied"},
        {"id": 2, "company": "Beta", "position": "SQA", "status": "applied"},
    ]
    updates = []

    monkeypatch.setattr(
        universal_agent,
        "_load_modules",
        lambda: {
            "jobs": {
                "label": "Job Applications",
                "description": "Track job applications",
                "fields": [{"name": "status", "type": "enum", "options": ["applied", "viewed"]}],
            }
        },
    )
    monkeypatch.setattr(universal_agent.database, "table_exists", lambda module: True)
    monkeypatch.setattr(universal_agent.database, "select", lambda *args, **kwargs: records)
    monkeypatch.setattr(universal_agent.database, "update", lambda module, record_id, data: updates.append((record_id, data)) or True)
    monkeypatch.setattr(universal_agent.database, "select_one", lambda module, record_id: {"id": record_id, "status": "viewed"})
    monkeypatch.setattr(universal_agent.excel_manager, "sync_module", lambda module: None)

    result = universal_agent.execute(route("update_data", None, raw_instruction="I have not applied to them"))

    assert result["success"] is True
    assert result["action"] == "update_data"
    assert result["meta"]["update"] == {"status": "viewed"}
    assert updates == [(1, {"status": "viewed"}), (2, {"status": "viewed"})]


def test_delete_handler(monkeypatch):
    monkeypatch.setattr(universal_agent.database, "delete", lambda module, record_id: True)
    monkeypatch.setattr(universal_agent.excel_manager, "sync_module", lambda module: None)

    result = universal_agent.execute(route("delete_data", id=7))

    assert result["success"] is True
    assert result["action"] == "delete_data"
    assert result["data"] == {"deleted_id": 7}


def test_delete_handler_deletes_explicit_all_without_ids(monkeypatch):
    records = [
        {"id": 1, "company": "Acme", "position": "QA", "status": "viewed"},
        {"id": 2, "company": "Beta", "position": "SQA", "status": "viewed"},
    ]
    deleted = []

    monkeypatch.setattr(
        universal_agent,
        "_load_modules",
        lambda: {
            "jobs": {
                "label": "Job Applications",
                "description": "Track job applications",
                "fields": [{"name": "status", "type": "enum", "options": ["applied", "viewed"]}],
            }
        },
    )
    monkeypatch.setattr(universal_agent.database, "table_exists", lambda module: True)
    monkeypatch.setattr(universal_agent.database, "select", lambda *args, **kwargs: records)
    monkeypatch.setattr(universal_agent.database, "count", lambda module: len(records))
    monkeypatch.setattr(universal_agent.database, "delete", lambda module, record_id: deleted.append(record_id) or True)
    monkeypatch.setattr(universal_agent.excel_manager, "sync_module", lambda module: None)

    result = universal_agent.execute(route("delete_data", None, raw_instruction="delete all previous job applications"))

    assert result["success"] is True
    assert result["action"] == "delete_data"
    assert result["data"]["deleted_ids"] == [1, 2]
    assert deleted == [1, 2]


def test_delete_handler_previews_ambiguous_bulk_delete(monkeypatch):
    records = [{"id": 1, "company": "Acme", "position": "QA", "status": "viewed"}]

    monkeypatch.setattr(
        universal_agent,
        "_load_modules",
        lambda: {
            "jobs": {
                "label": "Job Applications",
                "description": "Track job applications",
                "fields": [{"name": "status", "type": "enum", "options": ["applied", "viewed"]}],
            }
        },
    )
    monkeypatch.setattr(universal_agent.database, "table_exists", lambda module: True)
    monkeypatch.setattr(universal_agent.database, "select", lambda *args, **kwargs: records)

    result = universal_agent.execute(route("delete_data", None, raw_instruction="delete Acme job application"))

    assert result["success"] is True
    assert result["action"] == "delete_data"
    assert result["meta"]["confirmation_required"] is True
    assert result["data"] == [{"id": 1, "summary": "Acme | QA | viewed"}]


def test_search_handler_for_jobs(monkeypatch):
    class SearchAgent:
        @staticmethod
        def search_jobs(*args, **kwargs):
            return {
                "message": "found jobs",
                "jobs": [{"company": "Acme", "position": "QA", "is_remote": True}],
            }

    import backend.agents.search_agent as search_agent

    monkeypatch.setattr(search_agent, "search_jobs", SearchAgent.search_jobs)

    result = universal_agent.execute(route("search_web", query="remote QA job"))

    assert result["success"] is True
    assert result["action"] == "search_web"
    assert result["data"][0]["company"] == "Acme"


def test_scrape_handler_company(monkeypatch):
    import backend.agents.search_agent as search_agent

    monkeypatch.setattr(
        search_agent,
        "scrape_company_jobs",
        lambda company, query: {"message": "scraped", "jobs": [{"company": company}]},
    )

    result = universal_agent.execute(route("scrape", company="Acme"))

    assert result["success"] is True
    assert result["action"] == "scrape"


@pytest.mark.parametrize("action", ["analyze", "summarize"])
def test_analysis_handlers(monkeypatch, action):
    monkeypatch.setattr(universal_agent.database, "select", lambda *args, **kwargs: [{"id": 1}])
    monkeypatch.setattr(universal_agent.database, "count", lambda module: 1)
    monkeypatch.setattr(universal_agent.brain, "ask", lambda *args, **kwargs: "model summary")

    result = universal_agent.execute(route(action))

    assert result["success"] is True
    assert result["action"] == action


def test_export_handler(monkeypatch, tmp_path):
    export_path = tmp_path / "jobs.xlsx"
    monkeypatch.setattr(universal_agent.excel_manager, "export_filtered", lambda *args, **kwargs: export_path)

    result = universal_agent.execute(route("export"))

    assert result["success"] is True
    assert result["action"] == "export"
    assert result["data"]["file"] == str(export_path)


def test_schedule_handler():
    result = universal_agent.execute(route("schedule", frequency="daily"))

    assert result["success"] is True
    assert result["action"] == "schedule"


def test_create_module_handler(monkeypatch):
    created = {
        "clients": {
            "label": "Clients",
            "fields": [{"name": "date", "type": "date", "required": True}],
        }
    }
    monkeypatch.setattr(universal_agent.schema_engine, "create_module", lambda description: created)
    monkeypatch.setattr(universal_agent.database, "create_table", lambda *args, **kwargs: None)
    monkeypatch.setattr(universal_agent.excel_manager, "create_excel", lambda *args, **kwargs: None)

    result = universal_agent.execute(route("create_module", None, description="track clients"))

    assert result["success"] is True
    assert result["action"] == "create_module"
    assert result["data"] == created


def test_check_email_handler():
    result = universal_agent.execute(route("check_email", None))

    assert result["success"] is True
    assert result["action"] == "check_email"
