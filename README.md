# Personal AI Operating System

A fully dynamic, AI-powered personal data management system.

Built with Python (FastAPI), an LLM “brain” with Groq-first + Ollama fallback, and a React + Streamlit frontend UI.

## Structure
- `backend/` — FastAPI server, AI brain, agents, data layer
- `frontend/` — Streamlit UI
- `infrastructure/` — Docker, Nginx configs
- `config/` — Module definitions, AI prompts
- `data/` — Your personal data (SQLite + Excel files)

## Quick Start
```bash
# 1. Start local Ollama (optional fallback)
ollama serve

# 2. Set env vars (recommended)
# - GROQ_API_KEY (optional; enables Groq backend)
# - OLLAMA_BASE_URL (optional; default http://localhost:11434)

# 3. Start backend
make backend

# 4. Start frontend (Streamlit)
make frontend

# 5. Start frontend-react (Vite)
make frontend-react
```

## Document Intelligence

Uploads now go through a shared document ingestion service for chat, file extraction, and RAG ingestion.

Supported locally:
- PDF text/tables
- DOCX text/tables
- XLSX sheets
- PPTX slides, when optional dependency is installed
- CSV, JSON, HTML, TXT, MD
- image/scanned PDF OCR, when OCR dependencies are installed

Recommended setup:

```bash
make install-documents
brew install tesseract
```

For stronger local RAG:

```bash
ollama pull nomic-embed-text
export PERSONAL_OS_EMBEDDING_PROVIDER=ollama
export OLLAMA_EMBEDDING_MODEL=nomic-embed-text
```

Chroma is supported by the code path, but this local Python 3.14 runtime does not currently have compatible `onnxruntime`/`torch` wheels for Chroma plus `sentence-transformers`. Use the built-in SQLite vector store with Ollama embeddings here, or create a Python 3.12 environment before running `make install-rag`.

Check readiness at `GET /api/status`; the `document_ingestion` section reports missing OCR/PDF/Office capabilities.

## Dynamic Projects / Modules

Modules are no longer limited to the starter areas such as jobs, finance, health, or learning. Use the React app's Modules rail or the `/api/modules` endpoints to create, edit, and delete any project-style tracker you want: pets, travel, research papers, clients, house repairs, applications, invoices, or anything else.

Each module owns its own schema and SQLite table. The router scores the live module config by key, label, description, and field names, so natural-language commands can target newly created modules without adding code.

## Meridian Phase 2/3

The app now includes first-pass Phase 2 and Phase 3 capabilities:
- LLM tool-planner hook with deterministic fallback
- Inline chat artifacts for tables, charts, documents, and suggestions
- Proactive pattern detection and dashboard notification cards
- Morning briefing endpoint
- Scheduled task CRUD and natural-language schedule creation

See `MERIDIAN_PHASE_2_3.md` for implementation details and remaining production gaps.
