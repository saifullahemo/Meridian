"""
core/router.py
--------------
The instruction router for Personal OS.
Uses Groq AI first, falls back to keyword detection.
"""

import json
from pathlib import Path
from backend.core import observability

ROOT = Path(__file__).parent.parent.parent
logger = observability.get_logger(__name__)


def _load_modules() -> dict:
    config_path = ROOT / "config" / "modules.json"
    with open(config_path, "r") as f:
        return json.load(f).get("modules", {})


AVAILABLE_ACTIONS = [
    "search_web", "scrape", "save_data", "read_data",
    "update_data", "delete_data", "analyze", "summarize",
    "export", "schedule", "create_module", "check_email", "multi_step"
]


# ─────────────────────────────────────────────
#  Core routing function
# ─────────────────────────────────────────────

def route(instruction: str) -> dict:
    """
    Route a plain English instruction to the correct action.
    Tries AI first, falls back to keyword detection.
    """
    modules      = _load_modules()
    # Keyword detection runs first — fast and reliable
    module = detect_module(instruction, modules)
    action = detect_action_type(instruction)
    observability.log_event(
        logger,
        "routing.decision",
        action=action,
        module=module,
        instruction_preview=instruction[:300],
    )

    # If action is clear from keywords, return immediately
    if action != "read_data":
        return {
            "action":      action,
            "module":      module,
            "parameters":  {"raw_instruction": instruction},
            "explanation": "Routed via keyword detection",
            "steps":       []
        }

    # For read_data, also use keyword result directly
    return {
        "action":      action,
        "module":      module,
        "parameters":  {"raw_instruction": instruction},
        "explanation": "Routed via keyword detection",
        "steps":       []
    }


# ─────────────────────────────────────────────
#  Keyword detection
# ─────────────────────────────────────────────

def detect_module(instruction: str, modules: dict = None) -> str:
    """Detect which module an instruction refers to."""
    if modules is None:
        modules = _load_modules()

    t = instruction.lower()

    keyword_map = {
        "jobs":     ["job", "jobs", "apply", "applied", "application", "applications", "company", "position",
                     "interview", "resume", "cv", "career", "hiring",
                     "qa engineer", "sqa", "developer", "software engineer"],
        "finance":  ["money", "expense", "income", "spend", "cost",
                     "budget", "finance", "bill", "payment", "saving"],
        "health":   ["health", "doctor", "appointment", "medication",
                     "gym", "workout", "exercise", "symptom", "medical"],
        "learning": ["course", "book", "study", "skill",
                     "certificate", "training", "tutorial", "education"],
    }

    for module, keywords in keyword_map.items():
        if module in modules and any(kw in t for kw in keywords):
            return module

    return None


def detect_action_type(instruction: str) -> str:
    """Detect action type from keywords."""
    t = instruction.lower()

    # Scheduling
    if any(kw in t for kw in ["every", "schedule", "automatically", "weekly", "daily", "remind"]):
        return "schedule"

    # New module creation
    if any(kw in t for kw in ["want to track", "start tracking", "track my", "new module", "new category"]):
        return "create_module"

    # Delete
    if any(kw in t for kw in ["delete", "remove", "clear", "erase", "purge"]):
        return "delete_data"

    # Update
    if any(kw in t for kw in ["update", "change", "edit", "modify", "mark as", "not applied", "haven't applied", "have not applied"]):
        return "update_data"

    # Save
    if any(kw in t for kw in ["add", "save", "record", "log", "create new"]):
        return "save_data"

    # Analyze / Summarize
    if any(kw in t for kw in ["analyze", "analyse", "insight", "trend", "compare"]):
        return "analyze"
    if any(kw in t for kw in ["summarize", "summary", "overview"]):
        return "summarize"

    # Export
    if "export" in t:
        return "export"

    # ── Job search detection ──
    # Any mention of job TYPE + availability = search internet
    job_types = ["qa", "sqa", "qe", "engineer", "developer", "analyst",
                 "designer", "manager", "tester", "scientist", "architect"]
    job_signals = ["job", "jobs", "opening", "openings", "vacancy", "vacancies",
                   "hiring", "available", "position", "role", "opportunity",
                   "find me", "look for", "search for", "any company",
                   "which company", "where can i"]

    has_job_type   = any(kw in t for kw in job_types)
    has_job_signal = any(kw in t for kw in job_signals)

    # If instruction mentions a job type AND a job signal = search web
    if has_job_type and has_job_signal:
        return "search_web"

    # Explicit internet search signals
    internet_signals = [
        "find remote", "find qa", "find sqa", "remote qa", "remote jobs",
        "job openings", "job listings", "job vacancy", "hiring now",
        "available jobs", "current openings", "search jobs",
        "find jobs", "find job", "look for job", "search for job",
        "any company", "which company", "where can i find",
        "semiconductor", "tech company", "startup"
    ]
    if any(kw in t for kw in internet_signals):
        if has_job_type or has_job_signal:
            return "search_web"

    # Explicit web search
    if any(kw in t for kw in ["search", "google", "look up", "find on internet"]):
        return "search_web"

    # Read from database — only when referring to OWN data
    if any(kw in t for kw in ["my jobs", "my applications", "i applied",
                                "show me", "list my", "display my",
                                "how many", "which ones", "tell me about my"]):
        return "read_data"

    # Default — let AI answer conversationally
    return "read_data"


def _validate_route(result: dict, instruction: str) -> dict:
    """Ensure routing result has all required fields."""
    # Make sure raw_instruction is always in parameters
    params = result.get("parameters", {})
    if "raw_instruction" not in params:
        params["raw_instruction"] = instruction

    return {
        "action":      result.get("action", "read_data"),
        "module":      result.get("module", None),
        "parameters":  params,
        "explanation": result.get("explanation", ""),
        "steps":       result.get("steps", [])
    }


# ─────────────────────────────────────────────
#  Test
# ─────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        ("Find remote QA jobs",              "search_web"),
        ("Find SQA jobs in Singapore",       "search_web"),
        ("Show my job applications",         "read_data"),
        ("Add expense $50 lunch today",      "save_data"),
        ("Summarize my jobs data",           "summarize"),
        ("Every Monday search Apple jobs",   "schedule"),
        ("I want to track freelance clients","create_module"),
        ("Delete job record 5",              "delete_data"),
    ]

    print("Testing router...\n")
    print("=" * 60)

    all_pass = True
    for instruction, expected in tests:
        result   = route(instruction)
        action   = result["action"]
        passed   = "✅" if action == expected else "❌"
        all_pass = all_pass and (action == expected)
        print(passed + " " + instruction)
        print("   Expected: " + expected + " | Got: " + action)
        print()

    print("=" * 60)
    print("All passed: " + str(all_pass))
