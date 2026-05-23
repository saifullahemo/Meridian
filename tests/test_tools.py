from backend.core import tools


def test_tool_router_skips_when_disabled(monkeypatch):
    monkeypatch.setenv("PERSONAL_OS_LLM_ROUTER", "false")

    assert tools.route_with_tools("show my jobs", {"jobs": {}}) is None


def test_tool_router_maps_model_tool_choice(monkeypatch):
    monkeypatch.setenv("PERSONAL_OS_LLM_ROUTER", "true")
    monkeypatch.setattr(tools.brain, "ask_json", lambda *args, **kwargs: {
        "tool": "search_personal_data",
        "module": "jobs",
        "parameters": {"limit": 5},
        "confidence": 91,
        "reason": "user asked for records",
    })

    route = tools.route_with_tools("show my jobs", {"jobs": {}})

    assert route["action"] == "read_data"
    assert route["module"] == "jobs"
    assert route["confidence"] == 91
    assert route["parameters"]["raw_instruction"] == "show my jobs"
