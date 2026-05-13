from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
DB_PATH = ROOT / "data" / "personal_os.db"


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_tables() -> None:
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS training_consent (
                session_id TEXT PRIMARY KEY,
                consent INTEGER NOT NULL,
                note TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS training_labels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                instruction TEXT NOT NULL,
                expected_action TEXT,
                expected_module TEXT,
                expected_response TEXT,
                notes TEXT,
                metadata TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def set_consent(session_id: str, consent: bool, note: str = "") -> dict:
    init_tables()
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO training_consent (session_id, consent, note, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(session_id) DO UPDATE SET
                consent = excluded.consent,
                note = excluded.note,
                updated_at = CURRENT_TIMESTAMP
            """,
            (session_id, int(consent), note),
        )
        conn.commit()
    return {"session_id": session_id, "consent": consent, "note": note}


def has_consent(session_id: str) -> bool:
    init_tables()
    with _conn() as conn:
        row = conn.execute("SELECT consent FROM training_consent WHERE session_id = ?", (session_id,)).fetchone()
    return bool(row and row["consent"])


def add_label(
    session_id: str,
    instruction: str,
    expected_action: str = "",
    expected_module: str = "",
    expected_response: str = "",
    notes: str = "",
    metadata: dict | None = None,
) -> dict:
    init_tables()
    if not has_consent(session_id):
        raise PermissionError("Training consent is required before labeling session data.")
    with _conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO training_labels (
                session_id, instruction, expected_action, expected_module,
                expected_response, notes, metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                instruction,
                expected_action,
                expected_module,
                expected_response,
                notes,
                json.dumps(metadata or {}),
            ),
        )
        conn.commit()
    return {"id": cursor.lastrowid, "session_id": session_id}


def list_labels(limit: int = 200) -> list[dict]:
    init_tables()
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT id, session_id, instruction, expected_action, expected_module,
                   expected_response, notes, metadata, created_at
            FROM training_labels
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    results = []
    for row in rows:
        item = dict(row)
        item["metadata"] = json.loads(item["metadata"] or "{}")
        results.append(item)
    return results


def export_jsonl(path: str | Path) -> dict:
    labels = list_labels(limit=100000)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for label in reversed(labels):
            f.write(json.dumps(label, ensure_ascii=False) + "\n")
    return {"path": str(out), "records": len(labels)}
