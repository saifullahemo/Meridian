.PHONY: backend frontend frontend-react test lint typecheck eval install-backend install-frontend install-rag install-finetune playwright-install finetune-lora

PYTHON ?= python3
BACKEND_HOST ?= 127.0.0.1
BACKEND_PORT ?= 8000
FRONTEND_PORT ?= 8501

install-backend:
	$(PYTHON) -m pip install -r requirements.txt

install-frontend:
	cd frontend-react && npm install

install-rag:
	$(PYTHON) -m pip install -r requirements-rag.txt

install-finetune:
	$(PYTHON) -m pip install -r requirements-finetune.txt

playwright-install:
	$(PYTHON) -m playwright install chromium

backend:
	$(PYTHON) -m uvicorn backend.main:app --reload --host $(BACKEND_HOST) --port $(BACKEND_PORT)

frontend:
	$(PYTHON) -m streamlit run frontend/app.py --server.port $(FRONTEND_PORT)

frontend-react:
	cd frontend-react && npm run dev

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check backend frontend tests

typecheck:
	$(PYTHON) -m compileall -q -x '(^|/)(venv|\.venv|node_modules)(/|$$)' backend frontend tests
	cd frontend-react && npm run build

eval:
	$(PYTHON) -m backend.eval_harness --cases tests/golden_prompts.json

finetune-lora:
	$(PYTHON) scripts/prototype_finetune_lora.py --data data/training/labels.jsonl --output data/training/lora-adapter
