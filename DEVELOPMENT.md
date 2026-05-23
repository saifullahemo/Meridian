# Development

## Local Setup

```bash
python3 -m pip install -r requirements.txt
cd frontend-react && npm install
```

Optional document intelligence dependencies:

```bash
make install-documents
```

For OCR, also install the system `tesseract` binary:

```bash
# macOS
brew install tesseract
```

Optional RAG/vector dependencies:

```bash
make install-rag
```

Optional LoRA/fine-tuning dependencies:

```bash
make install-finetune
```

## Run

```bash
make backend
make frontend-react
```

If port `8000` is busy:

```bash
make backend BACKEND_PORT=8001
cd frontend-react && VITE_API_BASE_URL=http://127.0.0.1:8001 npm run dev
```

## Dynamic Modules

The data workspace is project-style: modules are defined in `config/modules.json` and can be created, edited, or deleted from the React UI.

API endpoints:

```text
GET    /api/modules
POST   /api/modules
GET    /api/modules/{module_key}
PUT    /api/modules/{module_key}
DELETE /api/modules/{module_key}?drop_data=true
```

Module schemas require `label`, `description`, and `fields`. Field types are `text`, `number`, `date`, `enum`, and `boolean`. Enum fields require `options`.

## AI Backends

Groq is optional:

```bash
GROQ_API_KEY=...
```

Ollama is local:

```bash
ollama serve
ollama pull llama3.2
```

Recommended local embeddings:

```bash
ollama pull nomic-embed-text
PERSONAL_OS_EMBEDDING_PROVIDER=ollama
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
```

Alternative local neural embeddings with Python models:

```bash
make install-rag
PERSONAL_OS_EMBEDDING_PROVIDER=sentence-transformers
PERSONAL_OS_SENTENCE_TRANSFORMERS_MODEL=BAAI/bge-small-en-v1.5
```

Recommended local vector store:

```bash
PERSONAL_OS_VECTOR_BACKEND=chroma
PERSONAL_OS_CHROMA_DIR=./data/chroma
```

Note: this machine is using Python 3.14. Chroma and `sentence-transformers` may fail to install here because `onnxruntime` and `torch` do not publish compatible wheels for this runtime yet. For this machine, the practical local setup is SQLite vector storage plus Ollama neural embeddings. For Chroma/Python embedding models, create a Python 3.12 virtual environment first.

## Document Upload Capabilities

The backend exposes readiness in:

```text
GET /api/status
```

Look at `document_ingestion` for supported file types, OCR readiness, and missing packages.

Supported extraction paths:

- PDF text and tables with `pdfplumber`
- PDF fallback with `PyMuPDF`
- scanned PDF/image OCR with `pytesseract` + system `tesseract`
- DOCX paragraphs and tables
- XLSX sheets as markdown tables
- PPTX slide text and tables
- CSV/JSON/HTML/TXT/MD

## Verify

```bash
make test
make typecheck
make eval
```
