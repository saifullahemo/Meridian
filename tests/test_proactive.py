from datetime import datetime, timedelta

from backend.scheduler import proactive


def test_pattern_detection_generates_job_insight(tmp_path, monkeypatch):
    monkeypatch.setattr(proactive.database, "DB_PATH", tmp_path / "proactive.db")
    proactive.database.create_table(
        "jobs",
        {
            "fields": [
                {"name": "company", "type": "text"},
                {"name": "position", "type": "text"},
                {"name": "status", "type": "text"},
                {"name": "date_applied", "type": "date"},
            ]
        },
    )
    old = (datetime.now() - timedelta(days=20)).date().isoformat()
    for index in range(6):
        proactive.database.insert(
            "jobs",
            {"company": f"Acme {index}", "position": "QA", "status": "applied", "date_applied": old},
        )

    result = proactive.run_pattern_detection()
    notifications = proactive.list_notifications()

    assert result["generated"] >= 1
    assert any(item["kind"] in {"low_response_rate", "stale_applications"} for item in notifications)


def test_scheduled_task_crud(tmp_path, monkeypatch):
    monkeypatch.setattr(proactive.database, "DB_PATH", tmp_path / "tasks.db")

    task = proactive.create_task("Weekly QA search", "Every Monday search QA jobs", "weekly")
    updated = proactive.update_task(task["id"], {"status": "paused", "name": "Paused QA search"})

    assert updated["status"] == "paused"
    assert proactive.list_tasks()[0]["name"] == "Paused QA search"
    assert proactive.delete_task(task["id"]) is True
    assert proactive.list_tasks() == []
