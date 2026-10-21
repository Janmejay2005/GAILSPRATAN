"""Database models for the local GAILSPARTAN application.

The application intentionally keeps the schema small and SQLite-friendly.  New
governance and feedback fields have defaults so fresh test databases and the
original document/chat flow continue to work without a migration step.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy.orm import synonym

try:
    from .extensions import db
except ImportError:  # pragma: no cover - direct script execution support.
    from extensions import db


class User(db.Model):
    """A local user account."""

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    role = db.Column(
        db.String(32),
        nullable=False,
        default="employee",
        server_default="employee",
        index=True,
    )

    documents = db.relationship(
        "Document",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy=True,
    )
    chat_history = db.relationship(
        "ChatHistory",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy=True,
    )


class Document(db.Model):
    """A locally indexed document and its governance metadata."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename = db.Column(db.String(255), nullable=False)
    # ``user_id`` is the original ownership field.  ``owner_id`` is exposed as
    # a synonym so callers can use the governance vocabulary without creating
    # a second, potentially inconsistent foreign key.
    owner_id = synonym("user_id")
    title = db.Column(db.String(255), nullable=True)
    category = db.Column(
        db.String(80),
        nullable=False,
        default="general",
        server_default="general",
    )
    version = db.Column(
        db.String(64),
        nullable=False,
        default="1.0",
        server_default="1.0",
    )
    access_scope = db.Column(
        db.String(32),
        nullable=False,
        default="private",
        server_default="private",
    )
    verification_status = db.Column(
        db.String(32),
        nullable=False,
        default="unverified",
        server_default="unverified",
    )
    effective_date = db.Column(db.DateTime, nullable=True)
    review_date = db.Column(db.DateTime, nullable=True)
    # Aliases used by the PRD/API vocabulary in earlier design notes.
    effective_at = synonym("effective_date")
    review_at = synonym("review_date")
    ingestion_status = db.Column(
        db.String(32),
        nullable=False,
        default="ready",
        server_default="ready",
    )
    checksum = db.Column(db.String(64), nullable=True, index=True)
    summary = db.Column(db.Text, nullable=True)
    # Stored as JSON text rather than a database-specific JSON type so the
    # model remains compatible with SQLite and the existing dependency set.
    keywords = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )

    user = db.relationship("User", back_populates="documents")
    chunks = db.relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentChunk.chunk_index",
        lazy=True,
    )


class DocumentChunk(db.Model):
    """A normalized, overlapping text chunk from an indexed PDF page."""

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(
        db.Integer,
        db.ForeignKey("document.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_number = db.Column(db.Integer, nullable=True)
    chunk_index = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=False)

    document = db.relationship("Document", back_populates="chunks")

    __table_args__ = (
        db.UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_document_chunk_index",
        ),
    )


class ChatHistory(db.Model):
    """A question and grounded response belonging to one user."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message = db.Column(db.Text, nullable=False)
    response = db.Column(db.Text, nullable=False)
    document_id = db.Column(
        db.Integer,
        db.ForeignKey("document.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    grounding_status = db.Column(
        db.String(40),
        nullable=False,
        default="insufficient_evidence",
        server_default="insufficient_evidence",
    )
    needs_escalation = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    latency_ms = db.Column(
        db.Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    citations = db.Column(db.Text, nullable=True)
    timestamp = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )

    user = db.relationship("User", back_populates="chat_history")
    document = db.relationship("Document")


class Feedback(db.Model):
    """Validated user feedback for one locally generated answer."""

    id = db.Column(db.Integer, primary_key=True)
    reference_id = db.Column(db.String(40), unique=True, nullable=False, index=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chat_history_id = db.Column(
        db.Integer,
        db.ForeignKey("chat_history.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # ``message_id`` is a convenient API alias for integrations using the PRD
    # terminology; both names address the same column.
    message_id = synonym("chat_history_id")
    rating = db.Column(db.String(16), nullable=False)
    category = db.Column(db.String(64), nullable=False, default="other")
    comment = db.Column(db.Text, nullable=True)
    source_ids = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )

    user = db.relationship("User")
    chat_history = db.relationship("ChatHistory")


class Escalation(db.Model):
    """A demo follow-up request stored after explicit validation and consent."""

    id = db.Column(db.Integer, primary_key=True)
    reference_id = db.Column(db.String(40), unique=True, nullable=False, index=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chat_history_id = db.Column(
        db.Integer,
        db.ForeignKey("chat_history.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    category = db.Column(db.String(32), nullable=False, default="general")
    summary = db.Column(db.Text, nullable=False)
    consent = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    status = db.Column(db.String(32), nullable=False, default="open", server_default="open")
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )

    user = db.relationship("User")
    chat_history = db.relationship("ChatHistory")


class AuditEvent(db.Model):
    """A privacy-conscious record of security and governance actions."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action = db.Column(db.String(80), nullable=False, index=True)
    entity_type = db.Column(db.String(40), nullable=True)
    entity_id = db.Column(db.String(80), nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )

    user = db.relationship("User")


# Keys that could contain private document or conversation text are deliberately
# excluded from audit metadata.  Audit events are for aggregate accountability,
# not a second content store.
_PRIVATE_AUDIT_KEYS = frozenset(
    {
        "text",
        "content",
        "message",
        "response",
        "comment",
        "summary",
        "body",
        "document_text",
        "prompt",
        "question",
    }
)


def create_audit_event(
    action: str,
    *,
    user_id: int | None = None,
    entity_type: str | None = None,
    entity_id: Any = None,
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    """Stage a sanitized audit event in the current SQLAlchemy transaction.

    The caller decides when to commit.  Only short scalar metadata is retained;
    in particular, private document/chat text is never copied into the event.
    """

    safe_metadata: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        normalized_key = str(key).lower()
        if normalized_key in _PRIVATE_AUDIT_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            if isinstance(value, str) and len(value) > 160:
                value = value[:160]
            safe_metadata[str(key)] = value

    event = AuditEvent(
        user_id=user_id,
        action=str(action)[:80],
        entity_type=str(entity_type)[:40] if entity_type else None,
        entity_id=str(entity_id)[:80] if entity_id is not None else None,
        metadata_json=json.dumps(safe_metadata, sort_keys=True) if safe_metadata else None,
    )
    db.session.add(event)
    return event
