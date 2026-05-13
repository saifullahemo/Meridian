from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from backend.core import memory, observability, rag

logger = observability.get_logger(__name__)

app = FastAPI(
    title="Personal OS API",
    description="Your Personal AI Operating System",
    version="1.0.0"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context_middleware(request, call_next):
    request_id = request.headers.get("x-request-id") or observability.new_request_id()
    session_id = request.headers.get("x-session-id", "")
    observability.set_context(request_id=request_id, session_id=session_id)
    with observability.trace_span("http.request", logger, method=request.method, path=request.url.path):
        response = await call_next(request)
    response.headers["x-request-id"] = request_id
    return response

@app.get("/")
def root():
    return {"status": "Personal OS is running"}

@app.get("/health")
def health():
    return {"status": "ok"}


@app.on_event("startup")
def enforce_retention_on_startup():
    if os.getenv("PERSONAL_OS_RETENTION_ON_STARTUP", "true").lower() != "true":
        return
    days = int(os.getenv("PERSONAL_OS_RETENTION_DAYS", "90"))
    memory.cleanup_older_than(days)
    rag.cleanup_older_than(days)
    observability.cleanup_older_than(days)


# ─────────────────────────────────────────────
# API routes
# ─────────────────────────────────────────────

try:
    from backend.api.routes.conversation import router as conversation_router

    app.include_router(conversation_router)
except Exception:
    # Keep server running even if optional route deps are missing
    pass

try:
    from backend.api.routes.app_data import router as app_data_router

    app.include_router(app_data_router)
except Exception:
    # Keep server running even if optional route deps are missing
    pass
