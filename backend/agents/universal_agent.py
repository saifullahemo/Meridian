"""
agents/universal_agent.py
The universal agent for Personal OS.
Receives a routing decision and executes it.
"""

import json
import re
import time
from pathlib import Path
from datetime import datetime

from backend.core import brain
from backend.core import artifacts, observability, prompt_templates, rag, safeguards
from backend.data import database, excel_manager
from backend.engine import schema_engine

ROOT   = Path(__file__).parent.parent.parent
CONFIG = ROOT / "config" / "modules.json"
logger = observability.get_logger(__name__)


def _load_modules() -> dict:
    with open(CONFIG, "r") as f:
        return json.load(f).get("modules", {})


def _module_fields(module: str) -> list[dict]:
    return _load_modules().get(module, {}).get("fields", [])


def _resolve_module(module: str | None, raw: str) -> str | None:
    """Infer a module from configured module names, labels, fields, and common words."""
    if module:
        return module

    text = (raw or "").lower()
    if not text:
        return None

    modules = _load_modules()
    best_module = None
    best_score = 0
    common_aliases = {
        "jobs": ["job", "jobs", "application", "applications", "applied", "apply", "company", "position", "role"],
        "finance": ["expense", "income", "money", "payment", "budget", "spent", "cost"],
        "health": ["doctor", "medicine", "medication", "workout", "appointment", "symptom"],
        "learning": ["course", "book", "study", "certification", "skill", "tutorial"],
    }

    for key, schema in modules.items():
        terms = [key, schema.get("label", ""), schema.get("description", "")]
        terms.extend(field.get("name", "") for field in schema.get("fields", []))
        terms.extend(common_aliases.get(key, []))
        score = 0
        phrases = {
            str(term).replace("_", " ").lower().strip()
            for term in terms
            if str(term).strip()
        }
        for phrase in phrases:
            if len(phrase) > 2 and re.search(r"\b" + re.escape(phrase) + r"s?\b", text):
                score += 4
        parts = set()
        for term in terms:
            for part in str(term).replace("_", " ").lower().split():
                if len(part) > 2:
                    parts.add(part)
        for part in parts:
            if re.search(r"\b" + re.escape(part) + r"s?\b", text):
                score += 1
        if score > best_score:
            best_module = key
            best_score = score

    return best_module if best_score else None


def _record_label(record: dict) -> str:
    pieces = []
    for key in ["company", "position", "title", "client_name", "category", "description", "status", "country"]:
        value = record.get(key)
        if value not in (None, ""):
            pieces.append(str(value))
    return " | ".join(pieces) or "record " + str(record.get("id", ""))


def _preview_records(records: list[dict], limit: int = 8) -> list[dict]:
    return [{"id": rec.get("id"), "summary": _record_label(rec)} for rec in records[:limit]]


def _module_hint() -> str:
    modules = _load_modules()
    labels = [
        (schema.get("label") or key).strip()
        for key, schema in modules.items()
        if key
    ]
    if not labels:
        return "Create a module first, then mention its name when you ask."
    return "Mention one of these modules: " + ", ".join(labels[:12]) + "."


def _is_all_request(raw: str) -> bool:
    text = (raw or "").lower()
    return any(phrase in text for phrase in [
        "all", "everything", "every ", "previous all", "all previous", "old all",
    ])


def _is_confirmed(raw: str) -> bool:
    text = (raw or "").lower()
    return any(phrase in text for phrase in [
        "confirm", "yes delete", "yes update", "go ahead", "do it",
        "delete all", "clear all", "remove all", "erase all",
    ])


def _infer_status(module: str, raw: str) -> str | None:
    text = (raw or "").lower()
    fields = _module_fields(module)
    status_field = next((field for field in fields if field.get("name") == "status"), None)
    options = status_field.get("options", []) if status_field else []
    if not options:
        return None

    if module == "jobs" and any(phrase in text for phrase in ["not applied", "haven't applied", "have not applied", "did not apply", "didn't apply"]):
        return "viewed" if "viewed" in options else None

    synonyms = {
        "in_progress": ["in progress", "started"],
        "interview": ["interview", "interviewing"],
        "responded": ["responded", "reply", "replied"],
        "withdrawn": ["withdrawn", "withdraw"],
        "rejected": ["rejected", "reject"],
        "completed": ["completed", "done", "finished"],
        "paused": ["paused", "pause"],
        "planned": ["planned", "plan"],
        "applied": ["applied", "submitted"],
        "viewed": ["viewed", "found", "saved", "bookmarked"],
        "offer": ["offer"],
    }
    for option in options:
        phrases = synonyms.get(option, [option.replace("_", " ")])
        if any(phrase in text for phrase in phrases):
            return option
    return None


def _infer_update_data(module: str, params: dict, raw: str) -> dict:
    skip = {"id", "record_id", "raw_instruction", "action", "module"}
    data = {k: v for k, v in params.items() if k not in skip}
    status = _infer_status(module, raw)
    if status:
        data["status"] = status
    return data


def _candidate_records(module: str, raw: str, limit: int = 500) -> list[dict]:
    if not database.table_exists(module):
        return []

    records = database.select(module, order_by="created_at DESC", limit=limit)
    text = (raw or "").lower()
    if not records:
        return []

    if _is_all_request(raw) or any(word in text for word in ["them", "these", "those"]):
        if module == "jobs" and any(phrase in text for phrase in ["not applied", "haven't applied", "have not applied", "did not apply", "didn't apply"]):
            applied = [rec for rec in records if str(rec.get("status", "")).lower() == "applied"]
            return applied or records
        return records

    quoted = re.findall(r"['\"]([^'\"]+)['\"]", raw or "")
    words = [
        word for word in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9._-]+", text)
        if len(word) > 2 and word not in {
            "delete", "remove", "clear", "erase", "update", "change", "edit", "modify",
            "mark", "status", "record", "records", "application", "applications",
            "jobs", "job", "from", "with", "that", "this", "please", "previous",
        }
    ]
    terms = [term.lower() for term in quoted] or words
    if not terms:
        return records[:10]

    matched = []
    for rec in records:
        haystack = " ".join(str(value).lower() for value in rec.values() if value is not None)
        if any(term in haystack for term in terms):
            matched.append(rec)
    return matched


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


def _success(message, data=None, action="", meta=None):
    return {
        "success":   True,
        "message":   message,
        "data":      data or [],
        "action":    action,
        "meta":      meta or {},
        "timestamp": datetime.now().isoformat(),
    }


def _attach_response_artifacts(result: dict, module: str | None) -> None:
    if not result.get("success"):
        return
    action = result.get("action", "")
    data = result.get("data")
    meta = result.setdefault("meta", {})
    artifact_list = meta.setdefault("artifacts", [])
    if isinstance(data, list) and data:
        table = artifacts.table((module or "Results").replace("_", " ").title(), data)
        if table:
            artifact_list.append(table)
        chart = artifacts.chart_for_records(module or "", data)
        if chart and action in {"read_data", "search_web", "summarize", "analyze"}:
            artifact_list.append(chart)
    elif action in {"summarize", "analyze"} and isinstance(result.get("message"), str):
        artifact_list.append(
            artifacts.document(
                (module or "Summary").replace("_", " ").title(),
                result.get("message", ""),
                filename=(module or "summary") + ".md",
            )
        )
        try:
            records = database.select(module, limit=50) if module else []
            chart = artifacts.chart_for_records(module or "", records)
            if chart:
                artifact_list.append(chart)
        except Exception:
            pass
    meta["suggestions"] = artifacts.suggestions(action, module)


def _error(message):
    return {
        "success":   False,
        "message":   message,
        "data":      [],
        "action":    "error",
        "meta":      {},
        "timestamp": datetime.now().isoformat(),
    }


def _clarify(message, action, data=None, meta=None):
    return {
        "success":   False,
        "message":   message,
        "data":      data or [],
        "action":    action,
        "meta":      {"needs_clarification": True, **(meta or {})},
        "timestamp": datetime.now().isoformat(),
    }


# ─────────────────────────────────────────────
#  Main execute
# ─────────────────────────────────────────────

def execute(route: dict, context: dict = None) -> dict:
    start = time.perf_counter()
    context = context or {}
    action = route.get("action")
    module = route.get("module")
    params = route.get("parameters", {})
    observability.set_context(session_id=context.get("session_id"))
    observability.log_event(
        logger,
        "agent.execute.start",
        action=action,
        module=module,
        params=_safe_params(params),
    )

    if action == "multi_step":
        return _execute_multi_step(route.get("steps", []), context)

    handlers = {
        "save_data":     _handle_save,
        "read_data":     _handle_read,
        "update_data":   _handle_update,
        "delete_data":   _handle_delete,
        "search_web":    _handle_search,
        "scrape":        _handle_scrape,
        "analyze":       _handle_analyze,
        "summarize":     _handle_summarize,
        "export":        _handle_export,
        "schedule":      _handle_schedule,
        "create_module": _handle_create_module,
        "check_email":   _handle_check_email,
    }

    handler = handlers.get(action)
    if not handler:
        raw = params.get("raw_instruction", "")
        if raw:
            try:
                response = brain.ask(raw, temperature=0.3)
                return _success(response, data=[], action="chat")
            except Exception:
                return _error("Unknown action: " + str(action))
        return _error("Unknown action: " + str(action))

    try:
        result = safeguards.run_with_timeout(lambda: handler(module, params, context))
        _attach_response_artifacts(result, module)
        result.setdefault("meta", {})["latency_ms"] = round((time.perf_counter() - start) * 1000, 2)
        observability.log_event(
            logger,
            "agent.execute.ok",
            action=result.get("action", action),
            module=module,
            latency_ms=result["meta"]["latency_ms"],
            success=result.get("success"),
        )
        return result
    except safeguards.ActionTimeoutError as e:
        observability.log_event(logger, "agent.execute.timeout", action=action, module=module, reason=str(e))
        return _error(str(e))
    except Exception as e:
        observability.log_event(logger, "agent.execute.error", action=action, module=module, error=str(e))
        return _error("Error executing " + str(action) + ": " + str(e))


# ─────────────────────────────────────────────
#  Handlers
# ─────────────────────────────────────────────

def _handle_save(module, params, context):
    if not module:
        return _error("No module specified for save_data.")

    if not database.table_exists(module):
        database.init_all_tables()

    skip = {"raw_instruction", "action", "module", "data"}
    data = {k: v for k, v in params.items() if k not in skip}

    raw = params.get("raw_instruction", "")
    if not data and raw:
        data = _extract_fields(module, raw)

    modules = _load_modules()
    schema  = modules.get(module, {})
    fields  = [f["name"] for f in schema.get("fields", [])]
    today   = datetime.now().strftime("%Y-%m-%d")
    if "date" in fields and "date" not in data:
        data["date"] = today
    if "date_applied" in fields and "date_applied" not in data:
        data["date_applied"] = today

    record_id = database.insert(module, data)
    record    = database.select_one(module, record_id)

    try:
        excel_manager.append_row(module, record)
    except Exception:
        pass

    return _success(
        "Saved to " + module + " (id: " + str(record_id) + ")",
        data=record,
        action="save_data",
    )


def _handle_read(module, params, context):
    raw = params.get("raw_instruction", "")

    # No module — answer conversationally via AI with memory context
    if not module:
        if raw:
            try:
                # Build prompt with conversation context from memory
                prompt     = raw
                session_id = context.get("session_id", "")
                if session_id:
                    try:
                        from backend.core import memory as mem
                        mem_context = mem.build_context(session_id, raw)
                        file_context = _session_file_context(session_id, raw)
                        combined_context = "\n\n".join(part for part in [mem_context, file_context] if part)
                        if combined_context:
                            prompt = prompt_templates.chat_prompt(raw, combined_context)
                    except Exception:
                        pass

                cfg = prompt_templates.config_for("chat")
                response = brain.ask(prompt, temperature=cfg["temperature"], max_tokens=cfg["max_tokens"])
                return _success(response, data=[], action="chat")
            except Exception as e:
                return _error("Could not process: " + str(e))
        return _error("No module specified for read_data.")

    if not database.table_exists(module):
        return _success(
            "No data found in " + module + " yet.",
            data=[],
            action="read_data",
        )

    skip    = {"raw_instruction", "fields", "order_by", "limit", "offset", "query", "filter"}
    filters = {k: v for k, v in params.items() if k not in skip and isinstance(v, str)}

    limit    = int(params.get("limit", 50))
    order_by = params.get("order_by", "created_at DESC")

    records = database.select(module, filters=filters or None, order_by=order_by, limit=limit)
    total   = database.count(module)

    try:
        cfg = prompt_templates.config_for("summarize")
        prompt = prompt_templates.summarize_records_prompt(module, json.dumps(records[:5]), len(records))
        message = brain.ask(prompt, temperature=cfg["temperature"], max_tokens=cfg["max_tokens"])
    except Exception:
        message = "Found " + str(len(records)) + " records in " + module + "."

    return _success(
        message,
        data=records,
        action="read_data",
        meta={"total": total, "returned": len(records)},
    )


def _handle_update(module, params, context):
    raw = params.get("raw_instruction", "")
    module = _resolve_module(module, raw)
    if not module:
        return _error("I could not tell which module to update. " + _module_hint())

    record_id = params.get("id") or params.get("record_id")
    if not record_id:
        update_data = _infer_update_data(module, params, raw)
        if not update_data:
            fields = ", ".join(field.get("name", "") for field in _module_fields(module) if field.get("name"))
            return _clarify(
                "I found the " + module + " area, but I could not tell what to change. You can mention one of these fields: " + fields,
                action="update_data",
                meta={"module": module},
            )

        candidates = _candidate_records(module, raw)
        if not candidates:
            return _success(
                "I understood the update for " + module + ", but I could not find matching records.",
                data=[],
                action="update_data",
                meta={"matched": 0, "update": update_data},
            )

        if len(candidates) > 20 and not _is_confirmed(raw):
            return _success(
                "I found " + str(len(candidates)) + " " + module + " records that could be updated. Say 'confirm update " + module + "' if you want me to update all of them.",
                data=_preview_records(candidates),
                action="update_data",
                meta={"confirmation_required": True, "matched": len(candidates), "update": update_data},
            )

        updated_records = []
        for rec in candidates:
            if database.update(module, int(rec["id"]), update_data):
                updated = database.select_one(module, int(rec["id"]))
                if updated:
                    updated_records.append(updated)

        try:
            excel_manager.sync_module(module)
        except Exception:
            pass

        return _success(
            "Updated " + str(len(updated_records)) + " " + module + " record(s): " + ", ".join(_record_label(rec) for rec in updated_records[:5]),
            data=updated_records,
            action="update_data",
            meta={"matched": len(candidates), "updated": len(updated_records), "update": update_data},
        )

    update_data = {k: v for k, v in params.items()
                   if k not in ["id", "record_id", "raw_instruction"]}

    updated = database.update(module, int(record_id), update_data)
    if not updated:
        return _error("Record " + str(record_id) + " not found in " + module + ".")

    record = database.select_one(module, int(record_id))
    try:
        excel_manager.sync_module(module)
    except Exception:
        pass

    return _success(
        "Updated record " + str(record_id) + " in " + module + ".",
        data=record,
        action="update_data",
    )


def _handle_delete(module, params, context):
    raw = params.get("raw_instruction", "")
    module = _resolve_module(module, raw)
    if not module:
        return _error("I could not tell which module to delete from. " + _module_hint())

    record_id = params.get("id") or params.get("record_id")
    if not record_id:
        candidates = _candidate_records(module, raw)
        if not candidates:
            return _success(
                "I understood you want to delete from " + module + ", but I could not find matching records.",
                data=[],
                action="delete_data",
                meta={"matched": 0},
            )

        confirmed = _is_confirmed(raw) or (_is_all_request(raw) and len(candidates) == database.count(module))
        if not confirmed:
            return _success(
                "I found " + str(len(candidates)) + " " + module + " record(s) that match. Say 'confirm delete " + module + "' to delete them.",
                data=_preview_records(candidates),
                action="delete_data",
                meta={"confirmation_required": True, "matched": len(candidates)},
            )

        deleted_ids = []
        for rec in candidates:
            if database.delete(module, int(rec["id"])):
                deleted_ids.append(rec["id"])

        try:
            excel_manager.sync_module(module)
        except Exception:
            pass

        return _success(
            "Deleted " + str(len(deleted_ids)) + " " + module + " record(s).",
            data={"deleted_ids": deleted_ids, "preview": _preview_records(candidates)},
            action="delete_data",
            meta={"deleted": len(deleted_ids)},
        )

    deleted = database.delete(module, int(record_id))
    if not deleted:
        return _error("Record " + str(record_id) + " not found in " + module + ".")

    try:
        excel_manager.sync_module(module)
    except Exception:
        pass

    return _success(
        "Deleted record " + str(record_id) + " from " + module + ".",
        data={"deleted_id": record_id},
        action="delete_data",
    )


def _handle_search(module, params, context):
    from backend.agents import search_agent

    raw      = params.get("raw_instruction", "")
    query    = params.get("query") or raw
    location = params.get("location") or params.get("country", "")

    if not location and raw:
        location_map = {
            "japan": "Japan", "tokyo": "Japan", "osaka": "Japan",
            "singapore": "Singapore",
            "germany": "Germany", "berlin": "Germany",
            "usa": "USA", "united states": "USA", "america": "USA",
            "uk": "UK", "london": "UK", "england": "UK",
            "australia": "Australia", "sydney": "Australia",
            "canada": "Canada", "toronto": "Canada",
            "india": "India", "bangalore": "India",
        }
        raw_lower = raw.lower()
        for kw, loc in location_map.items():
            if kw in raw_lower:
                location = loc
                break

    if not query:
        return _error("No search query provided.")

    job_keywords = [
        "job", "position", "opening", "career", "vacancy", "hiring",
        "engineer", "developer", "analyst", "sqa", "qa", "manager",
        "designer", "remote work", "remote job", "work from home"
    ]
    is_job = any(kw in query.lower() for kw in job_keywords)

    if is_job:
        remote_only = "remote" in query.lower()
        observability.log_event(
            logger,
            "tool.invoke",
            tool="search_jobs",
            parameters={"query": query, "location": location, "remote_only": remote_only},
        )
        result      = search_agent.search_jobs(
            query, location,
            remote_only=remote_only,
            save_to_db=True
        )
        jobs = result.get("jobs", [])

        display = []
        for j in jobs:
            display.append({
                "company":    j.get("company", "Unknown"),
                "position":   j.get("position", ""),
                "location":   j.get("country", location),
                "salary":     j.get("salary_range", "Not specified"),
                "type":       j.get("employment_type", ""),
                "remote":     "Yes" if j.get("is_remote") else "No",
                "posted":     j.get("date_posted", ""),
                "apply_link": (j.get("apply_link", "")[:80]
                               if j.get("apply_link") else "")
            })

        msg = result["message"]
        if not jobs:
            msg += " Try broader terms or check if the location is supported."

        return _success(msg, data=display, action="search_web")
    else:
        try:
            cfg = prompt_templates.config_for("chat")
            response = brain.ask(prompt_templates.chat_prompt(query), temperature=cfg["temperature"], max_tokens=cfg["max_tokens"])
            return _success(response, data=[], action="chat")
        except Exception as e:
            return _error("Could not process: " + str(e))


def _handle_scrape(module, params, context):
    from backend.agents import search_agent

    company = params.get("company") or params.get("name", "")
    query   = params.get("query") or params.get("raw_instruction", "")
    url     = params.get("url") or params.get("source", "")

    if company:
        result = search_agent.scrape_company_jobs(company, query)
        return _success(result["message"], data=result["jobs"], action="scrape")
    elif url:
        result = search_agent.search_web(url)
        return _success(result["message"], data=result.get("results", []), action="scrape")
    else:
        return _error("No company or URL specified for scraping.")


def _handle_analyze(module, params, context):
    if not module:
        return _error("No module specified for analysis.")

    records = database.select(module, limit=50)
    if not records:
        return _success("No data in " + module + " to analyze yet.", data=[], action="analyze")

    cfg = prompt_templates.config_for("analyze")
    prompt = prompt_templates.analyze_records_prompt(module, json.dumps(records[:10]))
    try:
        analysis = brain.ask(prompt, temperature=cfg["temperature"], max_tokens=cfg["max_tokens"])
    except Exception:
        analysis = "You have " + str(len(records)) + " records in " + module + "."

    return _success(analysis, data={"records_analyzed": len(records)}, action="analyze")


def _handle_summarize(module, params, context):
    if not module:
        return _error("No module to summarize.")

    total   = database.count(module)
    records = database.select(module, limit=20)

    if not records:
        return _success("No data in " + module + " yet.", data=[], action="summarize")

    cfg = prompt_templates.config_for("summarize")
    prompt = prompt_templates.summarize_records_prompt(module, json.dumps(records[:5]), total)
    try:
        summary = brain.ask(prompt, temperature=cfg["temperature"], max_tokens=cfg["max_tokens"])
    except Exception:
        summary = "You have " + str(total) + " records in " + module + "."

    return _success(summary, data={"total": total}, action="summarize")


def _handle_export(module, params, context):
    if not module:
        return _error("No module specified for export.")
    try:
        path = excel_manager.export_filtered(
            module,
            params.get("filters") or {},
            params.get("filename")
        )
        return _success(
            "Exported " + module + " to " + path.name,
            data={"file": str(path)},
            action="export"
        )
    except Exception as e:
        return _error("Export failed: " + str(e))


def _handle_schedule(module, params, context):
    from backend.scheduler import proactive

    raw = params.get("raw_instruction") or ""
    frequency = params.get("frequency") or _infer_frequency(raw)
    name = params.get("name") or _schedule_name(raw)
    task = proactive.create_task(name, raw or name, frequency)
    return _success(
        "Scheduled task created: " + task["name"] + " (" + task["frequency"] + ").",
        data=task,
        action="schedule",
    )


def _infer_frequency(raw: str) -> str:
    text = (raw or "").lower()
    if "daily" in text or "every day" in text:
        return "daily"
    if "monthly" in text or "every month" in text:
        return "monthly"
    if "every" in text and any(day in text for day in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]):
        return "weekly"
    return "weekly"


def _schedule_name(raw: str) -> str:
    clean = " ".join((raw or "Scheduled task").split())
    if len(clean) > 64:
        clean = clean[:61].rstrip() + "..."
    return clean[:1].upper() + clean[1:]


def _handle_create_module(module, params, context):
    description = params.get("description") or params.get("raw_instruction") or ""
    if not description:
        return _error("Please describe what you want to track.")

    try:
        result     = schema_engine.create_module(description)
        module_key = list(result.keys())[0]
        schema     = result[module_key]
        database.create_table(module_key, schema)
        excel_manager.create_excel(module_key)
        return _success(
            "Created module '" + module_key + "' — " +
            schema.get("label", "") + " with " +
            str(len(schema.get("fields", []))) + " fields.",
            data=result,
            action="create_module",
        )
    except ValueError as e:
        return _error(str(e))


def _handle_check_email(module, params, context):
    return _success("Email agent coming in next build step.", data={}, action="check_email")


# ─────────────────────────────────────────────
#  Multi-step
# ─────────────────────────────────────────────

def _execute_multi_step(steps, context):
    results  = []
    messages = []
    for i, step in enumerate(steps, 1):
        result = execute(step, context)
        results.append(result)
        messages.append("Step " + str(i) + ": " + result.get("message", ""))
        if not result.get("success"):
            messages.append("Stopped at step " + str(i) + ".")
            break
    return _success("\n".join(messages), data=results, action="multi_step")


# ─────────────────────────────────────────────
#  AI field extractor
# ─────────────────────────────────────────────

def _extract_fields(module, instruction):
    modules = _load_modules()
    schema  = modules.get(module, {})
    fields  = [f["name"] for f in schema.get("fields", [])]
    cfg = prompt_templates.config_for("extract_fields")
    prompt = prompt_templates.extract_fields_prompt(module, instruction, fields)
    try:
        result = brain.ask_json(prompt, temperature=cfg["temperature"])
        return {key: value for key, value in result.items() if key in fields}
    except Exception:
        return {}


def _safe_params(params: dict) -> dict:
    safe = {}
    for key, value in params.items():
        if key in {"raw_instruction", "query", "description"}:
            safe[key] = safeguards.truncate_text(str(value), 300, key)
        else:
            safe[key] = value
    return safe


# ─────────────────────────────────────────────
#  Test
# ─────────────────────────────────────────────

if __name__ == "__main__":
    from backend.core import router

    database.init_all_tables()
    print("Testing universal agent...\n")
    print("=" * 60)

    tests = [
        "Add a job application for Tesla, Software Engineer, USA",
        "Show me all my job applications",
        "Summarize my jobs data",
        "Find remote QA jobs",
    ]

    for instruction in tests:
        print("\nInstruction: " + instruction)
        print("-" * 40)
        try:
            route  = router.route(instruction)
            result = execute(route)
            print("  Success : " + str(result["success"]))
            print("  Message : " + result["message"][:120])
        except Exception as e:
            print("  Error   : " + str(e))
