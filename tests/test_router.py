import json
from pathlib import Path

import pytest

from backend.core import router


@pytest.mark.parametrize(
    ("instruction", "expected"),
    [
        ("Find remote QA jobs", "search_web"),
        ("Show my job applications", "read_data"),
        ("Add expense $50 lunch today", "save_data"),
        ("Delete job record 5", "delete_data"),
        ("Update job 5 status", "update_data"),
        ("I have not applied to them", "update_data"),
        ("Delete all previous job applications", "delete_data"),
        ("Summarize my jobs data", "summarize"),
        ("Analyze spending trends", "analyze"),
        ("Every Monday remind me", "schedule"),
        ("I want to track freelance clients", "create_module"),
        ("Create a project named Rayhan", "create_project"),
    ],
)
def test_detect_action_type(instruction, expected):
    assert router.detect_action_type(instruction) == expected


def test_route_project_creation_is_not_module_creation(monkeypatch):
    monkeypatch.setattr(router, "_load_modules", lambda: {"project_details": {"label": "Project Details", "fields": []}})

    result = router.route("create a project named Rayhan")

    assert result["action"] == "create_project"
    assert result["module"] is None


@pytest.mark.parametrize(
    ("instruction", "expected"),
    [
        ("Applied for a QA engineer role", "jobs"),
        ("I have not applied to them", "jobs"),
        ("Add expense $50 lunch", "finance"),
        ("Log doctor appointment", "health"),
        ("Save a Python course", "learning"),
        ("Tell me a joke", None),
    ],
)
def test_detect_module(instruction, expected):
    modules = {"jobs": {}, "finance": {}, "health": {}, "learning": {}}
    assert router.detect_module(instruction, modules) == expected


def test_detect_module_uses_dynamic_schema_terms():
    modules = {
        "pets": {
            "label": "Pet Care",
            "description": "Track vet visits and vaccines",
            "fields": [
                {"name": "pet_name", "type": "text", "required": True},
                {"name": "vaccine_date", "type": "date", "required": False},
            ],
        }
    }

    assert router.detect_module("Show my vaccine dates for pet care", modules) == "pets"


def test_golden_prompt_routes():
    path = Path(__file__).with_name("golden_prompts.json")
    cases = json.loads(path.read_text())

    for case in cases:
        result = router.route(case["prompt"])
        assert result["action"] == case["expected_action"]
        assert result["module"] == case["expected_module"]
