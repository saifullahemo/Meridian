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
