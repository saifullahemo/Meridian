from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.agents import universal_agent
from backend.core.auth import require_api_key, require_scope
from backend.core import brain, memory as mem, observability, prompt_templates, rag, router as instruction_router, safeguards, training_data, vector_store
from backend.data import database

ROOT = Path(__file__).parent.parent.parent.parent
CONFIG = ROOT / "config" / "modules.json"

router = APIRouter(prefix="/api")


class InstructionRequest(BaseModel):
    instruction: str
    session_id: Optional[str] = None


class RecordRequest(BaseModel):
    data: dict[str, Any]


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
        "modules": len(modules),
        "counts": _module_counts(modules),
    }


@router.get("/observability/events")
def observability_events(
    limit: int = Query(default=100, ge=1, le=1000),
    request_id: str = "",
    session_id: str = "",
    _authorized: bool = Depends(require_api_key),
):
    return {
        "success": True,
        "events": observability.get_trace_events(
            limit=limit,
            request_id=request_id or None,
            session_id=session_id or None,
        ),
    }


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
    from backend.api.routes.conversation import _extract_text_from_files_sync

    blocks = _extract_text_from_files_sync([file])
    text = blocks[0] if blocks else ""
    marker = f"--- FILE: {file.filename} ---"
    text = text.replace(marker, "", 1).strip()
    words = len(text.split())

    if save:
        _save_extracted_file(file.filename or "uploaded_file", text)
        rag.ingest_text(file.filename or "uploaded_file", text)

    return {
        "success": bool(text) and not text.startswith("[Could not extract") and not text.startswith("[No text"),
        "filename": file.filename,
        "text": text,
        "preview": text[:3000],
        "chars": len(text),
        "words": words,
    }


@router.get("/modules")
def modules():
    loaded = _load_modules()
    return {"success": True, "modules": loaded, "counts": _module_counts(loaded)}


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
    return {"success": True, "items": items}


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
    from backend.api.routes.conversation import _extract_text_from_files_sync

    blocks = _extract_text_from_files_sync([file])
    text = blocks[0] if blocks else ""
    marker = f"--- FILE: {file.filename} ---"
    text = text.replace(marker, "", 1).strip()
    result = rag.ingest_text(file.filename or "uploaded_file", text, source_type="file", title=file.filename)
    return {"success": True, **result}


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
