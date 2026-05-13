# Personal AI Operating System

A fully dynamic, AI-powered personal data management system.
Built with Python, FastAPI, Llama, and Streamlit.

## Structure
- `backend/` — FastAPI server, AI brain, agents, data layer
- `frontend/` — Streamlit UI
- `infrastructure/` — Docker, Nginx configs
- `config/` — Module definitions, AI prompts
- `data/` — Your personal data (SQLite + Excel files)

## Quick Start
```bash
# 1. Start Llama
ollama serve

# 2. Start backend
uvicorn backend.main:app --reload

# 3. Start frontend
streamlit run frontend/app.py
```
