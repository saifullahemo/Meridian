from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.core import router
from backend.core import projects


def load_cases(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_eval(path: Path, project_path: Path | None = None) -> dict:
    cases = load_cases(path)
    results = []
    correct_action = 0
    correct_module = 0
    for case in cases:
        routed = router.route(case["prompt"])
        action_ok = routed["action"] == case.get("expected_action")
        module_ok = routed["module"] == case.get("expected_module")
        correct_action += int(action_ok)
        correct_module += int(module_ok)
        results.append(
            {
                "prompt": case["prompt"],
                "expected_action": case.get("expected_action"),
                "actual_action": routed["action"],
                "action_ok": action_ok,
                "expected_module": case.get("expected_module"),
                "actual_module": routed["module"],
                "module_ok": module_ok,
            }
        )
    total = len(cases) or 1
    metrics = {
        "cases": len(cases),
        "action_accuracy": correct_action / total,
        "module_accuracy": correct_module / total,
        "results": results,
    }
    if project_path:
        project_metrics = run_project_eval(project_path)
        metrics["project_cases"] = project_metrics["cases"]
        metrics["project_action_accuracy"] = project_metrics["action_accuracy"]
        metrics["project_results"] = project_metrics["results"]
    return metrics


def run_project_eval(path: Path) -> dict:
    cases = load_cases(path)
    project = {"id": 1, "name": "Eval Project", "description": "", "instructions": ""}
    results = []
    correct = 0
    for case in cases:
        planned = projects.plan_project_action(project, case["prompt"])
        ok = planned.get("type") == case.get("expected_type")
        correct += int(ok)
        results.append(
            {
                "prompt": case["prompt"],
                "expected_type": case.get("expected_type"),
                "actual_type": planned.get("type"),
                "ok": ok,
            }
        )
    total = len(cases) or 1
    return {
        "cases": len(cases),
        "action_accuracy": correct / total,
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="tests/golden_prompts.json")
    parser.add_argument("--project-cases", default="tests/golden_project_prompts.json")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    project_path = Path(args.project_cases) if args.project_cases else None
    metrics = run_eval(Path(args.cases), project_path if project_path and project_path.exists() else None)
    text = json.dumps(metrics, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
