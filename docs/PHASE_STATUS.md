# GAILSPARTAN phase status

This status records what the API-free implementation actually provides. A
phase is not marked complete merely because a route or button exists; it needs
an observable flow and a check.

## Phase 0 — Product and evaluation setup

**Status: implemented for the local demo.**

- Product and app-flow documents use the single product name `GAILSPARTAN`.
- A synthetic public-demo evaluation corpus is versioned in
  `evaluation/public_demo_dataset.json`.
- The local evaluator reports retrieval, citation, abstention, and latency
  metrics without external services.

## Phase 1 — UI prototype

**Status: implemented.**

- Responsive login, registration, chat, documents, history, help, and admin
  pages are available through Flask templates.
- Empty, loading, error, source, grounding, feedback, and follow-up states are
  represented in the UI.
- The optional Streamlit client uses only the local Flask server.

## Phase 2 — Backend and persistence

**Status: implemented for the local stack.**

- Flask application factory and SQLite persistence are in place.
- Password hashing, local sessions, protected routes, user-scoped documents,
  conversations, feedback, escalation records, and audit events are persisted.
- Roles are `employee`, `knowledge_admin`, and `system_admin`; public signup
  always creates an employee.

## Phase 3 — Document ingestion and RAG

**Status: implemented as a transparent local baseline.**

- PDF page extraction and UTF-8 TXT extraction preserve page metadata.
- Overlapping chunks are ranked with deterministic TF-IDF/cosine-style search.
- Answers are extractive and cite real chunk/document IDs.
- Unsupported and simple conflicting evidence states abstain safely.
- Summaries and keywords are deterministic extractive metadata.

## Phase 4 — Trust and governance

**Status: implemented for the local demo.**

- Document owner scoping is enforced on retrieval and document-specific Q&A.
- Documents expose category, version, access scope, verification status,
  review/effective dates, checksum, ingestion status, summary, and keywords.
- Admin review, role-protected metrics, feedback, demo escalation, audit events,
  and a lightweight input safety filter are available.
- The safety filter is not a replacement for authorization or malware scanning.

## Phase 5 — Quality and performance

**Status: baseline tooling implemented.**

- `scripts/evaluate_local.py` runs a fixed dataset and reports p50/p95 latency,
  retrieval/citation rates, answer keyword checks, and abstention accuracy.
- The same script can run a five-user concurrent local retrieval smoke test.
- Numeric quality targets are intentionally not claimed beyond the recorded
  run output; repeat the script after retrieval changes.

## Phase 6 — Deployment and portfolio release

**Status: local reproducible release materials implemented; hosted deployment remains open.**

- README, local setup, privacy/safety guidance, requirements, and test/eval
  commands are documented.
- The public-demo dataset is synthetic and should not be replaced with
  confidential organizational data.
- A production deployment, TLS, managed authentication, worker queue, and
  hosted database still require an explicit deployment decision.

## Phase 7 — Differentiating features

**Status: intentionally deferred.**

OCR, DOCX parsing, multilingual evaluation, connected drives/wiki/ticketing,
admin knowledge-gap analytics beyond the local metrics, and optional local
model integrations can build on this baseline later. They are not claimed as
complete in the API-free MVP.
