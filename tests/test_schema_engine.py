import pytest

from backend.engine import schema_engine


def valid_schema():
    return {
        "label": "Client Projects",
        "icon": "",
        "description": "Track client project work",
        "fields": [
            {"name": "date", "type": "date", "required": True},
            {"name": "status", "type": "enum", "required": True, "options": ["open", "done"]},
            {"name": "notes", "type": "text", "required": False},
        ],
        "sources": ["manual"],
    }


def test_generate_schema_returns_validated_json(monkeypatch):
    monkeypatch.setattr(schema_engine.brain, "ask_json", lambda *args, **kwargs: valid_schema())

    schema = schema_engine._generate_schema("Track client projects")

    assert schema["label"] == "Client Projects"
    assert schema["fields"][1]["options"] == ["open", "done"]


@pytest.mark.parametrize(
    "bad_schema",
    [
        "not a dict",
        {"label": "Missing fields", "description": "No fields"},
        {"label": "Bad", "description": "Bad", "fields": []},
        {"label": "Bad", "description": "Bad", "fields": [{"name": "Bad Name", "type": "text", "required": True}]},
        {"label": "Bad", "description": "Bad", "fields": [{"name": "status", "type": "enum", "required": True}]},
        {"label": "Bad", "description": "Bad", "fields": [{"name": "count", "type": "integer", "required": True}]},
    ],
)
def test_validate_schema_rejects_invalid_json_shape(bad_schema):
    with pytest.raises(ValueError):
        schema_engine._validate_schema(bad_schema)
