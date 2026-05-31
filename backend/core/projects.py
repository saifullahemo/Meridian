from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import datetime
from typing import Any

from backend.core import brain, document_ingestion, memory, prompt_templates, rag, safeguards
from backend.core import observability
from backend.data import database

logger = observability.get_logger(__name__)


def init_project_tables() -> None:
    with database.get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                instructions TEXT NOT NULL DEFAULT '',
                archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS project_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                content_type TEXT,
                source TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                chars INTEGER NOT NULL DEFAULT 0,
                words INTEGER NOT NULL DEFAULT 0,
                warnings TEXT NOT NULL DEFAULT '[]',
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
            """
        )
        _ensure_column(conn, "project_files", "enabled", "INTEGER NOT NULL DEFAULT 1")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS project_artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'document',
                content TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS project_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'note',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
            """
        )
        conn.commit()


def create_project(name: str, description: str = "", instructions: str = "") -> dict[str, Any]:
    init_project_tables()
    clean_name = " ".join((name or "").split())
    if not clean_name:
        raise ValueError("Project name is required.")
    with database.get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO projects (name, description, instructions, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                clean_name[:120],
                safeguards.truncate_text(description or "", 2000, "project description"),
                safeguards.truncate_text(instructions or "", 4000, "project instructions"),
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        project_id = cursor.lastrowid
    memory.ensure_session(project_session_id(project_id), "Project created: " + clean_name)
    project = get_project(project_id)
    observability.log_event(logger, "project.create", project_id=project_id, name=project["name"])
    return project


def list_projects(include_archived: bool = False) -> list[dict[str, Any]]:
    init_project_tables()
    where = "" if include_archived else "WHERE archived = 0"
    with database.get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT p.*,
                   COUNT(DISTINCT pf.id) as file_count,
                   COUNT(DISTINCT pa.id) as artifact_count
            FROM projects p
            LEFT JOIN project_files pf ON pf.project_id = p.id
            LEFT JOIN project_artifacts pa ON pa.project_id = p.id
            {where}
            GROUP BY p.id
            ORDER BY p.updated_at DESC, p.created_at DESC
            """
        ).fetchall()
    return [_project_row(row) for row in rows]


def get_project(project_id: int) -> dict[str, Any]:
    init_project_tables()
    with database.get_connection() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        raise ValueError("Project not found.")
    project = _project_row(row)
    project["files"] = list_files(project_id)
    project["artifacts"] = list_artifacts(project_id)
    project["memory"] = list_memory(project_id)
    return project


def update_project(project_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    init_project_tables()
    allowed = {
        "name": lambda v: " ".join(str(v or "").split())[:120],
        "description": lambda v: safeguards.truncate_text(str(v or ""), 2000, "project description"),
        "instructions": lambda v: safeguards.truncate_text(str(v or ""), 4000, "project instructions"),
        "archived": lambda v: 1 if bool(v) else 0,
    }
    updates = []
    values: list[Any] = []
    for key, cleaner in allowed.items():
        if key in patch:
            cleaned = cleaner(patch[key])
            if key == "name" and not cleaned:
                raise ValueError("Project name cannot be empty.")
            updates.append(key + " = ?")
            values.append(cleaned)
    if not updates:
        return get_project(project_id)
    updates.append("updated_at = ?")
    values.append(datetime.now().isoformat())
    values.append(project_id)
    with database.get_connection() as conn:
        cursor = conn.execute("UPDATE projects SET " + ", ".join(updates) + " WHERE id = ?", values)
        conn.commit()
    if cursor.rowcount == 0:
        raise ValueError("Project not found.")
    project = get_project(project_id)
    observability.log_event(logger, "project.update", project_id=project_id, fields=list(patch.keys()))
    return project


def delete_project(project_id: int) -> None:
    init_project_tables()
    with database.get_connection() as conn:
        project_sources = conn.execute(
            "SELECT source FROM project_files WHERE project_id = ?",
            (project_id,),
        ).fetchall()
        conn.execute("DELETE FROM project_artifacts WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM project_memory WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM project_files WHERE project_id = ?", (project_id,))
        cursor = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()
    if cursor.rowcount == 0:
        raise ValueError("Project not found.")
    for row in project_sources:
        _delete_rag_source(row["source"])
    memory.clear_session(project_session_id(project_id))
    observability.log_event(logger, "project.delete", project_id=project_id, deleted_sources=len(project_sources))


def add_uploaded_files(project_id: int, files: list[Any]) -> list[dict[str, Any]]:
    init_project_tables()
    get_project(project_id)
    created = []
    for upload in files:
        doc = document_ingestion.extract_uploads([upload])[0]
        source = project_file_source(project_id, doc.filename)
        status = "indexed" if doc.success else "unreadable"
        summary = _summarize_text(doc.filename, doc.text) if doc.success else ""
        if doc.success:
            rag.ingest_text(source, doc.text, source_type="project_file", title=doc.filename)
        with database.get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO project_files (
                    project_id, filename, content_type, source, status, summary,
                    chars, words, warnings, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    doc.filename,
                    getattr(upload, "content_type", None),
                    source,
                    status,
                    summary,
                    len(doc.text or ""),
                    len((doc.text or "").split()),
                    json.dumps(doc.warnings),
                    json.dumps(doc.metadata),
                ),
            )
            conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (datetime.now().isoformat(), project_id))
            conn.commit()
            created.append(get_file(cursor.lastrowid))
        observability.log_event(
            logger,
            "project.file.ingest",
            project_id=project_id,
            filename=doc.filename,
            status=status,
            chars=len(doc.text or ""),
            warnings=len(doc.warnings),
        )
    return created


def list_files(project_id: int) -> list[dict[str, Any]]:
    init_project_tables()
    with database.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM project_files
            WHERE project_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (project_id,),
        ).fetchall()
    return [_file_row(row) for row in rows]


def get_file(file_id: int) -> dict[str, Any]:
    with database.get_connection() as conn:
        row = conn.execute("SELECT * FROM project_files WHERE id = ?", (file_id,)).fetchone()
    if not row:
        raise ValueError("Project file not found.")
    return _file_row(row)


def delete_file(project_id: int, file_id: int) -> None:
    init_project_tables()
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT source FROM project_files WHERE id = ? AND project_id = ?",
            (file_id, project_id),
        ).fetchone()
        if not row:
            raise ValueError("Project file not found.")
        conn.execute("DELETE FROM project_files WHERE id = ? AND project_id = ?", (file_id, project_id))
        conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (datetime.now().isoformat(), project_id))
        conn.commit()
    _delete_rag_source(row["source"])
    observability.log_event(logger, "project.file.delete", project_id=project_id, file_id=file_id)


def update_file(project_id: int, file_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    init_project_tables()
    updates = []
    values: list[Any] = []
    if "enabled" in patch:
        updates.append("enabled = ?")
        values.append(1 if bool(patch["enabled"]) else 0)
    if not updates:
        return get_file(file_id)
    values.extend([datetime.now().isoformat(), file_id, project_id])
    with database.get_connection() as conn:
        cursor = conn.execute(
            "UPDATE project_files SET " + ", ".join(updates) + " WHERE id = ? AND project_id = ?",
            values[:-3] + [file_id, project_id],
        )
        conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (values[-3], project_id))
        conn.commit()
    if cursor.rowcount == 0:
        raise ValueError("Project file not found.")
    updated = get_file(file_id)
    observability.log_event(logger, "project.file.update", project_id=project_id, file_id=file_id, enabled=updated.get("enabled"))
    return updated


def chat(project_id: int, instruction: str, files: list[Any] | None = None) -> dict[str, Any]:
    start = time.perf_counter()
    observability.set_context(project_id=project_id, session_id=project_session_id(project_id))
    project = get_project(project_id)
    text = safeguards.truncate_text(instruction or "", safeguards.MAX_PROMPT_CHARS, "request")
    if not text.strip():
        raise ValueError("Message is required.")
    safety = safeguards.evaluate_prompt_safety(text)
    if safety.action == "block":
        observability.log_event(logger, "project.chat.blocked", project_id=project_id, reason=safety.reason)
        return {
            "success": False,
            "message": safety.reason,
            "action": "blocked",
            "data": [],
            "meta": {"project": {"id": project_id}, "prompt_safety": safety.to_dict()},
        }
    uploaded = add_uploaded_files(project_id, files or []) if files else []
    planned = plan_project_action(project, text)
    observability.log_event(
        logger,
        "project.chat.plan",
        project_id=project_id,
        plan=planned.get("type"),
        uploaded_files=len(uploaded),
        prompt_safety=safety.severity,
    )
    action_result = execute_project_action(project_id, planned)
    if action_result:
        memory.save_exchange(project_session_id(project_id), text, action_result["message"], action_result["action"])
        touch_project(project_id)
        action_result.setdefault("meta", {})["latency_ms"] = round((time.perf_counter() - start) * 1000, 2)
        observability.log_event(
            logger,
            "project.chat.action",
            project_id=project_id,
            action=action_result["action"],
            latency_ms=action_result["meta"]["latency_ms"],
        )
        return action_result
    session_id = project_session_id(project_id)
    context = build_project_context(project, text)
    prompt = prompt_templates.project_chat_prompt(text, context)
    cfg = prompt_templates.config_for("chat")
    response = brain.ask(prompt, temperature=cfg["temperature"], max_tokens=cfg["max_tokens"])
    artifacts = _maybe_create_document_artifact(project_id, text, response)
    memory.save_exchange(session_id, text, response, "project_chat")
    touch_project(project_id)
    result = {
        "success": True,
        "message": response,
        "action": "project_chat",
        "data": [],
        "meta": {
            "project": {"id": project["id"], "name": project["name"]},
            "uploaded_files": uploaded,
            "artifacts": artifacts,
            "sources": retrieve_project_sources(project_id, text, top_k=5),
            "plan": planned,
            "prompt_safety": safety.to_dict(),
        },
    }
    result["meta"]["latency_ms"] = round((time.perf_counter() - start) * 1000, 2)
    observability.log_event(
        logger,
        "project.chat.response",
        project_id=project_id,
        sources=len(result["meta"]["sources"]),
        artifacts=len(artifacts),
        latency_ms=result["meta"]["latency_ms"],
    )
    return result


def get_history(project_id: int, limit: int = 100) -> list[dict[str, Any]]:
    return memory.get_full_history(project_session_id(project_id))[-limit:]


def touch_project(project_id: int) -> None:
    with database.get_connection() as conn:
        conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (datetime.now().isoformat(), project_id))
        conn.commit()


def retrieve_project_sources(project_id: int, query: str, top_k: int = 5) -> list[dict[str, Any]]:
    enabled = set(_enabled_sources(project_id))
    if not enabled:
        return []
    results = rag.retrieve(query, top_k=max(top_k * 3, top_k), source_prefix=project_source_prefix(project_id))
    filtered = [item for item in results if item.get("source") in enabled][:top_k]
    observability.log_event(logger, "project.rag.retrieve", project_id=project_id, top_k=top_k, hits=len(filtered))
    return filtered


def query_project(project_id: int, query: str, top_k: int = 5, answer: bool = True) -> dict[str, Any]:
    get_project(project_id)
    sources = retrieve_project_sources(project_id, query, top_k=top_k)
    if not answer:
        return {"success": True, "results": sources}
    if not sources:
        return {
            "success": False,
            "message": "No project file passages matched that query.",
            "sources": [],
        }
    prompt = prompt_templates.rag_answer_prompt(query, sources)
    cfg = prompt_templates.config_for("rag_answer")
    response = brain.ask(prompt, temperature=cfg["temperature"], max_tokens=cfg["max_tokens"])
    observability.log_event(logger, "project.rag.answer", project_id=project_id, hits=len(sources))
    return {"success": True, "message": response, "sources": sources}


def build_project_context(project: dict[str, Any], instruction: str) -> str:
    lines = [
        "Project workspace:",
        "Name: " + project["name"],
    ]
    if project.get("description"):
        lines.append("Description: " + project["description"])
    if project.get("instructions"):
        lines.append("Project instructions: " + project["instructions"])

    project_memories = list_memory(project["id"])
    if project_memories:
        lines.append("")
        lines.append("Project memory:")
        for item in project_memories[:12]:
            lines.append("- " + item["content"][:360])

    files = list_files(project["id"])
    if files:
        lines.append("")
        lines.append("Project files:")
        for item in files[:12]:
            status = item["status"]
            summary = (" - " + item["summary"][:240]) if item.get("summary") else ""
            enabled = "enabled" if item.get("enabled") else "disabled"
            lines.append("- " + item["filename"] + " (" + status + ", " + enabled + ")" + summary)

    mem_context = memory.build_context(project_session_id(project["id"]), instruction)
    if mem_context:
        lines.append("")
        lines.append(mem_context)

    passages = retrieve_project_sources(project["id"], instruction, top_k=5)
    if passages:
        lines.append("")
        lines.append("Relevant project file passages:")
        for idx, passage in enumerate(passages, 1):
            lines.append(
                "["
                + str(idx)
                + "] "
                + passage.get("citation", passage.get("title", "source"))
                + "\n"
                + safeguards.truncate_text(passage.get("text", ""), 1600, "project file passage")
            )
    return safeguards.truncate_text("\n".join(lines), safeguards.MAX_PROMPT_CHARS, "project context")


def project_session_id(project_id: int | str) -> str:
    return "project:" + str(project_id)


def project_source_prefix(project_id: int | str) -> str:
    return "project:" + str(project_id) + ":"


def project_file_source(project_id: int | str, filename: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename or "uploaded_file")
    return project_source_prefix(project_id) + "file:" + safe


def list_artifacts(project_id: int) -> list[dict[str, Any]]:
    init_project_tables()
    with database.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM project_artifacts
            WHERE project_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (project_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_memory(project_id: int) -> list[dict[str, Any]]:
    init_project_tables()
    with database.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM project_memory
            WHERE project_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (project_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def add_memory(project_id: int, content: str, kind: str = "note") -> dict[str, Any]:
    get_project(project_id)
    clean = safeguards.truncate_text(" ".join((content or "").split()), 1200, "project memory")
    if not clean:
        raise ValueError("Memory content is required.")
    with database.get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO project_memory (project_id, content, kind) VALUES (?, ?, ?)",
            (project_id, clean, kind[:40] or "note"),
        )
        conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (datetime.now().isoformat(), project_id))
        conn.commit()
        row = conn.execute("SELECT * FROM project_memory WHERE id = ?", (cursor.lastrowid,)).fetchone()
    observability.log_event(logger, "project.memory.create", project_id=project_id, kind=kind[:40] or "note")
    return dict(row)


def delete_memory(project_id: int, memory_id: int) -> None:
    init_project_tables()
    with database.get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM project_memory WHERE id = ? AND project_id = ?",
            (memory_id, project_id),
        )
        conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (datetime.now().isoformat(), project_id))
        conn.commit()
    if cursor.rowcount == 0:
        raise ValueError("Project memory not found.")
    observability.log_event(logger, "project.memory.delete", project_id=project_id, memory_id=memory_id)


def plan_project_action(project: dict[str, Any], instruction: str) -> dict[str, Any]:
    text = instruction.strip()
    lower = text.lower()
    rename_match = re.search(r"\brename (?:this )?project to ['\"]?([^'\"]+?)['\"]?$", text, re.IGNORECASE)
    if rename_match:
        return {"type": "rename_project", "name": rename_match.group(1).strip()}
    remember_match = re.search(r"\bremember(?: that)?\s+(.+)$", text, re.IGNORECASE)
    if remember_match:
        return {"type": "remember", "content": remember_match.group(1).strip()}
    if lower in {"what files are in this project?", "show files", "list files", "show project files"}:
        return {"type": "list_files"}
    if lower in {"what do you remember?", "show memory", "list memory", "show project memory"}:
        return {"type": "list_memory"}
    if lower.startswith("search files for "):
        return {"type": "search_files", "query": text[len("search files for "):].strip()}
    return {"type": "answer"}


def execute_project_action(project_id: int, plan: dict[str, Any]) -> dict[str, Any] | None:
    action_type = plan.get("type")
    if action_type == "rename_project":
        updated = update_project(project_id, {"name": plan.get("name", "")})
        return _action_response("Renamed this project to " + updated["name"] + ".", "project_rename", project_id, {"project": updated})
    if action_type == "remember":
        item = add_memory(project_id, plan.get("content", ""), kind="user_preference")
        return _action_response("Remembered for this project: " + item["content"], "project_memory_save", project_id, {"memory": item})
    if action_type == "list_files":
        files = list_files(project_id)
        if not files:
            message = "No files are attached to this project yet."
        else:
            message = "Project files:\n" + "\n".join(
                "- " + item["filename"] + " (" + item["status"] + ", " + ("enabled" if item.get("enabled") else "disabled") + ")"
                for item in files
            )
        return _action_response(message, "project_files_list", project_id, {"files": files})
    if action_type == "list_memory":
        memories = list_memory(project_id)
        if not memories:
            message = "No explicit project memories have been saved yet."
        else:
            message = "Project memory:\n" + "\n".join("- " + item["content"] for item in memories)
        return _action_response(message, "project_memory_list", project_id, {"memory": memories})
    if action_type == "search_files":
        query = plan.get("query", "")
        results = retrieve_project_sources(project_id, query, top_k=5)
        if not results:
            message = "I did not find matching passages in enabled project files."
        else:
            message = "Found matching project file passages:\n" + "\n".join(
                "- " + item.get("citation", item.get("title", "source")) + ": " + item.get("text", "")[:220]
                for item in results
            )
        return _action_response(message, "project_file_search", project_id, {"sources": results})
    return None


def _maybe_create_document_artifact(project_id: int, instruction: str, content: str) -> list[dict[str, Any]]:
    text = instruction.lower()
    triggers = ["create a document", "write a document", "draft", "report", "proposal", "summary document"]
    if not any(trigger in text for trigger in triggers):
        return []
    title = _artifact_title(instruction)
    with database.get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO project_artifacts (project_id, title, type, content)
            VALUES (?, ?, ?, ?)
            """,
            (project_id, title, "document", content),
        )
        conn.commit()
    return [dict(get_artifact(cursor.lastrowid))]


def get_artifact(artifact_id: int) -> dict[str, Any]:
    with database.get_connection() as conn:
        row = conn.execute("SELECT * FROM project_artifacts WHERE id = ?", (artifact_id,)).fetchone()
    if not row:
        raise ValueError("Artifact not found.")
    return dict(row)


def _artifact_title(instruction: str) -> str:
    clean = " ".join(instruction.split())
    return (clean[:57] + "...") if len(clean) > 60 else clean or "Generated document"


def _summarize_text(filename: str, text: str) -> str:
    if not text:
        return ""
    try:
        prompt = (
            "Summarize this uploaded project file in one concise sentence. "
            "Mention what it contains and how it may help future questions.\n\n"
            "Filename: " + filename + "\n"
            + safeguards.wrap_user_text(safeguards.truncate_text(text, 6000, "file summary"), "FILE_TEXT")
        )
        return safeguards.truncate_text(brain.ask(prompt, temperature=0.2, max_tokens=160), 500, "file summary")
    except Exception:
        return safeguards.truncate_text(" ".join(text.split())[:300], 500, "file summary")


def _delete_rag_source(source: str) -> None:
    try:
        with rag._conn() as conn:  # type: ignore[attr-defined]
            conn.execute("DELETE FROM rag_chunks WHERE source = ?", (source,))
            conn.commit()
    except Exception:
        pass


def _project_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["archived"] = bool(data.get("archived"))
    data.setdefault("file_count", 0)
    data.setdefault("artifact_count", 0)
    return data


def _file_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["enabled"] = bool(data.get("enabled", 1))
    data["warnings"] = _json_loads(data.get("warnings"), [])
    data["metadata"] = _json_loads(data.get("metadata"), {})
    return data


def _enabled_sources(project_id: int) -> list[str]:
    init_project_tables()
    with database.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT source FROM project_files
            WHERE project_id = ? AND enabled = 1 AND status = 'indexed'
            """,
            (project_id,),
        ).fetchall()
    return [row["source"] for row in rows]


def _action_response(message: str, action: str, project_id: int, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "success": True,
        "message": message,
        "action": action,
        "data": [],
        "meta": {"project": {"id": project_id}},
    }
    if meta:
        payload["meta"].update(meta)
    return payload


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _json_loads(value: Any, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return default
