# Personal AI Operating System

A local-first personal AI workspace built with FastAPI, React, SQLite, optional RAG/vector search, and Groq/Ollama model backends.

The goal is to give you a private assistant that can manage dynamic projects, remember useful context, work with uploaded documents, and answer with grounded sources when files are available.

## What It Can Do

- Chat with Groq or local Ollama, with fallback handling when one backend is unavailable.
- Create dynamic modules instead of being limited to hardcoded areas like jobs, finance, health, or learning.
- Create project workspaces similar to ChatGPT/Claude Projects.
- Upload project files and ask questions over them.
- Store project memory and reuse it in later conversations.
- Generate project artifacts such as notes, drafts, and structured outputs.
- Ingest PDFs, DOCX, XLSX, CSV, JSON, HTML, TXT, and Markdown.
- Use OCR for scanned PDFs/images when Tesseract is installed.
- Use local SQLite vector search by default, with optional Chroma support.
- Use deterministic local embeddings, Ollama embeddings, or optional sentence-transformer embeddings.
- Run tests, linting, type checks, and a lightweight golden-prompt eval.
- Log routing/model/tool events with request/session/project context.

## Current Limits

This is still a local engineering prototype.

- Best intelligence requires a strong model backend, preferably Groq or a capable local Ollama model.
- Chroma and `sentence-transformers` may need Python 3.12 because some ML wheels are not available for Python 3.14.
- Complex JavaScript-heavy web scraping requires Playwright setup and `PERSONAL_OS_PLAYWRIGHT_SCRAPE=true`.
- Fine-tuning/LoRA support is a prototype workflow, not a production training platform.
- Auth exists through API key configuration, but full multi-user production permissions are still a future hardening area.

## Tech Stack

- Backend: Python, FastAPI, SQLite
- Frontend: React + Vite
- Legacy UI: Streamlit
- Local model option: Ollama
- Cloud model option: Groq
- Extra fallback model options: OpenRouter and Gemini
- Document extraction: PDF/DOCX/XLSX/PPTX/CSV/JSON/HTML/TXT/MD, optional OCR
- Vector storage: SQLite by default, optional Chroma

## Project Structure

```text
backend/          FastAPI API, model layer, routing, memory, RAG, projects
frontend-react/   Main React UI
frontend/         Legacy Streamlit UI
config/           Dynamic module definitions and prompt config
data/             Local SQLite data, uploads, vector data, generated state
tests/            Unit tests, integration tests, golden prompt evals
scripts/          Utility scripts, including LoRA prototype tooling
```

## Quick Start

Install backend and frontend dependencies:

```bash
make install-backend
make install-frontend
```

Create local environment config:

```bash
cp .env.example .env
```

Start Ollama if you want a local model backend:

```bash
ollama serve
ollama pull llama3.2
```

Or set Groq in `.env`:

```bash
GROQ_API_KEY=your_key_here
GROQ_MODEL=llama-3.3-70b-versatile
```

Run the backend:

```bash
make backend
```

Run the React frontend:

```bash
make frontend-react
```

Open the app:

```text
http://localhost:5173
```

If the backend port is busy:

```bash
make backend BACKEND_PORT=8001
cd frontend-react && VITE_API_BASE_URL=http://127.0.0.1:8001 npm run dev
```

## Common Commands

```bash
make backend          # Start FastAPI backend on 127.0.0.1:8000
make frontend-react   # Start React/Vite frontend
make frontend         # Start legacy Streamlit frontend
make test             # Run pytest
make lint             # Run ruff
make typecheck        # Compile Python and build React frontend
make eval             # Run lightweight golden-prompt eval
```

## Environment Variables

Important settings live in `.env.example`.

Model backend:

```bash
GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
OPENROUTER_API_KEY=
OPENROUTER_MODEL=qwen/qwen-2.5-coder-32b-instruct
GEMINI_API_KEY=
GEMINI_MODEL=gemini-1.5-flash
PERSONAL_OS_MODEL_BACKEND=auto
PERSONAL_OS_MODEL_ORDER=groq,ollama,openrouter,gemini
```

Safety and reliability:

```bash
PERSONAL_OS_MODEL_RETRIES=2
PERSONAL_OS_TOOL_RETRIES=2
PERSONAL_OS_ACTION_TIMEOUT_SECONDS=30
PERSONAL_OS_TOOL_TIMEOUT_SECONDS=15
PERSONAL_OS_MAX_PROMPT_CHARS=20000
PERSONAL_OS_MAX_MEMORY_CONTEXT_CHARS=6000
PERSONAL_OS_MAX_OUTPUT_CHARS=12000
```

RAG/vector search:

```bash
PERSONAL_OS_EMBEDDING_PROVIDER=local
PERSONAL_OS_VECTOR_BACKEND=sqlite
PERSONAL_OS_RERANKER=lexical
```

API protection:

```bash
PERSONAL_OS_API_KEY=
PERSONAL_OS_API_KEYS=
```

## Projects

Projects are the main workspace for long-running work.

Each project can have:

- its own chat history
- custom instructions
- uploaded files
- project memory
- generated artifacts
- source-grounded answers from uploaded documents

The project API is available under:

```text
/api/projects
```

Use this for the user experience you described: create a project, upload documents, continue the conversation later, and have the assistant remember what belongs to that project.

## Dynamic Modules

Modules are no longer fixed to starter categories.

You can create, edit, and delete modules for anything: applications, clients, research papers, travel plans, invoices, house repairs, learning plans, or your own custom trackers.

Module APIs:

```text
GET    /api/modules
POST   /api/modules
GET    /api/modules/{module_key}
PUT    /api/modules/{module_key}
DELETE /api/modules/{module_key}?drop_data=true
```

Module schemas live in `config/modules.json`. Each module owns its own SQLite table.

## Document Intelligence

Uploads use a shared ingestion service so files can be reused across chat, extraction, and RAG.

Supported locally:

- PDF text and tables
- DOCX paragraphs and tables
- XLSX sheets
- PPTX slides, when optional dependency is installed
- CSV, JSON, HTML, TXT, and MD
- scanned PDFs and images with OCR, when Tesseract is installed

Install optional document dependencies:

```bash
make install-documents
```

Install OCR on macOS:

```bash
brew install tesseract
```

Check document readiness:

```text
GET /api/status
```

The `document_ingestion` section reports which file capabilities are active and which packages are missing.

## RAG And Vector Search

Default local setup:

```bash
PERSONAL_OS_VECTOR_BACKEND=sqlite
PERSONAL_OS_EMBEDDING_PROVIDER=local
```

Recommended stronger local embeddings with Ollama:

```bash
ollama pull nomic-embed-text
PERSONAL_OS_EMBEDDING_PROVIDER=ollama
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
```

Optional Chroma setup:

```bash
make install-rag
PERSONAL_OS_VECTOR_BACKEND=chroma
PERSONAL_OS_CHROMA_DIR=./data/chroma
PERSONAL_OS_CHROMA_COLLECTION=personal_os_rag
```

Note: if you are on Python 3.14 and Chroma/ML dependencies fail to install, use Python 3.12 for the Chroma environment or stay on SQLite vector storage with Ollama embeddings.

## Web Scraping

Basic HTML extraction works without a browser. For complex JavaScript-heavy pages:

```bash
make playwright-install
PERSONAL_OS_PLAYWRIGHT_SCRAPE=true
```

## Fine-Tuning Prototype

LoRA/PEFT support is available as a prototype for experimentation after you have labeled training data.

Install optional dependencies:

```bash
make install-finetune
```

Run the prototype:

```bash
make finetune-lora
```

Expected input:

```text
data/training/labels.jsonl
```

Output:

```text
data/training/lora-adapter
```

## Testing And Evaluation

Run everything important:

```bash
make lint
make typecheck
make test
make eval
```

The eval harness uses golden prompt cases in `tests/golden_prompts.json`.

## Troubleshooting

If the React app goes blank after a code change, hard refresh the browser and restart Vite:

```bash
make frontend-react
```

If chat says no streaming model backend is available:

- Make sure `GROQ_API_KEY` is set, or
- Make sure Ollama is running with `ollama serve`, and
- Make sure the configured `OLLAMA_MODEL` exists locally, or
- Configure `OPENROUTER_API_KEY` / `GEMINI_API_KEY` as additional fallbacks.

Recommended free/low-cost fallback setup for code rewrites:

```bash
OLLAMA_MODEL=qwen2.5-coder:7b
OPENROUTER_API_KEY=your_openrouter_key
OPENROUTER_MODEL=qwen/qwen-2.5-coder-32b-instruct
GEMINI_API_KEY=your_gemini_key
GEMINI_MODEL=gemini-1.5-flash
PERSONAL_OS_MODEL_BACKEND=auto
PERSONAL_OS_MODEL_ORDER=groq,ollama,openrouter,gemini
```

Check backend status:

```text
GET /api/status
```

If project file upload works but answers are weak, install document dependencies and use stronger embeddings:

```bash
make install-documents
ollama pull nomic-embed-text
```

Then set:

```bash
PERSONAL_OS_EMBEDDING_PROVIDER=ollama
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
```

## More Docs

- `DEVELOPMENT.md` has local development details.
- `MERIDIAN_PHASE_2_3.md` documents the Phase 2/3 implementation notes when present.
- `.env.example` is the source of truth for configurable runtime options.
