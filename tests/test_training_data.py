import pytest

from backend.core import training_data


def test_training_labels_require_consent(tmp_path, monkeypatch):
    monkeypatch.setattr(training_data, "DB_PATH", tmp_path / "training.db")

    with pytest.raises(PermissionError):
        training_data.add_label("session-1", "hello", expected_action="chat")

    training_data.set_consent("session-1", True, "ok")
    label = training_data.add_label("session-1", "hello", expected_action="chat")
    labels = training_data.list_labels()

    assert label["session_id"] == "session-1"
    assert labels[0]["expected_action"] == "chat"


def test_export_jsonl(tmp_path, monkeypatch):
    monkeypatch.setattr(training_data, "DB_PATH", tmp_path / "training-export.db")
    training_data.set_consent("session-1", True)
    training_data.add_label("session-1", "hello")

    result = training_data.export_jsonl(tmp_path / "labels.jsonl")

    assert result["records"] == 1
    assert "hello" in (tmp_path / "labels.jsonl").read_text()
