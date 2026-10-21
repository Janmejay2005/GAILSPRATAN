# GAILSPARTAN demo privacy and safety notice

GAILSPARTAN is currently a local development and portfolio demo. Use only
synthetic or public sample documents. Do not upload confidential company data,
personal information, credentials, regulated records, or production HR/IT
material.

The local build stores account records, hashed passwords, indexed text chunks,
document metadata, conversation history, feedback, escalation records, and
privacy-conscious audit metadata in SQLite. Audit events intentionally omit
document text, chat messages, responses, comments, and prompts.

The retriever treats document text as untrusted reference material and does not
execute instructions found inside a document. The input filter catches a small
set of obvious abusive or prompt-injection-like phrases; it is not a complete
content moderation or security boundary.

Answers are not official HR, legal, security, or IT decisions. Check the cited
source and contact the accountable team when GAILSPARTAN abstains, reports
conflicting sources, or cannot resolve the question.
