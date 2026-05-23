from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from backend.core import observability
from backend.data import database

logger = observability.get_logger(__name__)


def _conn() -> sqlite3.Connection:
    conn = database.get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS proactive_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'info',
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            module TEXT,
            supporting_data TEXT NOT NULL DEFAULT '{}',
            suggested_action TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            dismissed_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            instruction TEXT NOT NULL,
            frequency TEXT NOT NULL DEFAULT 'weekly',
            next_run_at TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            last_run_at TEXT,
            last_result TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    return conn


def list_notifications(limit: int = 50, status: str = "active") -> list[dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM proactive_notifications
            WHERE status = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (status, limit),
        ).fetchall()
    return [_decode_notification(dict(row)) for row in rows]


def dismiss_notification(notification_id: int) -> bool:
    with _conn() as conn:
        changed = conn.execute(
            """
            UPDATE proactive_notifications
            SET status = 'dismissed', dismissed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (notification_id,),
        ).rowcount
        conn.commit()
    return changed > 0


def run_pattern_detection() -> dict[str, Any]:
    database.init_all_tables()
    generated = []
    for insight in _job_insights() + _finance_insights() + _learning_insights() + _deadline_insights():
        if _insert_notification_once(insight):
            generated.append(insight)
    observability.log_event(logger, "proactive.pattern_detection", generated=len(generated))
    return {"generated": len(generated), "notifications": generated}


def morning_briefing() -> dict[str, Any]:
    database.init_all_tables()
    run_pattern_detection()
    jobs = database.select("jobs", limit=500) if database.table_exists("jobs") else []
    finance = database.select("finance", limit=500) if database.table_exists("finance") else []
    learning = database.select("learning", limit=500) if database.table_exists("learning") else []
    active = list_notifications(limit=8)
    lines = ["Good morning. Here is your Meridian briefing."]
    if jobs:
        pending = [row for row in jobs if str(row.get("status", "")).lower() in {"applied", "viewed", "responded"}]
        lines.append(f"Jobs: {len(jobs)} tracked, {len(pending)} still active.")
    if finance:
        expenses = _sum_amount(row for row in finance if str(row.get("type", "")).lower() == "expense")
        lines.append(f"Finance: expenses logged total {expenses:.2f}.")
    if learning:
        active_learning = [row for row in learning if str(row.get("status", "")).lower() in {"planned", "in_progress"}]
        lines.append(f"Learning: {len(active_learning)} active learning items.")
    if active:
        lines.append("Top alerts:")
        for item in active[:5]:
            lines.append("- " + item["title"] + ": " + item["message"])
    if len(lines) == 1:
        lines.append("No tracked data yet. Add records or upload documents to make briefings useful.")
    return {"success": True, "message": "\n".join(lines), "notifications": active}


def list_tasks() -> list[dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM scheduled_tasks ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]


def create_task(name: str, instruction: str, frequency: str = "weekly", next_run_at: str | None = None) -> dict[str, Any]:
    with _conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO scheduled_tasks (name, instruction, frequency, next_run_at)
            VALUES (?, ?, ?, ?)
            """,
            (name, instruction, frequency, next_run_at),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM scheduled_tasks WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row)


def update_task(task_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {key: value for key, value in data.items() if key in {"name", "instruction", "frequency", "next_run_at", "status"}}
    if not allowed:
        return None
    allowed["updated_at"] = datetime.now().isoformat()
    clause = ", ".join(key + " = ?" for key in allowed)
    with _conn() as conn:
        changed = conn.execute(
            "UPDATE scheduled_tasks SET " + clause + " WHERE id = ?",
            list(allowed.values()) + [task_id],
        ).rowcount
        conn.commit()
        if not changed:
            return None
        row = conn.execute("SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,)).fetchone()
    return dict(row)


def delete_task(task_id: int) -> bool:
    with _conn() as conn:
        changed = conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,)).rowcount
        conn.commit()
    return changed > 0


def _job_insights() -> list[dict[str, Any]]:
    if not database.table_exists("jobs"):
        return []
    jobs = database.select("jobs", limit=1000)
    if not jobs:
        return []
    insights = []
    active = [row for row in jobs if str(row.get("status", "")).lower() in {"applied", "viewed"}]
    responded = [row for row in jobs if str(row.get("status", "")).lower() in {"responded", "interview", "offer"}]
    if len(jobs) >= 5 and len(responded) / max(1, len(jobs)) < 0.2:
        insights.append(_notification("low_response_rate", "warning", "Low job response rate", "Your saved job applications have a response rate below 20%. Try tailoring resumes or prioritizing warmer leads.", "jobs", {"total": len(jobs), "responded": len(responded)}, "Review job strategy"))
    stale_cutoff = datetime.now() - timedelta(days=14)
    stale = [row for row in active if _parse_date(row.get("date_applied") or row.get("created_at")) and _parse_date(row.get("date_applied") or row.get("created_at")) < stale_cutoff]
    if stale:
        insights.append(_notification("stale_applications", "info", "Stale job applications", f"{len(stale)} active applications have had no movement for over 14 days.", "jobs", {"count": len(stale)}, "Plan follow-ups"))
    return insights


def _finance_insights() -> list[dict[str, Any]]:
    if not database.table_exists("finance"):
        return []
    records = database.select("finance", limit=1000)
    expenses = [row for row in records if str(row.get("type", "")).lower() == "expense"]
    if len(expenses) < 3:
        return []
    total = _sum_amount(expenses)
    avg = total / len(expenses)
    spikes = [row for row in expenses if _amount(row) > avg * 2 and _amount(row) > 0]
    if spikes:
        return [_notification("budget_spike", "warning", "Budget spike detected", f"{len(spikes)} expenses are more than 2x your average expense.", "finance", {"average": round(avg, 2), "spikes": len(spikes)}, "Review expenses")]
    return []


def _learning_insights() -> list[dict[str, Any]]:
    if not database.table_exists("jobs") or not database.table_exists("learning"):
        return []
    jobs = database.select("jobs", limit=500)
    learning = database.select("learning", limit=500)
    learned_text = " ".join(str(row.get("title", "")) + " " + str(row.get("notes", "")) for row in learning).lower()
    skills = ["kubernetes", "docker", "aws", "sql", "python", "react", "typescript", "playwright", "selenium"]
    missing = []
    job_text = " ".join(str(row.get("position", "")) + " " + str(row.get("notes", "")) for row in jobs).lower()
    for skill in skills:
        count = job_text.count(skill)
        if count >= 2 and skill not in learned_text:
            missing.append({"skill": skill, "mentions": count})
    if missing:
        top = sorted(missing, key=lambda item: item["mentions"], reverse=True)[0]
        return [_notification("learning_gap", "info", "Learning gap found", f"{top['skill'].title()} appears in saved jobs but is not in your learning tracker.", "learning", top, "Add learning item")]
    return []


def _deadline_insights() -> list[dict[str, Any]]:
    insights = []
    now = datetime.now()
    for module in ["jobs", "health", "learning"]:
        if not database.table_exists(module):
            continue
        for row in database.select(module, limit=500):
            for field in ["deadline", "next_date", "end_date"]:
                due = _parse_date(row.get(field))
                if due and now <= due <= now + timedelta(days=7):
                    insights.append(_notification("deadline_alert", "warning", "Deadline coming up", f"{module} record {row.get('id')} has {field} due on {due.date()}.", module, {"record_id": row.get("id"), "field": field, "due": due.date().isoformat()}, "Review deadline"))
    return insights


def _insert_notification_once(item: dict[str, Any]) -> bool:
    with _conn() as conn:
        existing = conn.execute(
            """
            SELECT id FROM proactive_notifications
            WHERE kind = ? AND title = ? AND module IS ? AND status = 'active'
            """,
            (item["kind"], item["title"], item.get("module")),
        ).fetchone()
        if existing:
            return False
        conn.execute(
            """
            INSERT INTO proactive_notifications
            (kind, severity, title, message, module, supporting_data, suggested_action)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["kind"],
                item["severity"],
                item["title"],
                item["message"],
                item.get("module"),
                json.dumps(item.get("supporting_data") or {}),
                item.get("suggested_action"),
            ),
        )
        conn.commit()
    return True


def _notification(kind: str, severity: str, title: str, message: str, module: str | None, supporting_data: dict[str, Any], suggested_action: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "severity": severity,
        "title": title,
        "message": message,
        "module": module,
        "supporting_data": supporting_data,
        "suggested_action": suggested_action,
    }


def _decode_notification(row: dict[str, Any]) -> dict[str, Any]:
    try:
        row["supporting_data"] = json.loads(row.get("supporting_data") or "{}")
    except Exception:
        row["supporting_data"] = {}
    return row


def _amount(row: dict[str, Any]) -> float:
    try:
        return float(row.get("amount") or 0)
    except (TypeError, ValueError):
        return 0.0


def _sum_amount(rows) -> float:
    return sum(_amount(row) for row in rows)


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    raw = str(value)[:19]
    candidates = [raw[:10], raw[:19]]
    for candidate in candidates:
        for fmt in ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]:
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                continue
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
