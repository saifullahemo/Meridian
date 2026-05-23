from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def table(title: str, rows: list[dict[str, Any]], limit: int = 50) -> dict[str, Any] | None:
    if not rows:
        return None
    columns = _ordered_columns(rows)
    return {
        "type": "table",
        "title": title,
        "columns": columns,
        "rows": rows[:limit],
        "total": len(rows),
    }


def chart_for_records(module: str, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not records:
        return None
    if module == "jobs":
        return _count_chart("Job Status", records, "status", "pie")
    if module == "finance":
        return _sum_chart("Spending by Category", records, "category", "amount", "bar")
    if module in {"health", "learning"}:
        return _count_chart("Status Overview", records, "status" if module == "learning" else "type", "bar")
    return _count_chart("Records by Type", records, "status", "bar")


def document(title: str, content: str, filename: str = "meridian-document.md") -> dict[str, Any]:
    return {
        "type": "document",
        "title": title,
        "content": content,
        "filename": filename,
    }


def suggestions(action: str, module: str | None = None) -> list[str]:
    if action in {"read_data", "search_web"}:
        return ["Show details", "Summarize these results", "Create a chart"]
    if action in {"summarize", "analyze"}:
        return ["Show source records", "What should I do next?", "Create weekly briefing"]
    if action == "save_data":
        return ["Undo last save", "Show this module", "Add another record"]
    if action == "chat":
        return ["Use my uploaded files", "Save this insight", "Search my memory"]
    if module:
        return ["Show " + module, "Summarize " + module, "Find patterns"]
    return ["Show dashboard", "Search memory", "Create a task"]


def _ordered_columns(rows: list[dict[str, Any]]) -> list[str]:
    preferred = ["id", "company", "position", "title", "status", "date", "date_applied", "amount", "category", "type"]
    keys = list(dict.fromkeys(key for row in rows for key in row.keys()))
    return [key for key in preferred if key in keys] + [key for key in keys if key not in preferred]


def _count_chart(title: str, records: list[dict[str, Any]], field: str, chart_type: str) -> dict[str, Any] | None:
    counts = Counter(str(row.get(field) or "Unknown") for row in records)
    if not counts:
        return None
    return {
        "type": "chart",
        "title": title,
        "chart": chart_type,
        "series": [{"label": label, "value": value} for label, value in counts.items()],
    }


def _sum_chart(title: str, records: list[dict[str, Any]], label_field: str, value_field: str, chart_type: str) -> dict[str, Any] | None:
    totals: dict[str, float] = defaultdict(float)
    for row in records:
        try:
            value = float(row.get(value_field) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            totals[str(row.get(label_field) or "Unknown")] += value
    if not totals:
        return _count_chart(title, records, label_field, chart_type)
    return {
        "type": "chart",
        "title": title,
        "chart": chart_type,
        "series": [{"label": label, "value": round(value, 2)} for label, value in totals.items()],
    }
