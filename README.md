# GAILSPARTAN

GAILSPARTAN is a local, source-grounded document assistant. Users create a
local account, upload text-based PDFs, and ask questions that are answered
from the indexed document passages. The current implementation deliberately
does **not** call OpenAI, Gemini, SerpAPI, email services, or any other
external AI/search API.

## Current flow

```text
Register → Sign in → Upload a PDF → Ask a question → See answer and sources
```

The retrieval pipeline is deterministic and local:

1. `pdfminer.six` extracts text and page numbers.
2. Text is normalized and split into overlapping chunks.
3. A standard-library TF-IDF/cosine-style scorer ranks relevant chunks.
4. The answer is assembled from matching source sentences.
5. If evidence is missing, GAILSPARTAN abstains instead of inventing an answer.

## Project layout

```text
GAILSPRATAN/
├── GAILSPARTAN/
│   ├── backend/
│   │   ├── app.py                 # Flask application and routes
│   │   ├── models.py              # Users, documents, chunks, history
│   │   ├── rag.py                 # Local PDF retrieval pipeline
│   │   ├── requirements.txt       # Flask backend dependencies
│   │   └── tests/                 # Backend tests
│   ├── frontend/
│   │   ├── chatbot_ui.py          # Optional Streamlit client
│   │   └── requirements.txt       # Streamlit client dependencies
│   ├── templates/                 # Flask pages
│   └── static/style.css           # Responsive UI styling
├── GAILSPARTAN_PRD.md             # Product requirements
└── GAILSPARTAN_APP_FLOW.md        # Application flow
```

## Local setup

From the repository root:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

python -m pip install -r GAILSPARTAN/backend/requirements.txt
```

Run the Flask application:

```bash
python -m backend.app
```

The command must be run from inside `GAILSPARTAN/`, or use the direct script
form from the repository root:

```bash
python GAILSPARTAN/backend/app.py
```

Open `http://127.0.0.1:5000` in a browser.

### Optional Streamlit client

In a second terminal:

```bash
python -m pip install -r GAILSPARTAN/frontend/requirements.txt
streamlit run GAILSPARTAN/frontend/chatbot_ui.py
```

The Streamlit client communicates only with the local Flask server. To use a
different local Flask address, set `GAILSPARTAN_BACKEND_URL` before launching
it.

## Tests

Run the backend test suite from the repository root:

```bash
python -m pytest -q GAILSPARTAN/backend/tests
python -m compileall -q GAILSPARTAN/backend GAILSPARTAN/frontend
```

The tests cover PDF extraction, chunk overlap, grounded retrieval, unsupported
questions, per-user document isolation, registration, login, protected routes,
PDF upload, chat history, and removal of the old provider endpoints.

## Important limitations

- The current MVP accepts text-based PDFs. Scanned image-only PDFs require OCR.
- Retrieval is local and extractive; there is no generative model provider.
- The default database is local SQLite for development.
- Do not upload confidential, personal, regulated, or production organizational
  information to a public demo or development instance.
