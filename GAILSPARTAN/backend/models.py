"""Database models for users, indexed documents, and chat history."""

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
    """A PDF uploaded and indexed for one user."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename = db.Column(db.String(255), nullable=False)
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
    timestamp = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )

    user = db.relationship("User", back_populates="chat_history")
