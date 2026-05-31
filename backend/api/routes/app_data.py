from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.agents import universal_agent
from backend.core.auth import require_api_key, require_scope
from backend.core import brain, document_ingestion, memory as mem, observability, prompt_templates, rag, router as instruction_router, safeguards, semantic, training_data, vector_store
from backend.data import database
from backend.engine import schema_engine
from backend.scheduler import proactive

ROOT = Path(__file__).parent.parent.parent.parent
CONFIG = ROOT / "config" / "modules.json"

router = APIRouter(prefix="/api")


class InstructionRequest(BaseModel):
    instruction: str
    session_id: Optional[str] = None


class RecordRequest(BaseModel):
    data: dict[str, Any]


class ModuleRequest(BaseModel):
    key: str
    module_schema: dict[str, Any] = Field(alias="schema")


class MemorySearchRequest(BaseModel):
    query: str


class RagIngestRequest(BaseModel):
    source: str
    text: str = ""


class RagQueryRequest(BaseModel):
    query: str
    top_k: int = 5
    answer: bool = False


class JobSearchRequest(BaseModel):
    query: str
    location: str = ""
    session_id: Optional[str] = None


class RetentionRequest(BaseModel):
    days: int | None = None


class ConsentRequest(BaseModel):
    session_id: str
    consent: bool
    note: str = ""


class LabelRequest(BaseModel):
    session_id: str
    instruction: str
    expected_action: str = ""
    expected_module: str = ""
    expected_response: str = ""
    notes: str = ""
    metadata: dict[str, Any] = {}


class RenameSessionRequest(BaseModel):
    title: str


class ScheduledTaskRequest(BaseModel):
    name: str
    instruction: str
    frequency: str = "weekly"
    next_run_at: str | None = None
    status: str = "active"


def _load_modules() -> dict[str, Any]:
    with open(CONFIG, "r") as f:
        return json.load(f).get("modules", {})


def _require_module(module_key: str) -> dict[str, Any]:
    modules = _load_modules()
    if module_key not in modules:
        raise HTTPException(status_code=404, detail="Unknown module: " + module_key)
    return modules[module_key]


def _module_counts(modules: dict[str, Any]) -> dict[str, int]:
    database.init_all_tables()
    return {key: database.count(key) for key in modules}


def _sse(event: str, data: dict) -> str:
    return "event: " + event + "\ndata: " + json.dumps(data, default=str) + "\n\n"


@router.get("/status")
def status():
    modules = _load_modules()
    try:
        ai_status = brain.get_status()
    except Exception as e:
        ai_status = {"ready": False, "error": str(e)}
    return {
        "success": True,
        "ai": ai_status,
        "vector_store": vector_store.status(),
        "embeddings": semantic.status(),
        "document_ingestion": document_ingestion.capabilities(),
        "modules": len(modules),
        "counts": _module_counts(modules),
    }


@router.get("/observability/events")
def observability_events(
    limit: int = Query(default=100, ge=1, le=1000),
    request_id: str = "",
    session_id: str = "",
    project_id: str = "",
    event: str = "",
    _authorized: bool = Depends(require_api_key),
):
    return {
        "success": True,
        "events": observability.get_trace_events(
            limit=limit,
            request_id=request_id or None,
            session_id=session_id or None,
            project_id=project_id or None,
            event=event or None,
        ),
    }


@router.get("/observability/summary")
def observability_summary(
    limit: int = Query(default=500, ge=1, le=2000),
    _authorized: bool = Depends(require_api_key),
):
    return {"success": True, "summary": observability.get_trace_summary(limit=limit)}


@router.post("/maintenance/retention")
def maintenance_retention(req: RetentionRequest, _authorized: bool = Depends(require_api_key)):
    days = req.days if req.days is not None else int(os.getenv("PERSONAL_OS_RETENTION_DAYS", "90"))
    days = max(1, days)
    return {
        "success": True,
        "days": days,
        "deleted": {
            **mem.cleanup_older_than(days),
            **rag.cleanup_older_than(days),
            **observability.cleanup_older_than(days),
        },
    }


@router.post("/training/consent")
def training_consent(req: ConsentRequest, _authorized: bool = Depends(require_scope("training:write"))):
    return {"success": True, **training_data.set_consent(req.session_id, req.consent, req.note)}


@router.post("/training/labels")
def training_label(req: LabelRequest, _authorized: bool = Depends(require_scope("training:write"))):
    try:
        label = training_data.add_label(
            session_id=req.session_id,
            instruction=req.instruction,
            expected_action=req.expected_action,
            expected_module=req.expected_module,
            expected_response=req.expected_response,
            notes=req.notes,
            metadata=req.metadata,
        )
        return {"success": True, **label}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


@router.get("/training/labels")
def training_labels(
    limit: int = Query(default=200, ge=1, le=1000),
    _authorized: bool = Depends(require_scope("training:read")),
):
    return {"success": True, "labels": training_data.list_labels(limit=limit)}


@router.post("/training/export")
def training_export(_authorized: bool = Depends(require_scope("training:read"))):
    return {"success": True, **training_data.export_jsonl("data/training/labels.jsonl")}


@router.post("/chat")
def chat(req: InstructionRequest):
    session_id = req.session_id or mem.today_session_id()
    observability.set_context(session_id=session_id)
    database.init_all_tables()
    instruction = safeguards.truncate_text(req.instruction, safeguards.MAX_PROMPT_CHARS, "instruction")
    safety = safeguards.evaluate_prompt_safety(instruction)
    if safety.action == "block":
        return {
            "success": False,
            "message": safety.reason,
            "data": [],
            "action": "blocked",
            "meta": {"prompt_safety": safety.to_dict()},
        }
    route = instruction_router.route(instruction)
    result = universal_agent.execute(route, context={"session_id": session_id})
    result.setdefault("meta", {})["route"] = route
    result.setdefault("meta", {})["prompt_safety"] = safety.to_dict()
    try:
        mem.save_exchange(
            session_id,
            req.instruction,
            result.get("message", ""),
            result.get("action", ""),
        )
    except Exception:
        pass
    return result


@router.post("/chat/stream")
def chat_stream(req: InstructionRequest):
    session_id = req.session_id or mem.today_session_id()
    observability.set_context(session_id=session_id)
    instruction = safeguards.truncate_text(req.instruction, safeguards.MAX_PROMPT_CHARS, "instruction")
    safety = safeguards.evaluate_prompt_safety(instruction)
    route = instruction_router.route(instruction)

    def events():
        yield _sse("meta", {"route": route, "prompt_safety": safety.to_dict()})
        if safety.action == "block":
            yield _sse("error", {"message": safety.reason, "action": "blocked"})
            yield _sse("done", {})
            return

        if route.get("action") == "read_data" and route.get("module") is None:
            try:
                context = mem.build_context(session_id, instruction)
                file_context = _session_file_context(session_id, instruction)
                if file_context:
                    context = "\n\n".join(part for part in [context, file_context] if part)
                prompt = prompt_templates.chat_prompt(instruction, context)
                cfg = prompt_templates.config_for("chat")
                collected = []
                for token in brain.ask_stream(prompt, temperature=cfg["temperature"]):
                    collected.append(token)
                    yield _sse("token", {"text": token})
                message = "".join(collected)
                try:
                    mem.save_exchange(session_id, req.instruction, message, "chat")
                except Exception:
                    pass
                yield _sse("done", {"action": "chat"})
            except Exception as e:
                yield _sse("error", {"message": str(e)})
                yield _sse("done", {})
            return

        result = universal_agent.execute(route, context={"session_id": session_id})
        result.setdefault("meta", {})["route"] = route
        result.setdefault("meta", {})["prompt_safety"] = safety.to_dict()
        try:
            mem.save_exchange(session_id, req.instruction, result.get("message", ""), result.get("action", ""))
        except Exception:
            pass
        yield _sse("final", result)
        yield _sse("done", {"action": result.get("action")})

    return StreamingResponse(events(), media_type="text/event-stream")


def _session_file_context(session_id: str, query: str, top_k: int = 4) -> str:
    passages = rag.retrieve(query, top_k=top_k, source_prefix=rag.session_source_prefix(session_id))
    if not passages:
        return ""
    lines = ["Relevant uploaded files for this session:"]
    for index, passage in enumerate(passages, start=1):
        lines.append(
            "["
            + str(index)
            + "] "
            + passage.get("title", passage.get("source", "uploaded_file"))
            + "#"
            + str(passage.get("chunk_id", ""))
            + "\n"
            + safeguards.truncate_text(passage.get("text", ""), 2000, "uploaded file context")
        )
    return "\n\n".join(lines)


@router.post("/jobs/search")
def jobs_search(req: JobSearchRequest):
    text = req.query.strip()
    if req.location.strip():
        text += " in " + req.location.strip()
    if "job" not in text.lower():
        text = "Find " + text + " jobs"
    route = {
        "action": "search_web",
        "module": "jobs",
        "parameters": {"raw_instruction": text, "query": text, "location": req.location},
        "explanation": "Job search workspace",
        "steps": [],
    }
    result = universal_agent.execute(route, context={"session_id": req.session_id or mem.today_session_id()})
    result.setdefault("meta", {})["route"] = route
    return result


@router.post("/files/extract")
async def extract_file(
    file: UploadFile = File(...),
    save: bool = Form(False),
    _authorized: bool = Depends(require_api_key),
):
    extracted = document_ingestion.extract_uploads([file])[0]
    text = extracted.text
    words = len(text.split())

    if save:
        _save_extracted_file(file.filename or "uploaded_file", text)
        if extracted.success:
            rag.ingest_text(file.filename or "uploaded_file", text, source_type="file", title=file.filename)

    return {
        "success": extracted.success,
        "filename": file.filename,
        "text": text,
        "preview": text[:3000],
        "chars": len(text),
        "words": words,
        "warnings": extracted.warnings,
        "metadata": extracted.metadata,
        "parts": [part.__dict__ for part in extracted.parts[:50]],
    }


@router.get("/modules")
def modules():
    loaded = _load_modules()
    return {"success": True, "modules": loaded, "counts": _module_counts(loaded)}


@router.post("/modules")
def create_module(req: ModuleRequest, _authorized: bool = Depends(require_api_key)):
    key = _clean_module_key(req.key)
    try:
        created = schema_engine.create_module_from_schema(key, req.module_schema)
        database.create_table(key, created[key])
        return {"success": True, "module_key": key, "module": created[key]}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/modules/{module_key}")
def module_detail(module_key: str, _authorized: bool = Depends(require_api_key)):
    return {"success": True, "module_key": module_key, "module": _require_module(module_key)}


@router.put("/modules/{module_key}")
def update_module(module_key: str, req: ModuleRequest, _authorized: bool = Depends(require_api_key)):
    _require_module(module_key)
    try:
        updated = schema_engine.update_module(module_key, req.module_schema)
        _sync_table_columns(module_key, updated)
        return {"success": True, "module_key": module_key, "module": updated}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/modules/{module_key}")
def delete_module(module_key: str, drop_data: bool = Query(default=False), _authorized: bool = Depends(require_api_key)):
    _require_module(module_key)
    try:
        schema_engine.delete_module(module_key)
        if drop_data:
            database.drop_table(module_key)
        return {"success": True, "message": "Module deleted.", "module_key": module_key, "dropped_data": drop_data}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/modules/{module_key}/records")
def module_records(
    module_key: str,
    search: str = "",
    status: str = "",
    limit: int = Query(default=500, ge=1, le=1000),
    _authorized: bool = Depends(require_api_key),
):
    schema = _require_module(module_key)
    database.init_all_tables()
    records = database.select(module_key, limit=limit)

    if search:
        needle = search.lower()
        records = [
            record
            for record in records
            if any(needle in str(value).lower() for value in record.values())
        ]

    if status and status != "All":
        records = [record for record in records if record.get("status") == status]

    return {
        "success": True,
        "module": schema,
        "records": records,
        "total": database.count(module_key),
        "showing": len(records),
    }


def _clean_module_key(key: str) -> str:
    clean = (key or "").strip().lower().replace(" ", "_")
    clean = "".join(ch for ch in clean if ch.isalnum() or ch == "_")
    if not clean:
        raise HTTPException(status_code=400, detail="Module key is required.")
    return clean


def _sync_table_columns(module_key: str, schema: dict[str, Any]):
    if not database.table_exists(module_key):
        database.create_table(module_key, schema)
        return
    type_map = {"text": "TEXT", "number": "REAL", "date": "TEXT", "enum": "TEXT", "boolean": "INTEGER"}
    existing = set(database.get_table_columns(module_key))
    for field in schema.get("fields", []):
        name = field.get("name")
        if name and name not in existing:
            database.add_column(module_key, name, type_map.get(field.get("type"), "TEXT"))


@router.post("/modules/{module_key}/records")
def create_record(module_key: str, req: RecordRequest, _authorized: bool = Depends(require_api_key)):
    _require_module(module_key)
    database.init_all_tables()
    record_id = database.insert(module_key, req.data)
    record = database.select_one(module_key, record_id)
    try:
        from backend.data import excel_manager

        excel_manager.append_row(module_key, record)
    except Exception:
        pass
    return {"success": True, "message": "Record saved.", "record": record}


@router.put("/modules/{module_key}/records/{record_id}")
def update_record(
    module_key: str,
    record_id: int,
    req: RecordRequest,
    _authorized: bool = Depends(require_api_key),
):
    _require_module(module_key)
    database.init_all_tables()
    updated = database.update(module_key, record_id, req.data)
    if not updated:
        raise HTTPException(status_code=404, detail="Record not found")
    try:
        from backend.data import excel_manager

        excel_manager.sync_module(module_key)
    except Exception:
        pass
    return {"success": True, "message": "Record updated.", "record": database.select_one(module_key, record_id)}


@router.delete("/modules/{module_key}/records/{record_id}")
def delete_record(module_key: str, record_id: int, _authorized: bool = Depends(require_api_key)):
    _require_module(module_key)
    database.init_all_tables()
    deleted = database.delete(module_key, record_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Record not found")
    try:
        from backend.data import excel_manager

        excel_manager.sync_module(module_key)
    except Exception:
        pass
    return {"success": True, "message": "Record deleted.", "deleted_id": record_id}


@router.get("/dashboard")
def dashboard():
    modules = _load_modules()
    database.init_all_tables()
    items = []
    for key, schema in modules.items():
        records = database.select(key, limit=5, order_by="created_at DESC")
        items.append(
            {
                "key": key,
                "module": schema,
                "count": database.count(key),
                "recent": records,
            }
        )
    return {"success": True, "items": items, "notifications": proactive.list_notifications(limit=8)}


@router.get("/proactive/notifications")
def proactive_notifications(_authorized: bool = Depends(require_api_key)):
    return {"success": True, "notifications": proactive.list_notifications()}


@router.post("/proactive/notifications/{notification_id}/dismiss")
def proactive_dismiss(notification_id: int, _authorized: bool = Depends(require_api_key)):
    if not proactive.dismiss_notification(notification_id):
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"success": True}


@router.post("/proactive/run")
def proactive_run(_authorized: bool = Depends(require_api_key)):
    return {"success": True, **proactive.run_pattern_detection()}


@router.get("/proactive/briefing")
def proactive_briefing(_authorized: bool = Depends(require_api_key)):
    return proactive.morning_briefing()


@router.get("/scheduled-tasks")
def scheduled_tasks(_authorized: bool = Depends(require_api_key)):
    return {"success": True, "tasks": proactive.list_tasks()}


@router.post("/scheduled-tasks")
def scheduled_task_create(req: ScheduledTaskRequest, _authorized: bool = Depends(require_api_key)):
    task = proactive.create_task(req.name, req.instruction, req.frequency, req.next_run_at)
    return {"success": True, "task": task}


@router.put("/scheduled-tasks/{task_id}")
def scheduled_task_update(task_id: int, req: ScheduledTaskRequest, _authorized: bool = Depends(require_api_key)):
    task = proactive.update_task(task_id, req.dict())
    if not task:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    return {"success": True, "task": task}


@router.delete("/scheduled-tasks/{task_id}")
def scheduled_task_delete(task_id: int, _authorized: bool = Depends(require_api_key)):
    if not proactive.delete_task(task_id):
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    return {"success": True}


@router.get("/memory/{session_id}")
def memory_history(
    session_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    _authorized: bool = Depends(require_api_key),
):
    history = mem.get_full_history(session_id)[-limit:]
    return {
        "success": True,
        "session_id": session_id,
        "history": history,
        "summary": mem.get_session_summary(session_id),
    }


@router.get("/memory/sessions/list")
def memory_sessions(_authorized: bool = Depends(require_api_key)):
    return {"success": True, "sessions": mem.get_all_sessions()}


@router.put("/memory/sessions/{session_id}")
def rename_memory_session(
    session_id: str,
    req: RenameSessionRequest,
    _authorized: bool = Depends(require_api_key),
):
    try:
        return {"success": True, **mem.rename_session(session_id, req.title)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/memory/search")
def memory_search(req: MemorySearchRequest, _authorized: bool = Depends(require_api_key)):
    lexical = mem.search_all_sessions(req.query)
    semantic_results = []
    for session in mem.get_all_sessions()[:20]:
        semantic_results.extend(mem.search_semantic_memory(session["session_id"], req.query, limit=3))
    semantic_results = sorted(semantic_results, key=lambda item: item["score"], reverse=True)[:10]
    return {"success": True, "results": lexical, "semantic_results": semantic_results}


@router.post("/rag/ingest")
def rag_ingest(req: RagIngestRequest, _authorized: bool = Depends(require_api_key)):
    text = safeguards.truncate_text(req.text, 200000, "rag source")
    return {"success": True, **rag.ingest_text(req.source, text)}


@router.post("/rag/ingest-file")
async def rag_ingest_file(
    file: UploadFile = File(...),
    _authorized: bool = Depends(require_api_key),
):
    extracted = document_ingestion.extract_uploads([file])[0]
    text = extracted.text
    if not extracted.success:
        return {
            "success": False,
            "source": file.filename or "uploaded_file",
            "source_type": "file",
            "title": file.filename,
            "chunks": 0,
            "warnings": extracted.warnings,
            "message": "No readable text could be extracted from this file.",
        }
    result = rag.ingest_text(file.filename or "uploaded_file", text, source_type="file", title=file.filename)
    return {"success": True, "warnings": extracted.warnings, "metadata": extracted.metadata, **result}


@router.post("/rag/ingest-url")
def rag_ingest_url(req: RagIngestRequest, _authorized: bool = Depends(require_api_key)):
    return {"success": True, **rag.ingest_url(req.source)}


@router.post("/rag/query")
def rag_query(req: RagQueryRequest, _authorized: bool = Depends(require_api_key)):
    top_k = max(1, min(req.top_k, 10))
    if req.answer:
        return rag.answer(req.query, top_k=top_k)
    return {"success": True, "results": rag.retrieve(req.query, top_k=top_k)}


@router.get("/rag/sources")
def rag_sources(_authorized: bool = Depends(require_api_key)):
    return {"success": True, "sources": rag.list_sources()}


@router.post("/memory/{session_id}/summarize")
def memory_summarize(session_id: str, _authorized: bool = Depends(require_api_key)):
    return {"success": True, "summary": mem.summarize_session(session_id)}


@router.delete("/memory/{session_id}")
def memory_clear(session_id: str, _authorized: bool = Depends(require_api_key)):
    mem.clear_session(session_id)
    return {"success": True, "message": "Memory cleared."}


def _save_extracted_file(filename: str, text: str):
    with database.get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS extracted_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "INSERT INTO extracted_files (filename, content) VALUES (?, ?)",
            (filename, text),
        )
        conn.commit()
