from __future__ import annotations

import json
import sys
from io import BytesIO
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from backend.agents import universal_agent
from backend.api.routes.conversation import _extract_text_from_files_sync, _max_chars
from backend.core import brain, memory as mem, router as instruction_router
from backend.data import database

CONFIG = ROOT / "config" / "modules.json"


def _load_modules() -> dict:
    with open(CONFIG, "r") as f:
        return json.load(f).get("modules", {})


def _module_counts(modules: dict) -> dict:
    database.init_all_tables()
    return {key: database.count(key) for key in modules}


def _json_error(message: str, status: int = 400) -> tuple[int, dict]:
    return status, {"success": False, "message": message}


class Uploaded:
    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        self.file = BytesIO(data)


class Handler(BaseHTTPRequestHandler):
    server_version = "PersonalOSDevAPI/1.0"

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

    def _read_multipart(self) -> tuple[dict[str, str], list[Uploaded]]:
        content_type = self.headers.get("Content-Type", "")
        marker = "boundary="
        if marker not in content_type:
            return {}, []
        boundary = content_type.split(marker, 1)[1].strip().strip('"')
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length)
        parts = body.split(("--" + boundary).encode("utf-8"))
        fields: dict[str, str] = {}
        files: list[Uploaded] = []

        for part in parts:
            part = part.strip()
            if not part or part == b"--":
                continue
            if part.endswith(b"--"):
                part = part[:-2].strip()
            header_blob, sep, payload = part.partition(b"\r\n\r\n")
            if not sep:
                continue
            payload = payload.rstrip(b"\r\n")
            headers = header_blob.decode("utf-8", errors="ignore").split("\r\n")
            disposition = next((h for h in headers if h.lower().startswith("content-disposition:")), "")
            name = _disposition_value(disposition, "name")
            filename = _disposition_value(disposition, "filename")
            if not name:
                continue
            if filename:
                files.append(Uploaded(filename, payload))
            else:
                fields[name] = payload.decode("utf-8", errors="ignore")

        return fields, files

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle(self, method: str):
        try:
            status, payload = self._route(method)
        except Exception as e:
            status, payload = _json_error(str(e), 500)
        self._send_json(status, payload)

    def _route(self, method: str) -> tuple[int, dict]:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if method == "GET" and path in ("/", "/health"):
            return 200, {"status": "ok"}

        if method == "GET" and path == "/api/status":
            modules = _load_modules()
            try:
                ai_status = brain.get_status()
            except Exception as e:
                ai_status = {"ready": False, "error": str(e)}
            return 200, {
                "success": True,
                "ai": ai_status,
                "modules": len(modules),
                "counts": _module_counts(modules),
            }

        if method == "POST" and path == "/api/chat":
            req = self._read_json()
            instruction = str(req.get("instruction", "")).strip()
            if not instruction:
                return _json_error("Instruction is required")
            session_id = req.get("session_id") or mem.today_session_id()
            database.init_all_tables()
            route = instruction_router.route(instruction)
            result = universal_agent.execute(route, context={"session_id": session_id})
            result.setdefault("meta", {})["route"] = route
            try:
                mem.save_exchange(session_id, instruction, result.get("message", ""), result.get("action", ""))
            except Exception:
                pass
            return 200, result

        if method == "POST" and path == "/api/jobs/search":
            req = self._read_json()
            query_text = str(req.get("query", "")).strip()
            location = str(req.get("location", "")).strip()
            if not query_text:
                return _json_error("Query is required")
            text = query_text + ((" in " + location) if location else "")
            if "job" not in text.lower():
                text = "Find " + text + " jobs"
            route = {
                "action": "search_web",
                "module": "jobs",
                "parameters": {"raw_instruction": text, "query": text, "location": location},
                "explanation": "Job search workspace",
                "steps": [],
            }
            result = universal_agent.execute(route, context={"session_id": req.get("session_id") or mem.today_session_id()})
            result.setdefault("meta", {})["route"] = route
            return 200, result

        if method == "POST" and path == "/api/conversation":
            fields, files = self._read_multipart()
            instruction = fields.get("instruction", "").strip()
            if not instruction:
                return _json_error("Instruction is required")
            session_id = fields.get("session_id") or mem.today_session_id()
            database.init_all_tables()

            file_blocks = _extract_text_from_files_sync(files) if files else []
            augmented = instruction
            if file_blocks:
                augmented = (
                    "You have uploaded files. Use them to answer the user's request as best as you can. "
                    "If you cannot read something, say so and suggest next steps.\n\n"
                    + "".join(file_blocks)
                    + "\n\nUSER REQUEST:\n"
                    + instruction
                )
            augmented = _max_chars(augmented, 20000)
            result = universal_agent.execute(
                {
                    "action": "read_data",
                    "module": None,
                    "parameters": {"raw_instruction": augmented},
                    "explanation": "Forced conversational routing",
                    "steps": [],
                },
                context={"session_id": session_id},
            )
            try:
                mem.save_exchange(session_id, instruction, result.get("message", ""), result.get("action", ""))
            except Exception:
                pass
            return 200, result

        if method == "POST" and path == "/api/files/extract":
            fields, files = self._read_multipart()
            if not files:
                return _json_error("File is required")
            block = _extract_text_from_files_sync([files[0]])[0]
            marker = f"--- FILE: {files[0].filename} ---"
            text = block.replace(marker, "", 1).strip()
            if fields.get("save") in ("true", "1", "yes"):
                _save_extracted_file(files[0].filename, text)
            return 200, {
                "success": bool(text) and not text.startswith("[Could not extract") and not text.startswith("[No text"),
                "filename": files[0].filename,
                "text": text,
                "preview": text[:3000],
                "chars": len(text),
                "words": len(text.split()),
            }

        if method == "GET" and path == "/api/modules":
            modules = _load_modules()
            return 200, {"success": True, "modules": modules, "counts": _module_counts(modules)}

        if method == "GET" and path == "/api/dashboard":
            modules = _load_modules()
            database.init_all_tables()
            items = []
            for key, schema in modules.items():
                items.append({
                    "key": key,
                    "module": schema,
                    "count": database.count(key),
                    "recent": database.select(key, limit=5, order_by="created_at DESC"),
                })
            return 200, {"success": True, "items": items}

        parts = [part for part in path.split("/") if part]

        if len(parts) == 4 and parts[:2] == ["api", "modules"] and parts[3] == "records":
            module_key = parts[2]
            modules = _load_modules()
            if module_key not in modules:
                return _json_error("Unknown module: " + module_key, 404)

            if method == "GET":
                search = (query.get("search") or [""])[0]
                status = (query.get("status") or [""])[0]
                limit = int((query.get("limit") or ["500"])[0])
                database.init_all_tables()
                records = database.select(module_key, limit=limit)
                if search:
                    needle = search.lower()
                    records = [r for r in records if any(needle in str(v).lower() for v in r.values())]
                if status and status != "All":
                    records = [r for r in records if r.get("status") == status]
                return 200, {
                    "success": True,
                    "module": modules[module_key],
                    "records": records,
                    "total": database.count(module_key),
                    "showing": len(records),
                }

            if method == "POST":
                req = self._read_json()
                database.init_all_tables()
                record_id = database.insert(module_key, req.get("data") or {})
                record = database.select_one(module_key, record_id)
                try:
                    from backend.data import excel_manager
                    excel_manager.append_row(module_key, record)
                except Exception:
                    pass
                return 200, {"success": True, "message": "Record saved.", "record": record}

        if len(parts) == 5 and parts[:2] == ["api", "modules"] and parts[3] == "records" and method == "PUT":
            module_key = parts[2]
            record_id = int(parts[4])
            modules = _load_modules()
            if module_key not in modules:
                return _json_error("Unknown module: " + module_key, 404)
            req = self._read_json()
            database.init_all_tables()
            updated = database.update(module_key, record_id, req.get("data") or {})
            if not updated:
                return _json_error("Record not found", 404)
            try:
                from backend.data import excel_manager
                excel_manager.sync_module(module_key)
            except Exception:
                pass
            return 200, {"success": True, "message": "Record updated.", "record": database.select_one(module_key, record_id)}

        if len(parts) == 5 and parts[:2] == ["api", "modules"] and parts[3] == "records" and method == "DELETE":
            module_key = parts[2]
            record_id = int(parts[4])
            modules = _load_modules()
            if module_key not in modules:
                return _json_error("Unknown module: " + module_key, 404)
            database.init_all_tables()
            deleted = database.delete(module_key, record_id)
            if not deleted:
                return _json_error("Record not found", 404)
            return 200, {"success": True, "message": "Record deleted.", "deleted_id": record_id}

        if path == "/api/memory/sessions/list" and method == "GET":
            return 200, {"success": True, "sessions": mem.get_all_sessions()}

        if len(parts) == 3 and parts[:2] == ["api", "memory"] and method == "GET":
            session_id = parts[2]
            limit = int((query.get("limit") or ["100"])[0])
            return 200, {
                "success": True,
                "session_id": session_id,
                "history": mem.get_full_history(session_id)[-limit:],
                "summary": mem.get_session_summary(session_id),
            }

        if path == "/api/memory/search" and method == "POST":
            req = self._read_json()
            return 200, {"success": True, "results": mem.search_all_sessions(str(req.get("query", "")))}

        if len(parts) == 4 and parts[:2] == ["api", "memory"] and parts[3] == "summarize" and method == "POST":
            return 200, {"success": True, "summary": mem.summarize_session(parts[2])}

        if len(parts) == 3 and parts[:2] == ["api", "memory"] and method == "DELETE":
            mem.clear_session(parts[2])
            return 200, {"success": True, "message": "Memory cleared."}

        return _json_error("Not found: " + path, 404)


def _disposition_value(header: str, key: str) -> str:
    token = key + "="
    for part in header.split(";"):
        part = part.strip()
        if part.startswith(token):
            return part[len(token):].strip().strip('"')
    return ""


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


def main():
    host = "127.0.0.1"
    port = 8000
    print(f"Personal OS dev API listening on http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
