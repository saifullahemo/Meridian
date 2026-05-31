import json
import logging
import sqlite3
import sys
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

request_id_var: ContextVar[str] = ContextVar("request_id", default="")
session_id_var: ContextVar[str] = ContextVar("session_id", default="")
project_id_var: ContextVar[str] = ContextVar("project_id", default="")
ROOT = Path(__file__).parent.parent.parent
TRACE_DB_PATH = ROOT / "data" / "personal_os.db"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
            "session_id": session_id_var.get(),
            "project_id": project_id_var.get(),
        }
        extra = getattr(record, "event_data", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    root = logging.getLogger()
    if any(getattr(handler, "_personal_os_json", False) for handler in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler._personal_os_json = True
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def set_context(request_id: str | None = None, session_id: str | None = None, project_id: str | int | None = None) -> None:
    if request_id is not None:
        request_id_var.set(request_id)
    if session_id is not None:
        session_id_var.set(session_id)
    if project_id is not None:
        project_id_var.set(str(project_id))


def log_event(logger: logging.Logger, event: str, **data: Any) -> None:
    event_data = {"event": event, **data}
    _save_trace_event(logger.name, event, event_data)
    logger.info(event, extra={"event_data": event_data})


def get_trace_events(
    limit: int = 100,
    request_id: str | None = None,
    session_id: str | None = None,
    project_id: str | None = None,
    event: str | None = None,
) -> list[dict]:
    _init_trace_table()
    limit = max(1, min(limit, 1000))
    clauses = []
    values: list[Any] = []
    if request_id:
        clauses.append("request_id = ?")
        values.append(request_id)
    if session_id:
        clauses.append("session_id = ?")
        values.append(session_id)
    if project_id:
        clauses.append("project_id = ?")
        values.append(project_id)
    if event:
        clauses.append("event = ?")
        values.append(event)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, level, logger, event, request_id, session_id, project_id, data
            FROM trace_events
            """
            + where
            + " ORDER BY id DESC LIMIT ?",
            values + [limit],
        ).fetchall()
    events = []
    for row in rows:
        item = dict(row)
        item["data"] = json.loads(item["data"]) if item.get("data") else {}
        events.append(item)
    return events


def get_trace_summary(limit: int = 500) -> dict:
    events = get_trace_events(limit=limit)
    by_event: dict[str, int] = {}
    by_logger: dict[str, int] = {}
    error_count = 0
    latency_values = []
    for event in events:
        event_name = event.get("event", "")
        logger_name = event.get("logger", "")
        by_event[event_name] = by_event.get(event_name, 0) + 1
        by_logger[logger_name] = by_logger.get(logger_name, 0) + 1
        if event_name.endswith(".error") or "error" in event.get("data", {}):
            error_count += 1
        latency = event.get("data", {}).get("latency_ms")
        if isinstance(latency, (int, float)):
            latency_values.append(float(latency))
    return {
        "total": len(events),
        "errors": error_count,
        "by_event": dict(sorted(by_event.items(), key=lambda item: item[1], reverse=True)[:20]),
        "by_logger": dict(sorted(by_logger.items(), key=lambda item: item[1], reverse=True)[:10]),
        "avg_latency_ms": round(sum(latency_values) / len(latency_values), 2) if latency_values else None,
    }


def cleanup_older_than(days: int) -> dict:
    _init_trace_table()
    with _get_conn() as conn:
        deleted = conn.execute(
            "DELETE FROM trace_events WHERE datetime(created_at) < datetime('now', ?)",
            (f"-{days} days",),
        ).rowcount
        conn.commit()
    return {"trace_events": deleted}


def _save_trace_event(logger_name: str, event: str, data: dict) -> None:
    try:
        _init_trace_table()
        with _get_conn() as conn:
            conn.execute(
                """
                INSERT INTO trace_events (level, logger, event, request_id, session_id, project_id, data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "INFO",
                    logger_name,
                    event,
                    request_id_var.get(),
                    session_id_var.get(),
                    project_id_var.get(),
                    json.dumps(data, default=str),
                ),
            )
            conn.commit()
    except Exception:
        pass


def _get_conn() -> sqlite3.Connection:
    TRACE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(TRACE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_trace_table() -> None:
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trace_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                level TEXT NOT NULL,
                logger TEXT NOT NULL,
                event TEXT NOT NULL,
                request_id TEXT,
                session_id TEXT,
                project_id TEXT,
                data TEXT NOT NULL
            )
            """
        )
        _ensure_column(conn, "trace_events", "project_id", "TEXT")
        conn.commit()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


@contextmanager
def trace_span(name: str, logger: logging.Logger, **data: Any):
    start = time.perf_counter()
    log_event(logger, name + ".start", **data)
    try:
        yield
        log_event(logger, name + ".ok", latency_ms=round((time.perf_counter() - start) * 1000, 2), **data)
    except Exception as exc:
        log_event(
            logger,
            name + ".error",
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
            error=str(exc),
            **data,
        )
        raise
