# GAILSPARTAN --- Product Requirements Document

**Version:** 1.0\
**Date:** 21 October 2026\
**Status:** Proposed MVP\
**Product type:** Web-based AI knowledge assistant\
**Product name:** GAILSPARTAN

## 1. Executive Summary

GAILSPARTAN is a secure, source-grounded employee knowledge assistant
that helps people find organizational information, understand documents,
and resolve routine HR and IT questions through natural-language
conversation.

The first release will use publicly available sample policies and
support guides, not real confidential company data. Users can ask
questions, upload supported documents, receive summaries and keyword
extraction, and inspect the evidence behind answers. Administrators can
manage the knowledge base and review unanswered or low-confidence
questions.

The product is inspired by the SIH/GAIL problem statement, but its scope
is updated for a modern AI knowledge product: reliable retrieval,
permission-aware access, knowledge freshness, explicit uncertainty, safe
escalation, and measurable evaluation.

## 2. Product Vision

**Make organizational knowledge easy to find, safe to use, and simple to
verify.**

### Product promise

Employees should not need to search through multiple PDFs or wait for a
colleague to answer a routine question. They should be able to ask in
plain language, receive a concise answer grounded in approved sources,
and open those sources to verify the answer.

### Product category

AI-powered organizational knowledge and employee support assistant.

### What the product is not

-   Not a generic ChatGPT clone.
-   Not an autonomous HR decision-maker.
-   Not a replacement for HR, IT, legal, or other accountable teams.
-   Not a full enterprise search platform with dozens of integrations in
    the first release.
-   Not a system that should invent policy answers when evidence is
    missing.

## 3. Problem Statement

Organizational knowledge is often distributed across policy PDFs,
circulars, SOPs, help guides, and internal pages. Employees struggle to
locate the right version, interpret long documents, and identify the
correct team for help. HR and IT teams repeatedly answer similar
questions.

This creates: - Time wasted searching and asking around. - Repetitive
support workload. - Inconsistent answers across employees. - Risk of
using outdated or unofficial documents. - Poor visibility into missing
or confusing documentation.

## 4. Target Users and Personas

### Employee

Needs quick answers to HR, IT, events, and process questions. Wants
understandable answers with source links.

### HR or IT support member

Needs to reduce repetitive queries and route unresolved questions to the
right team.

### Knowledge administrator

Uploads and organizes documents, assigns owners, marks authoritative
sources, and reviews stale or missing knowledge.

### Organization administrator

Manages users, roles, security settings, and audit records.

For the public portfolio demo, all roles and data are simulated or based
on public sample documents. Users must not upload confidential,
personal, or regulated information.

## 5. Product Goals

1.  Answer common employee questions from a curated knowledge base.
2.  Provide traceable source citations for factual policy answers.
3.  Support document upload, text extraction, summarization, and keyword
    extraction.
4.  Respect user and document access rules.
5.  Admit when evidence is insufficient and offer a useful next step.
6.  Demonstrate secure email verification, including a second factor
    where configured.
7.  Support at least five concurrent test users in a repeatable load
    test.
8.  Publish a usable web demo and a reproducible self-hosting guide.
9.  Measure answer quality, latency, retrieval quality, and failure
    rates rather than relying on subjective impressions.

## 6. Non-Goals for MVP

-   Production deployment inside a real public-sector organization.
-   Integration with confidential HRIS, payroll, Active Directory, or
    ticketing systems.
-   Automatic approval of leave, reimbursements, hiring, or other
    consequential decisions.
-   Broad enterprise connectors for SharePoint, Slack, Teams, Google
    Drive, Jira, and email.
-   Fine-tuning a foundation model.
-   Native mobile applications.
-   Voice calling or always-on agents.
-   Guaranteed sub-five-second responses for every query and every
    provider. The target will be measured under a defined test
    environment; external model, network, and cold-start latency can
    exceed it.

## 7. Core Product Experience

### Main navigation

-   Chat
-   Documents
-   History
-   Feedback
-   Admin area, visible only to authorized administrators

### Main chat experience

-   Ask an HR, IT, policy, event, or process question.
-   Receive a concise response with citations.
-   Open the cited document and relevant page/section.
-   See an uncertainty message if evidence is weak or conflicting.
-   Give thumbs-up/down feedback and optionally report an incorrect
    answer.
-   Create an escalation request when the answer cannot resolve the
    issue.

### Document workspace

-   Upload a supported file.
-   View processing state: queued, extracting, indexing, ready, or
    failed.
-   See file metadata and extraction errors.
-   Summarize the document.
-   Extract keywords, dates, named entities, and action items where
    supported.
-   Ask questions scoped to the selected document.
-   Delete a document and its indexed chunks, subject to retention and
    audit policy.

## 8. Functional Requirements

### FR-01: Authentication and account lifecycle

-   Users can create an account and sign in.
-   Verify control of the email address before enabling the account.
-   Implement email OTP or magic-link verification and a genuine
    second-factor flow if the security requirement calls for two-factor
    authentication.
-   Email verification alone is not necessarily two-factor
    authentication. A true 2FA flow requires two distinct factors, such
    as a password plus email OTP, or a password plus TOTP.
-   Use a managed auth provider where possible; never build OTP
    cryptography or password storage from scratch.
-   Provide logout, session expiry, and protected routes.
-   Never allow public self-signup to grant administrator privileges.

### FR-02: Roles and access control

MVP roles: - Employee: ask questions and access permitted documents. -
Knowledge Admin: manage documents and knowledge metadata. - System
Admin: manage users, configuration, and audit events.

Enforce permissions on the backend for every request and retrieval
operation. UI hiding is not authorization. In future multi-tenant
deployment, every record and query must be scoped to the correct
organization.

### FR-03: Knowledge ingestion

-   Accept PDF and DOCX initially; TXT can be included as a
    low-complexity format.
-   Enforce file size, MIME/type, and extension limits.
-   Reject encrypted, malformed, or unsupported files with a clear
    message.
-   Extract text and preserve page or section metadata where possible.
-   Chunk text with overlap and retain document ID, title, page/section,
    version, owner, access scope, and ingestion timestamp.
-   Create embeddings and index chunks.
-   Make indexing asynchronous so a large file does not block the web
    request.
-   Show processing status and allow retry after recoverable failures.
-   Prevent duplicate ingestion where practical using file hashes.

### FR-04: Retrieval-augmented generation (RAG)

-   Classify whether the query needs organizational retrieval,
    document-specific analysis, or a general clarification.
-   Retrieve only content the current user is authorized to access.
-   Use keyword plus vector retrieval when practical; add reranking only
    after a baseline evaluation demonstrates value.
-   Supply retrieved evidence to the model as untrusted reference
    material, not instructions.
-   Ask the model to answer only from supplied evidence for policy
    questions.
-   Return citations tied to retrieved chunk IDs and source metadata.
-   Validate that every citation maps to a real retrieved source.
-   If evidence is absent, weak, or contradictory, do not fabricate a
    policy answer. Explain the limitation and suggest escalation.

### FR-05: Chat and conversation history

-   Support multi-turn conversation.
-   Store conversation metadata and messages for authenticated users.
-   Keep document context and organization context separate.
-   Provide a new-chat action and conversation history.
-   Allow users to delete their own conversation history subject to the
    declared retention policy.
-   Do not treat chat history as authoritative organizational knowledge
    by default.

### FR-06: Document intelligence

For a selected document: - Generate a concise summary. - Extract
keywords and key entities. - Answer questions using the selected
document. - Include page/section citations where available. - State when
the requested detail does not appear in the document. - Label
AI-generated summaries as generated content, not official policy.

### FR-07: Unsafe-language filtering

-   Maintain a configurable dictionary for abusive terms and
    policy-defined prohibited language.
-   Normalize case and common obfuscation patterns before checking.
-   Use context-sensitive handling where possible to avoid flagging
    legitimate quotations or educational discussion.
-   Choose a defined response: warn, redact, or refuse abusive content
    according to policy.
-   Do not treat profanity filtering as the primary security control; it
    does not prevent prompt injection, data leakage, or authorization
    failures.
-   Log moderation outcomes with minimal necessary data.

### FR-08: Feedback and escalation

-   Let users rate an answer and report missing, incorrect, outdated, or
    inaccessible information.
-   If no reliable answer is found, show relevant sources if available
    and offer escalation.
-   MVP escalation may create an internal demo ticket with category,
    summary, user consent, and conversation reference.
-   Do not claim a ticket was created unless the backend confirms it.
-   Real ticketing integration is a later phase.

### FR-09: Knowledge governance

Each document should support: - Title, category, owner, version, source,
upload date, review date, and access scope. - Status: draft/unverified,
verified, outdated, archived, or failed. - Optional effective date and
expiry/review date. - Admin review workflow. - A visible warning when an
answer relies on an unverified or stale document. - Searchable document
inventory.

### FR-10: Admin insights

MVP dashboard: - Number of active documents and ingestion failures. -
Most frequent question categories. - Unanswered and low-confidence
questions. - User feedback and reported answer issues. - Latency and
error rate summaries. - Document review dates and stale-document alerts.

Use aggregate analytics and avoid exposing private chat contents to
admins unless explicitly required and disclosed.

## 9. Non-Functional Requirements

### Performance

-   Initial target: p95 response time below 5 seconds for a defined,
    warmed-up test workload of short questions and a small indexed
    corpus.
-   Report retrieval latency, model latency, total latency, p50/p95/p99,
    timeouts, and error rate separately.
-   Document upload and indexing are asynchronous and excluded from the
    chat latency target.
-   Do not claim the five-second target is guaranteed until measured on
    the deployed environment.

### Concurrency

-   Demonstrate at least five simultaneous users through a load test.
-   Avoid in-memory-only session state.
-   Use async I/O for network-bound operations.
-   Apply request limits, timeouts, and bounded concurrency to protect
    the model provider.

### Reliability

-   Gracefully handle model-provider outages, timeouts, failed document
    parsing, and empty retrieval.
-   Use retries only for transient failures and avoid retry storms.
-   Return a clear error state rather than a fabricated answer.

### Security and privacy

-   Enforce authorization on the backend and in retrieval.
-   Keep secrets in environment variables or a secrets manager.
-   Validate file type and size; scan uploaded files where deployment
    supports it.
-   Treat document contents as untrusted input. Defend against indirect
    prompt injection.
-   Prevent one user's or tenant's documents from appearing in another
    user's retrieval results.
-   Use TLS in deployment and secure session handling.
-   Minimize retained personal data and publish a demo privacy notice.
-   Keep audit records for authentication, document administration,
    permission changes, and escalation events.
-   Do not place private document text, OTPs, access tokens, or secrets
    in logs.
-   Use public sample data for the public demo.

### Accessibility and usability

-   Responsive layout for desktop and mobile browsers.
-   Keyboard-accessible controls, visible focus states, adequate
    contrast, and meaningful error messages.
-   Loading, empty, success, and failure states for all long-running
    operations.

### Maintainability

-   Typed request/response schemas.
-   Unit tests for parsing, permissions, filtering, retrieval, and
    citation mapping.
-   Integration tests for upload-to-answer flow.
-   A versioned evaluation dataset and documented deployment process.

## 10. Product Architecture (proposed)

### Frontend

-   React + TypeScript + Vite
-   Tailwind CSS
-   React Router
-   Fetch or Axios client with centralized error handling

### Backend

-   Python + FastAPI
-   Pydantic schemas
-   Async endpoints for model and database I/O
-   Background task queue for document ingestion when needed

### Persistence

-   PostgreSQL for users/organization metadata, documents,
    conversations, feedback, and audit records.
-   Supabase can provide managed PostgreSQL, storage, and authentication
    for a prototype.
-   Use pgvector or a separate vector store for embeddings. Start with
    pgvector if operational simplicity matters.

### Document processing

-   PyMuPDF for PDF text extraction.
-   python-docx for DOCX extraction.
-   A parser abstraction so OCR can be added for scanned PDFs later.
-   OCR is a later enhancement; text extraction from scanned image-only
    PDFs must report that OCR is needed.

### Retrieval and orchestration

-   Start with direct, explicit retrieval code or a lightweight
    orchestration framework.
-   Use hybrid search if available.
-   Add a reranker only after evaluation.
-   Keep model provider, embedding model, chunking, and retrieval
    settings configurable.

### Models

-   Use a low-latency hosted model API for the first working version if
    budget and data policy permit.
-   Keep the model interface provider-agnostic.
-   Use a small embedding model such as `BAAI/bge-small-en-v1.5` or
    `sentence-transformers/all-MiniLM-L6-v2` as a benchmark baseline.
-   Evaluate models on a fixed test set before selecting a default.
-   Local inference with Ollama is useful for development/privacy
    experiments but depends on available hardware and may not meet
    latency targets on a CPU-only machine.
-   Do not fine-tune a model for the MVP; retrieval and evaluation are
    the priority.

### Authentication

-   Prefer a managed auth provider supporting email verification,
    sessions, and a real second-factor method.
-   Verify exact provider support for the chosen OTP method before
    implementation.
-   If the original requirement specifically means email OTP after
    login, document that flow accurately and distinguish email
    verification from true 2FA.

### Deployment

-   Frontend: a static frontend host.
-   Backend: a managed Python host or low-cost VPS with Docker.
-   Database and storage: managed service for the first public demo, or
    self-hosted components for a reproducible local deployment.
-   Provide Docker Compose for local/self-hosted setup once the app is
    stable.

## 11. Suggested Data Model

-   `organizations`: id, name, slug, created_at
-   `users`: id, organization_id, email, display_name, role, status,
    created_at
-   `documents`: id, organization_id, title, file_key, mime_type,
    checksum, owner_id, access_scope, verification_status, version,
    effective_at, review_at, ingestion_status, created_at
-   `document_chunks`: id, document_id, organization_id, chunk_index,
    text, page_number, section_title, embedding, metadata
-   `conversations`: id, organization_id, user_id, title, created_at,
    updated_at
-   `messages`: id, conversation_id, role, content, citations_json,
    latency_ms, model_id, created_at
-   `feedback`: id, message_id, user_id, rating, category, comment,
    created_at
-   `escalations`: id, organization_id, user_id, category, summary,
    status, conversation_id, created_at
-   `audit_events`: id, organization_id, actor_id, event_type,
    resource_type, resource_id, metadata_json, created_at

Apply organization scoping and database constraints consistently. Never
rely on a client-provided organization ID without verifying membership.

## 12. API Surface (initial proposal)

-   `POST /auth/...`: provider-managed auth flow; avoid reimplementing
    token issuance.
-   `GET /me`: current authenticated user and permitted role.
-   `POST /documents`: validate and register upload.
-   `GET /documents`: list documents visible to current user.
-   `GET /documents/{id}`: metadata and status, with authorization.
-   `DELETE /documents/{id}`: authorized deletion.
-   `POST /documents/{id}/summarize`: summarize a selected document.
-   `POST /chat`: submit a question and receive answer, citations,
    confidence/grounding status, and latency metadata.
-   `GET /conversations`: list current user's conversations.
-   `GET /conversations/{id}`: read an authorized conversation.
-   `POST /feedback`: submit feedback.
-   `POST /escalations`: request human follow-up.
-   `GET /admin/metrics`: admin-only aggregate metrics.
-   `GET /health`: non-sensitive health status.

The exact routes and schemas should be frozen before frontend/backend
integration.

## 13. Success Metrics and Acceptance Criteria

### MVP acceptance

-   A new user can register, verify their email, sign in, and sign out.
-   Unauthorized users cannot access the app's protected APIs.
-   A user can upload a supported PDF or DOCX and see ingestion status.
-   The system can summarize the file and answer questions from its
    content.
-   A grounded answer displays at least one valid source citation when
    evidence exists.
-   Unsupported questions produce an uncertainty response rather than
    invented policy.
-   A user cannot retrieve a document outside their access scope.
-   The profanity filter handles configured test cases.
-   A repeatable load test demonstrates five concurrent users.
-   A benchmark report records p50/p95/p99 latency and error rates.
-   A clean setup guide allows another developer to run the project.
-   Public demo uses sample data and includes privacy/safety notices.

### Quality metrics to track

-   Retrieval hit rate on labeled questions.
-   Citation correctness.
-   Answer faithfulness to retrieved evidence.
-   Answer completeness and usefulness.
-   Abstention correctness when evidence is missing.
-   p50/p95/p99 response latency.
-   Upload and ingestion failure rates.
-   Feedback rate and negative-feedback categories.

Set numeric quality targets only after building a baseline evaluation
set; do not invent a high accuracy percentage without measurement.

## 14. Roadmap and Phases

### Phase 0 --- Product and evaluation setup

-   Finalize scope, personas, and user stories.
-   Create a small public sample corpus: HR policy, IT guide, leave
    policy, travel/reimbursement policy, events circular.
-   Create 30--50 representative test questions with expected source
    sections.
-   Define privacy, access, and citation rules.
-   Draw architecture and API contracts.

**Exit criteria:** scope is frozen and test data exists.

### Phase 1 --- UI prototype

-   Build login, signup, and main application routes.
-   Create responsive chat layout.
-   Create document library/upload panel.
-   Add loading, empty, error, and citation states.
-   Use mock responses only temporarily.

**Exit criteria:** all core screens are navigable and usable.

### Phase 2 --- Backend and persistence

-   Set up FastAPI and typed schemas.
-   Configure database and migrations.
-   Add authentication integration and protected endpoints.
-   Implement document metadata and conversation persistence.

**Exit criteria:** frontend can call the backend and store user-scoped
data.

### Phase 3 --- Document ingestion and RAG

-   Extract PDF/DOCX text.
-   Chunk text and retain page/section metadata.
-   Generate embeddings and index chunks.
-   Implement retrieval, answer generation, citation mapping, and
    abstention.
-   Add document-scoped summarization and keyword extraction.

**Exit criteria:** end-to-end document questions return traceable
evidence.

### Phase 4 --- Trust and governance

-   Implement roles and document access scopes.
-   Add verification status, owner, review date, and stale-document
    warning.
-   Add unsafe-language filter and prompt-injection tests.
-   Add feedback and escalation.
-   Add audit events.

**Exit criteria:** security and trust tests pass.

### Phase 5 --- Quality and performance

-   Build a repeatable evaluation script.
-   Test retrieval and citation correctness.
-   Test five concurrent users.
-   Measure latency and fix bottlenecks.
-   Add rate limits, timeouts, bounded concurrency, and cost controls.

**Exit criteria:** a documented benchmark report exists and known
limitations are disclosed.

### Phase 6 --- Deployment and portfolio release

-   Deploy frontend and backend.
-   Configure secrets and production environment variables.
-   Add sample/demo tenant and sample documents.
-   Write README, architecture diagram, setup guide, and demo script.
-   Record a short walkthrough.
-   Publish a LinkedIn launch post.

**Exit criteria:** recruiter can open the demo or run it locally from
the repository.

### Phase 7 --- Differentiating features

-   OCR for scanned PDFs.
-   Hindi and multilingual retrieval evaluation.
-   Search across connected drives/wiki/ticket systems.
-   Admin knowledge-gap analytics.
-   Ticketing integration.
-   Optional browser extension or Slack/Teams integration.
-   Optional local-model mode and tenant self-hosting.

## 15. Key Risks and Mitigations

  -----------------------------------------------------------------------
  Risk                                Mitigation
  ----------------------------------- -----------------------------------
  Hallucinated policy answer          Grounded prompt, citation
                                      validation, abstention, test set

  Data leakage between users          Backend authorization, filtered
                                      retrieval, tenant-scoped tests

  Prompt injection in uploaded        Treat retrieved text as untrusted;
  documents                           no tool permissions derived from
                                      document text

  Stale policies                      Verification status, owner, review
                                      date, warning

  Slow model response                 Measure stages, use low-latency
                                      model, reduce context, bounded
                                      concurrency

  Model API cost                      Token limits, rate limits, caching
                                      for safe repeat queries, usage
                                      tracking

  Scope creep                         Finish one end-to-end path before
                                      integrations and advanced agents

  Misleading security claims          Separate email verification from
                                      true 2FA; document actual controls

  Public demo misuse                  Use public sample documents; limit
                                      upload size and request rate
  -----------------------------------------------------------------------

## 16. Definition of Done

A feature is done when: 1. The happy path works. 2. Empty, invalid,
unauthorized, and failed states are handled. 3. Relevant
unit/integration tests pass. 4. Access control is enforced server-side.
5. The UI gives clear feedback. 6. README/configuration are updated. 7.
The change is committed and can be demonstrated.

## 17. Product Pitch

**GAILSPARTAN turns scattered organizational documents into a secure,
conversational knowledge experience. Employees get answers grounded in
approved sources, while support teams gain visibility into unanswered
questions and outdated knowledge.**

## 18. Research Notes

The product direction is informed by public product documentation
reviewed on 21 October 2026:

-   Glean: company knowledge, permission-aware results, and cited
    answers.
-   Microsoft 365 Copilot/SharePoint agents: answers constrained by
    source permissions.
-   Guru: verified knowledge, source lineage, and governance.
-   Atlassian Rovo: enterprise search and configurable agents that help
    move work forward.
-   Slite: cited workspace answers and knowledge verification.
-   AnythingLLM: local/self-hosted document chat, multiple model
    providers, and multi-user deployment.
-   Dify: open-source AI application workflows and RAG tooling.
-   OWASP GenAI Security Project: prompt injection,
    sensitive-information disclosure, insecure output handling,
    excessive agency, and related risks.

These products establish category expectations, not a guarantee that
GAILSPARTAN can match their enterprise capabilities. The MVP
differentiator is a focused, transparent, testable implementation with a
reproducible demo.
