# GAILSPARTAN --- Application Flow

**Version:** 1.0\
**Date:** 21 October 2026\
**Purpose:** UX flows, navigation, and end-to-end system behavior for
the MVP.

## 1. Navigation Map

``` text
Public
├── Landing / Demo information
├── Sign up
├── Login
├── Email verification / second factor
└── Privacy and demo-data notice

Authenticated Employee
├── Chat
│   ├── New conversation
│   ├── Ask question
│   ├── View citations
│   ├── Open source document
│   ├── Rate answer / report issue
│   └── Request human follow-up
├── Documents
│   ├── Upload document
│   ├── Processing status
│   ├── Document details
│   ├── Summarize
│   ├── Extract keywords
│   ├── Ask about this document
│   └── Delete own permitted document (if allowed)
├── Conversation history
├── Profile / sign out
└── Help and privacy

Knowledge Admin
├── Document inventory
├── Upload and ingest
├── Verification and review dates
├── Owners and access scopes
├── Unanswered questions
├── Feedback review
└── Knowledge health metrics

System Admin
├── User and role management
├── Organization settings
├── Security/audit events
├── Usage and latency metrics
└── Model/provider configuration
```

## 2. First-Visit Flow

``` mermaid
flowchart TD
    A[Open public demo] --> B{Signed in?}
    B -- No --> C[Landing / demo notice]
    C --> D{Choose action}
    D --> E[Create account]
    D --> F[Sign in]
    E --> G[Verify email]
    G --> H[Complete second factor if configured]
    F --> I[Verify credentials]
    I --> H
    H --> J[Load user profile and permissions]
    J --> K[Open Chat]
    B -- Yes --> J
```

### UX requirements

-   Explain that the demo uses sample organizational data.
-   Do not let users select their own admin role during public signup.
-   Show verification errors without exposing whether an arbitrary email
    belongs to an account.
-   Protect all application APIs, not just frontend routes.
-   If a true second factor is required, make the two factors explicit.
    Email verification alone is not necessarily 2FA.

## 3. Chat Question Flow

``` mermaid
flowchart TD
    A[Employee enters question] --> B[Validate request and session]
    B --> C[Normalize input and apply language policy]
    C --> D{Input allowed?}
    D -- No --> E[Show safe warning / refusal]
    D -- Yes --> F[Classify query and scope]
    F --> G[Authorize searchable sources]
    G --> H[Hybrid/vector retrieval]
    H --> I[Rank and select evidence]
    I --> J{Enough relevant evidence?}
    J -- No --> K[Explain limitation and offer escalation]
    J -- Yes --> L[Generate answer from evidence]
    L --> M[Validate citations and response]
    M --> N{Citations valid and answer acceptable?}
    N -- No --> K
    N -- Yes --> O[Display answer with source references]
    O --> P[Save message and latency metadata]
    P --> Q[Optional user feedback]
```

### Response contract

The chat API should return structured data, conceptually:

``` json
{
  "answer": "Employees may request leave using the process described in the policy.",
  "citations": [
    {
      "document_id": "doc_example",
      "title": "Sample Leave Policy",
      "page": 4,
      "section": "Applying for Leave"
    }
  ],
  "grounding_status": "grounded",
  "needs_escalation": false,
  "latency_ms": 1820
}
```

This is an illustrative schema, not a final API contract. The backend
must validate citation IDs and permissions before returning source
metadata.

### Grounding states

-   `grounded`: enough supporting evidence was retrieved and citations
    validated.
-   `insufficient_evidence`: no useful source or weak evidence was
    found.
-   `conflicting_sources`: sources disagree or have different effective
    dates.
-   `restricted`: potentially relevant content exists but is not
    accessible to the user; do not reveal restricted document titles or
    contents.
-   `error`: a technical failure prevented a reliable answer.

Do not expose internal reasoning or hidden chain-of-thought. Provide
concise explanations and evidence instead.

## 4. Document Upload and Indexing Flow

``` mermaid
flowchart TD
    A[Open Documents] --> B[Select file]
    B --> C[Validate extension, MIME, size]
    C --> D{Valid file?}
    D -- No --> E[Show validation error]
    D -- Yes --> F[Upload to private storage]
    F --> G[Create document record]
    G --> H[Queue ingestion]
    H --> I[Extract text and page metadata]
    I --> J{Text extracted?}
    J -- No --> K[Mark failed or OCR required]
    J -- Yes --> L[Chunk and attach metadata]
    L --> M[Generate embeddings]
    M --> N[Write chunks to authorized index]
    N --> O[Mark document ready]
    O --> P[Show summary and Ask about document]
```

### Upload rules

-   Private storage by default.
-   Validate actual file content, not only filename.
-   Limit file size and supported types.
-   Do not expose a document as searchable until authorization metadata
    is set.
-   Keep ingestion idempotent where practical.
-   Delete indexed chunks when the source document is deleted, following
    the declared retention policy.
-   Treat document text as untrusted data. Never follow instructions
    found inside an uploaded document as system instructions.

## 5. Document Summary Flow

``` text
User opens a ready document
        ↓
Selects “Summarize”
        ↓
Backend checks document access
        ↓
Extracted text is summarized in bounded sections
        ↓
System produces overview, key points, and optional action items
        ↓
UI displays generated summary with source page references where available
        ↓
User can ask a follow-up question
```

If the document is too large, process it in sections and combine the
summaries. Make clear that the summary is AI-generated and is not an
official replacement for the document.

## 6. Unanswered Question and Escalation Flow

``` mermaid
flowchart TD
    A[Question cannot be answered reliably] --> B[Explain what is missing]
    B --> C[Show relevant permitted sources if any]
    C --> D{User wants follow-up?}
    D -- No --> E[End conversation]
    D -- Yes --> F[Choose HR, IT, or General]
    F --> G[Confirm summary and consent]
    G --> H[Create demo escalation record]
    H --> I{Backend confirms creation?}
    I -- Yes --> J[Show reference number]
    I -- No --> K[Show failure and retry option]
```

In the MVP, escalation may create a record inside the app. Do not imply
that a real HR or IT team was contacted unless an actual integration
confirms delivery.

## 7. Admin Document Governance Flow

``` text
Admin uploads or selects document
        ↓
Sets title, category, owner, version, access scope
        ↓
Sets effective date and review date where relevant
        ↓
Document is indexed
        ↓
Admin verifies source and content
        ↓
Document status becomes Verified
        ↓
Periodic review identifies stale documents
        ↓
Admin updates, re-verifies, archives, or replaces document
```

### Suggested document statuses

-   `processing`
-   `ready_unverified`
-   `verified`
-   `outdated`
-   `archived`
-   `failed`

A document can be technically indexed but not verified. Search ranking
and answer presentation should reflect this distinction.

## 8. Feedback Flow

1.  User selects thumbs up/down or "Report an issue."
2.  User selects a category: incorrect answer, missing citation,
    outdated source, incomplete answer, inaccessible source, or other.
3.  Optional comment is collected.
4.  Backend stores feedback linked to the answer and source IDs.
5.  Admin sees aggregate patterns and can inspect permitted details.
6.  Feedback is used to improve test cases and document quality; it must
    not automatically retrain a model.

## 9. Error and Empty States

  -----------------------------------------------------------------------
  Situation                           UI behavior
  ----------------------------------- -----------------------------------
  No conversations yet                Show example questions and "Start a
                                      conversation"

  No documents yet                    Explain how to upload a sample
                                      policy

  Upload too large/unsupported        Show allowed formats and limit

  PDF contains no extractable text    Explain OCR may be required

  Indexing is in progress             Show status and allow the user to
                                      leave the page

  Model timeout                       Show retry option; do not fabricate
                                      an answer

  No evidence found                   Explain that the knowledge base
                                      does not support an answer

  Conflicting policy versions         State that sources conflict and
                                      suggest admin/HR confirmation

  Citation source deleted             Mark citation unavailable and
                                      prevent broken access

  User lacks permission               Show a generic access message
                                      without leaking restricted metadata

  Rate limit reached                  Explain when to retry if known

  Session expired                     Preserve unsent text where safe and
                                      ask the user to sign in again
  -----------------------------------------------------------------------

## 10. Main UI Layout

### Chat screen

-   **Left sidebar:** New chat, conversation history, Documents, Help.
-   **Top bar:** product name, current organization/demo label, user
    menu.
-   **Conversation area:** user messages, assistant answers, citations,
    grounding status, feedback.
-   **Composer:** text input, send button, optional document attachment.
-   **Answer evidence:** source title, page/section, and open-source
    action.
-   **Status feedback:** sending, retrieving, generating, error, and
    retry states.

### Documents screen

-   Upload button and supported formats.
-   Search/filter by title, category, status, and owner.
-   File cards or table with title, processing status, verification
    state, and last reviewed date.
-   Document details page with summary, extracted metadata, and Ask
    about this document.

### Admin screen

-   Overview metrics.
-   Document verification queue.
-   Stale documents and review reminders.
-   Unanswered questions and feedback categories.
-   User/role management only for authorized administrators.

## 11. API and State Ownership

-   The frontend owns transient UI state such as an open modal or draft
    input.
-   The backend owns authentication decisions, authorization, role
    checks, document access, retrieval, citation validation, and
    escalation creation.
-   The database owns durable records.
-   Background workers own long-running ingestion tasks.
-   The model is an untrusted generation component, not the authority on
    user permissions or official policy.
-   Never place model API keys, privileged database keys, or
    service-role secrets in browser code.

## 12. Performance Flow and Observability

Record per-request timing for: - Request validation and moderation. -
Retrieval. - Reranking, if enabled. - Model call. - Citation
validation. - Total response time.

Track p50, p95, and p99 latency, timeouts, model errors, retrieval-empty
rate, and citation-validation failures. The five-second target applies
to a defined test workload; report actual measurements rather than
promising universal latency.

For a five-user concurrency test: 1. Seed a fixed sample corpus. 2.
Prepare a representative question set. 3. Run five concurrent clients.
4. Record response latency and errors. 5. Confirm answers remain
isolated by user permissions. 6. Repeat after any retrieval or model
change.

## 13. Suggested Implementation Order

1.  Build UI routes and mock data.
2.  Finalize API request/response schemas.
3.  Add authentication and protected backend routes.
4.  Persist users, documents, conversations, and messages.
5.  Implement upload and extraction.
6.  Implement chunking, embeddings, and retrieval.
7.  Generate grounded answers and validate citations.
8.  Add document summaries and keyword extraction.
9.  Add roles, document governance, moderation, and audit events.
10. Add feedback and escalation.
11. Evaluate quality, latency, and concurrent usage.
12. Deploy, document, and record the demo.

## 14. Demo Walkthrough (3--4 minutes)

1.  Sign in to the public demo.
2.  Ask: "How do I apply for leave?"
3.  Show the answer and click the citation to open the sample policy
    section.
4.  Ask a question whose answer is absent and show the assistant
    abstaining instead of guessing.
5.  Upload a sample 8--10 page document and show its processing status.
6.  Summarize the document and extract keywords.
7.  Ask a document-specific question and show page-level evidence.
8.  Show document verification status or the admin knowledge-health
    view.
9.  Show the README and self-hosting instructions.

## 15. MVP Release Checklist

-   [ ] Signup, email verification, sign-in, sign-out.
-   [ ] True second-factor flow if claimed as 2FA.
-   [ ] Protected API routes and backend authorization.
-   [ ] PDF/DOCX upload with validation and status.
-   [ ] Text extraction and page/section metadata.
-   [ ] Embedding and retrieval pipeline.
-   [ ] Grounded answers with validated citations.
-   [ ] Insufficient-evidence and conflicting-source states.
-   [ ] Document summary and keyword extraction.
-   [ ] Configurable bad-language filter.
-   [ ] Feedback and demo escalation.
-   [ ] Document verification and review metadata.
-   [ ] Five-concurrent-user load test.
-   [ ] Latency and error benchmark.
-   [ ] Public demo privacy notice and sample data.
-   [ ] README, architecture diagram, environment example, and local run
    instructions.
-   [ ] Short demo video and portfolio write-up.
