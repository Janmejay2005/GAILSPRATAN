# GAILSPARTAN local setup and testing

This guide describes the API-free development build. It uses Flask, SQLite,
`pdfminer.six`, and deterministic standard-library retrieval. It does not call
an external AI, web-search, email, or hosted authentication provider.

## 1. Install dependencies

From the repository root:

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# Windows cmd: .venv\Scripts\activate.bat
# macOS/Linux: source .venv/bin/activate
python -m pip install -r GAILSPARTAN/backend/requirements.txt
python -m pip install -r GAILSPARTAN/frontend/requirements.txt
python -m pip install pytest
```

## 2. Run the Flask application

Run from the repository root:

```bash
python GAILSPARTAN/backend/app.py
```

Open `http://127.0.0.1:5000`, create an account, upload a public sample PDF or
UTF-8 TXT file, and ask a question. The default development database is a
local SQLite file named `chatbot.sqlite3`; it is ignored by Git.

## 3. Run the optional Streamlit client

Keep Flask running and start a second terminal:

```bash
streamlit run GAILSPARTAN/frontend/chatbot_ui.py
```

To point the client at another local Flask address:

```bash
# PowerShell
$env:GAILSPARTAN_BACKEND_URL = "http://127.0.0.1:5000"
# cmd
set GAILSPARTAN_BACKEND_URL=http://127.0.0.1:5000
```

## 4. Run automated tests

```bash
python -m pytest -q GAILSPARTAN/backend/tests
python -m compileall -q GAILSPARTAN/backend GAILSPARTAN/frontend scripts
```

The tests cover registration, login, protected routes, local PDF/TXT ingestion,
user isolation, chunk retrieval, grounded citations, unsupported questions,
conflict/grounding metadata, feedback, escalation, role protection, audit
records, and admin aggregate metrics.

## 5. Run the deterministic evaluation

```bash
python scripts/evaluate_local.py
python scripts/evaluate_local.py --concurrency 5 --requests-per-user 2
python scripts/evaluate_local.py --json > evaluation-output.json
```

The evaluation uses only the versioned synthetic dataset at
`evaluation/public_demo_dataset.json`. It reports retrieval hit rate, citation
source hit rate, answer keyword hit rate, abstention accuracy, and p50/p95
latency. The optional benchmark creates five isolated local users and checks
that concurrent retrieval requests complete without errors.

## 6. API smoke checks

With Flask running, these public checks should work:

```bash
curl http://127.0.0.1:5000/health
```

Expected characteristics:

- `retrieval` is `local-tfidf`.
- `external_providers` is `disabled`.
- `/search`, `/openai`, and `/gemini` are not registered.
- `/documents`, `/chat`, `/get_chat_history`, `/feedback`, `/escalations`,
  `/me`, and `/admin/metrics` require an authenticated session, except for
  `/health`.

## 7. Current limitations

The API-free build intentionally leaves several production concerns explicit:

- Email verification and genuine 2FA are not active because no email/auth
  service is configured.
- Indexing is synchronous in the Flask request; a worker queue is a later
  deployment improvement.
- PDF and UTF-8 TXT are supported; DOCX and OCR for scanned PDFs are not yet
  included.
- The local TF-IDF retriever is a transparent baseline, not an embedding model
  or a hosted generative model.
- SQLite is appropriate for the local demo, not a production multi-tenant
  deployment.
