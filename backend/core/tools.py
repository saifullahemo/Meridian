from __future__ import annotations

import os
from typing import Any

from backend.core import brain, router as keyword_router


TOOL_NAMES = {
    "search_personal_data": "read_data",
    "save_record": "save_data",
    "search_jobs": "search_web",
    "query_knowledge_base": "read_data",
    "get_summary": "summarize",
    "create_module": "create_module",
    "create_project": "create_project",
}

TOOL_DESCRIPTIONS = [
    {"name": "search_personal_data", "description": "Read/search records from user modules."},
    {"name": "save_record", "description": "Save a record into a module."},
    {"name": "search_jobs", "description": "Search external job listings."},
    {"name": "query_knowledge_base", "description": "Answer using uploaded files or RAG sources."},
    {"name": "get_summary", "description": "Summarize or analyze module data."},
    {"name": "create_module", "description": "Create a new module/schema."},
    {"name": "create_project", "description": "Create a Project workspace for chat, files, memory, and artifacts."},
]


def route_with_tools(instruction: str, modules: dict[str, Any]) -> dict[str, Any] | None:
    if os.getenv("PERSONAL_OS_LLM_ROUTER", "auto").lower() == "false":
        return None
    if os.getenv("PERSONAL_OS_LLM_ROUTER", "auto").lower() == "auto" and not brain.is_groq_available():
        return None
    module_names = list(modules.keys())
    prompt = (
        "Choose the best tool for this user instruction. Return JSON only.\n"
        "Tools: " + str(TOOL_DESCRIPTIONS) + "\n"
        "Modules: " + str(module_names) + "\n"
        "Schema: {\"tool\":\"tool_name\", \"module\":\"module_or_null\", "
        "\"parameters\":{}, \"confidence\":0-100, \"reason\":\"short\"}\n"
        "Instruction: " + instruction
    )
    try:
        result = brain.ask_json(prompt, temperature=0.0)
    except Exception:
        return None
    tool = str(result.get("tool", ""))
    action = TOOL_NAMES.get(tool)
    if not action:
        return None
    module = result.get("module")
    if module not in modules:
        module = keyword_router.detect_module(instruction, modules)
    params = result.get("parameters") if isinstance(result.get("parameters"), dict) else {}
    params["raw_instruction"] = instruction
    return {
        "action": action,
        "module": module,
        "parameters": params,
        "explanation": "Routed via LLM tool planner: " + str(result.get("reason", "")),
        "confidence": int(result.get("confidence") or 75),
        "tool": tool,
        "steps": [],
    }
