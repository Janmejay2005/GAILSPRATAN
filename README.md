# GAILSPARTAN

GAILSPARTAN is a local, source-grounded organizational knowledge assistant.
Users create a local account, upload text-based PDFs or UTF-8 TXT files, and
ask questions that are answered from indexed document passages. The current
implementation deliberately does **not** call external AI, web-search, email,
or hosted authentication APIs.

## Current flow

```text
Register → Sign in → Upload a document → Ask a question → Review sources → Give feedback or escalate
```

The retrieval pipeline is deterministic and local:

1. `pdfminer.six` extracts PDF text and page numbers; UTF-8 TXT is supported directly.
2. Text is normalized and split into overlapping chunks.
3. A standard-library TF-IDF/cosine-style scorer ranks relevant chunks.
4. The answer is assembled from matching source sentences.
5. If evidence is missing or conflicting, GAILSPARTAN abstains instead of inventing an answer.
6. Feedback, demo escalation, role checks, document governance, and privacy-conscious audit events are stored locally.

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
├── GAILSPARTAN_APP_FLOW.md        # Application flow
├── evaluation/public_demo_dataset.json # Synthetic evaluation corpus
├── scripts/evaluate_local.py       # Quality and five-user smoke benchmark
└── docs/                           # Setup, privacy, and phase status
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
python scripts/evaluate_local.py --concurrency 5 --requests-per-user 2
```

The tests cover PDF/TXT extraction, chunk overlap, grounded retrieval,
unsupported questions, citations, per-user document isolation, registration,
login, protected routes, document metadata and deletion, chat history,
feedback, escalation, moderation, role protection, audit records, health, and
aggregate admin metrics.

See [`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md) for the complete testing and
manual smoke-test process, [`docs/PHASE_STATUS.md`](docs/PHASE_STATUS.md) for
the phase-by-phase implementation status, and
[`docs/PRIVACY_NOTICE.md`](docs/PRIVACY_NOTICE.md) before uploading demo data.

## Important limitations

- The current MVP accepts text-based PDFs and UTF-8 TXT. Scanned image-only PDFs require OCR.
- Retrieval is local and extractive; there is no generative model provider.
- The default database is local SQLite for development.
- Email verification and genuine 2FA are not active because no email/auth service is configured.
- DOCX parsing, OCR, asynchronous workers, hosted deployment, and production multi-tenancy remain future work.
- Do not upload confidential, personal, regulated, or production organizational
  information to a public demo or development instance.
