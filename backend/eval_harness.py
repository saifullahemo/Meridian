from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.core import router


def load_cases(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_eval(path: Path) -> dict:
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
    return {
        "cases": len(cases),
        "action_accuracy": correct_action / total,
        "module_accuracy": correct_module / total,
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="tests/golden_prompts.json")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    metrics = run_eval(Path(args.cases))
    text = json.dumps(metrics, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
