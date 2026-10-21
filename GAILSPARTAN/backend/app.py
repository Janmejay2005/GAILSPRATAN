"""Flask backend for the API-free local GAILSPARTAN RAG MVP."""

from __future__ import annotations

import os
from pathlib import Path
import re
import json
from datetime import datetime
import uuid
from typing import Any

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

try:  # Support both ``python -m backend.app`` and ``python backend/app.py``.
    from .extensions import db
    from .models import (
        AuditEvent,
        ChatHistory,
        Document,
        Escalation,
        Feedback,
        User,
        create_audit_event,
    )
    from .rag import LocalRAGService
    from .safety import check_input
except ImportError:  # pragma: no cover - exercised only for direct script use.
    from extensions import db
    from models import (
        AuditEvent,
        ChatHistory,
        Document,
        Escalation,
        Feedback,
        User,
        create_audit_event,
    )
    from rag import LocalRAGService
    from safety import check_input


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "chatbot.db"
FALLBACK_DATABASE_PATH = PROJECT_ROOT / "chatbot.sqlite3"
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _default_database_uri() -> str:
    # The repository's historical ``chatbot.db`` artifact is not a SQLite
    # file. Preserve it and use a real local SQLite file until a user provides
    # a valid database path through the app configuration.
    database_path = DEFAULT_DATABASE_PATH
    if database_path.exists():
        try:
            with database_path.open("rb") as database_file:
                if database_file.read(16) != b"SQLite format 3\x00":
                    database_path = FALLBACK_DATABASE_PATH
        except OSError:
            database_path = FALLBACK_DATABASE_PATH
    return f"sqlite:///{database_path.as_posix()}"


def _error_response(message: str, template: str, status: int):
    if request.is_json or request.accept_mimetypes.best == "application/json":
        return jsonify({"error": message}), status
    return render_template(template, error=message), status


def _unauthorized_response(json_response: bool = False):
    if json_response:
        return jsonify({"error": "Unauthorized"}), 401
    return redirect(url_for("login"))


def _valid_registration_input(username: str, email: str, password: str) -> str | None:
    if not username or not email or not password:
        return "Username, email, and password are required."
    if len(username) > 80 or any(character.isspace() for character in username):
        return "Username must be 80 characters or fewer and contain no spaces."
    if not _EMAIL_PATTERN.fullmatch(email):
        return "Enter a valid email address."
    if len(email) > 255:
        return "Email must be 255 characters or fewer."
    return None


ADMIN_ROLES = frozenset({"knowledge_admin", "system_admin"})
VALID_DOCUMENT_STATUSES = frozenset(
    {"unverified", "verified", "outdated", "archived", "failed"}
)
VALID_FEEDBACK_RATINGS = frozenset({"positive", "negative", "up", "down"})
VALID_FEEDBACK_CATEGORIES = frozenset(
    {"incorrect_answer", "missing_citation", "outdated_source", "incomplete_answer", "inaccessible_source", "other"}
)
VALID_ESCALATION_CATEGORIES = frozenset({"hr", "it", "general"})


def _current_user() -> User | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(User, user_id)


def _request_value(name: str, default: Any = None) -> Any:
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        return payload.get(name, default)
    return request.form.get(name, default)


def _parse_optional_date(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("Dates must use YYYY-MM-DD format.") from exc


def _document_payload(document: Document, *, include_content: bool = False) -> dict[str, Any]:
    payload = {
        "id": document.id,
        "filename": document.filename,
        "title": document.title,
        "category": document.category,
        "version": document.version,
        "access_scope": document.access_scope,
        "verification_status": document.verification_status,
        "ingestion_status": document.ingestion_status,
        "checksum": document.checksum,
        "effective_date": document.effective_date.isoformat() if document.effective_date else None,
        "review_date": document.review_date.isoformat() if document.review_date else None,
        "created_at": document.created_at.isoformat() if document.created_at else None,
        "summary": document.summary,
        "keywords": [item for item in (document.keywords or "").split(",") if item],
        "chunk_count": len(document.chunks),
        "owner_id": document.user_id,
    }
    if include_content:
        payload["chunks"] = [
            {
                "id": chunk.id,
                "page_number": chunk.page_number,
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
            }
            for chunk in document.chunks
        ]
    return payload


def _history_payload(item: ChatHistory) -> dict[str, Any]:
    citations = []
    if item.citations:
        try:
            citations = json.loads(item.citations)
        except (TypeError, ValueError):
            citations = []
    return {
        "id": item.id,
        "message": item.message,
        "response": item.response,
        "document_id": item.document_id,
        "grounding_status": item.grounding_status,
        "needs_escalation": item.needs_escalation,
        "latency_ms": item.latency_ms,
        "citations": citations,
        "timestamp": item.timestamp.isoformat() if item.timestamp else None,
    }


def _role_allows(user: User | None, *roles: str) -> bool:
    return user is not None and user.role in set(roles)


def _reference(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    """Create a configured Flask app and initialize its database in context."""

    app = Flask(
        __name__,
        template_folder=str(PROJECT_ROOT / "templates"),
        static_folder=str(PROJECT_ROOT / "static"),
    )
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "gailspratan-local-dev-key"),
        SQLALCHEMY_DATABASE_URI=_default_database_uri(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,
        MAX_UPLOAD_SIZE=10 * 1024 * 1024,
        MAX_QUESTION_LENGTH=4000,
        RAG_CHUNK_SIZE=1000,
        RAG_CHUNK_OVERLAP=150,
        RAG_TOP_K=5,
    )
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    with app.app_context():
        db.create_all()

    @app.errorhandler(413)
    def request_too_large(_error):
        if request.is_json or request.accept_mimetypes.best == "application/json":
            return jsonify({"error": "The upload exceeds the configured size limit."}), 413
        return render_template("login.html", error="The upload exceeds the configured size limit."), 413

    @app.context_processor
    def inject_current_user():
        return {"current_user": _current_user()}

    rag_service = LocalRAGService(
        chunk_size=app.config["RAG_CHUNK_SIZE"],
        overlap=app.config["RAG_CHUNK_OVERLAP"],
    )

    @app.route("/")
    def home():
        if session.get("user_id"):
            return redirect(url_for("chat"))
        return render_template("login.html")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "GET":
            return render_template("register.html")

        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        validation_error = _valid_registration_input(username, email, password)
        if validation_error:
            return _error_response(validation_error, "register.html", 400)

        duplicate = User.query.filter(
            (User.username == username) | (User.email == email)
        ).first()
        if duplicate:
            return _error_response(
                "Username or email is already registered.",
                "register.html",
                409,
            )

        user = User(
            username=username,
            email=email,
            password=generate_password_hash(password),
        )
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return _error_response(
                "Username or email is already registered.",
                "register.html",
                409,
            )
        create_audit_event(
            "user_registered",
            user_id=user.id,
            entity_type="user",
            entity_id=user.id,
            metadata={"role": user.role},
        )
        db.session.commit()
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            return render_template("login.html")

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            return _error_response(
                "Username and password are required.",
                "login.html",
                400,
            )

        user = User.query.filter_by(username=username).first()
        if user is None or not check_password_hash(user.password, password):
            return _error_response("Invalid username or password.", "login.html", 401)

        session.clear()
        session["user_id"] = user.id
        session["username"] = user.username
        create_audit_event(
            "user_login",
            user_id=user.id,
            entity_type="user",
            entity_id=user.id,
        )
        db.session.commit()
        return redirect(url_for("chat"))

    @app.route("/logout", methods=["GET", "POST"])
    def logout():
        user = _current_user()
        if user is not None:
            create_audit_event(
                "user_logout",
                user_id=user.id,
                entity_type="user",
                entity_id=user.id,
            )
            db.session.commit()
        session.clear()
        return redirect(url_for("login"))

    @app.route("/chat", methods=["GET", "POST"])
    def chat():
        user = _current_user()
        if user is None:
            return _unauthorized_response(json_response=request.method == "POST")

        if request.method == "GET":
            return render_template("chat.html")

        message = str(_request_value("message", "") or "").strip()
        safety_result = check_input(
            message,
            max_length=app.config["MAX_QUESTION_LENGTH"],
        )
        if not safety_result.allowed:
            create_audit_event(
                "chat_rejected",
                user_id=user.id,
                entity_type="chat",
                metadata={"category": safety_result.category},
            )
            db.session.commit()
            return jsonify(
                {
                    "error": safety_result.message,
                    "safety_status": safety_result.category,
                }
            ), 400

        uploaded_file = request.files.get("pdf_file")
        indexed_document = None
        filename = ""
        if uploaded_file is not None and uploaded_file.filename:
            filename = secure_filename(uploaded_file.filename)
            if not filename or not filename.lower().endswith((".pdf", ".txt")):
                return jsonify({"error": "Only PDF and UTF-8 TXT files can be indexed."}), 400

        try:
            if uploaded_file is not None and uploaded_file.filename:
                indexed_document = rag_service.index_file(
                    user.id,
                    uploaded_file,
                    filename,
                    title=_request_value("title"),
                    category=_request_value("category", "general"),
                    version=_request_value("version", "1.0"),
                    max_size=app.config["MAX_UPLOAD_SIZE"],
                )
                create_audit_event(
                    "document_indexed",
                    user_id=user.id,
                    entity_type="document",
                    entity_id=indexed_document.id,
                    metadata={
                        "filename": indexed_document.filename,
                        "category": indexed_document.category,
                        "duplicate_checksum": indexed_document.checksum is not None,
                    },
                )
            result = rag_service.answer(
                user.id,
                message,
                top_k=app.config["RAG_TOP_K"],
                document_id=indexed_document.id if indexed_document is not None else None,
            )
            history_item = ChatHistory(
                user_id=user.id,
                message=message,
                response=result.response,
                document_id=indexed_document.id if indexed_document is not None else None,
                grounding_status=result.grounding_status,
                needs_escalation=result.needs_escalation,
                latency_ms=result.latency_ms,
                citations=json.dumps(result.citations),
            )
            db.session.add(history_item)
            db.session.flush()
            create_audit_event(
                "chat_answered",
                user_id=user.id,
                entity_type="chat_history",
                entity_id=history_item.id,
                metadata={
                    "grounding_status": result.grounding_status,
                    "needs_escalation": result.needs_escalation,
                    "latency_ms": result.latency_ms,
                    "source_count": len(result.sources),
                },
            )
            db.session.commit()
        except ValueError as exc:
            db.session.rollback()
            return jsonify({"error": str(exc)}), 400
        except Exception:
            db.session.rollback()
            raise

        return jsonify(
            {
                "response": result.response,
                "answer": result.response,
                "sources": result.sources,
                "citations": result.citations,
                "grounding_status": result.grounding_status,
                "needs_escalation": result.needs_escalation,
                "latency_ms": result.latency_ms,
                "document_id": indexed_document.id if indexed_document is not None else None,
                "chat_history_id": history_item.id,
            }
        )

    @app.route("/get_chat_history", methods=["GET"])
    def get_chat_history():
        user = _current_user()
        if user is None:
            return _unauthorized_response(json_response=True)

        history = (
            ChatHistory.query.filter_by(user_id=user.id)
            .order_by(ChatHistory.timestamp.desc(), ChatHistory.id.desc())
            .limit(10)
            .all()
        )
        return jsonify(
            [_history_payload(item) for item in history]
        )

    @app.route("/documents", methods=["GET", "POST"])
    def documents():
        user = _current_user()
        if user is None:
            return _unauthorized_response(json_response=True)

        if request.method == "POST":
            uploaded_file = request.files.get("pdf_file")
            if uploaded_file is None or not uploaded_file.filename:
                return jsonify({"error": "Choose a PDF or TXT file to index."}), 400
            filename = secure_filename(uploaded_file.filename)
            if not filename or not filename.lower().endswith((".pdf", ".txt")):
                return jsonify({"error": "Only PDF and UTF-8 TXT files can be indexed."}), 400
            try:
                document = rag_service.index_file(
                    user.id,
                    uploaded_file,
                    filename,
                    title=_request_value("title"),
                    category=_request_value("category", "general"),
                    version=_request_value("version", "1.0"),
                    max_size=app.config["MAX_UPLOAD_SIZE"],
                )
                create_audit_event(
                    "document_indexed",
                    user_id=user.id,
                    entity_type="document",
                    entity_id=document.id,
                    metadata={"filename": document.filename, "category": document.category},
                )
                db.session.commit()
            except ValueError as exc:
                db.session.rollback()
                return jsonify({"error": str(exc)}), 400
            return jsonify(_document_payload(document)), 201

        indexed_documents = (
            Document.query.filter_by(user_id=user.id)
            .order_by(Document.created_at.desc(), Document.id.desc())
            .all()
        )
        return jsonify(
            [_document_payload(document) for document in indexed_documents]
        )

    @app.route("/documents/<int:document_id>", methods=["GET", "DELETE"])
    def document_detail(document_id: int):
        user = _current_user()
        if user is None:
            return _unauthorized_response(json_response=True)
        document = db.session.get(Document, document_id)
        if document is None:
            return jsonify({"error": "Document not found."}), 404
        can_manage = document.user_id == user.id or user.role in ADMIN_ROLES
        if not can_manage:
            return jsonify({"error": "Document not found."}), 404

        if request.method == "GET":
            return jsonify(_document_payload(document))

        db.session.delete(document)
        create_audit_event(
            "document_deleted",
            user_id=user.id,
            entity_type="document",
            entity_id=document.id,
            metadata={"owner_id": document.user_id},
        )
        db.session.commit()
        return jsonify({"deleted": True, "id": document_id})

    @app.route("/documents/<int:document_id>/summarize", methods=["POST"])
    def summarize_document(document_id: int):
        user = _current_user()
        if user is None:
            return _unauthorized_response(json_response=True)
        document = db.session.get(Document, document_id)
        if document is None or (
            document.user_id != user.id and user.role not in ADMIN_ROLES
        ):
            return jsonify({"error": "Document not found."}), 404
        return jsonify(
            {
                "id": document.id,
                "title": document.title,
                "summary": document.summary or "No extractable summary is available.",
                "keywords": [item for item in (document.keywords or "").split(",") if item],
                "generated": True,
            }
        )

    @app.route("/documents/<int:document_id>/ask", methods=["POST"])
    def ask_document(document_id: int):
        user = _current_user()
        if user is None:
            return _unauthorized_response(json_response=True)
        document = db.session.get(Document, document_id)
        # Even admins do not get cross-user document text through this route.
        if document is None or document.user_id != user.id:
            return jsonify({"error": "Document not found."}), 404
        message = str(_request_value("message", "") or "").strip()
        safety_result = check_input(
            message,
            max_length=app.config["MAX_QUESTION_LENGTH"],
        )
        if not safety_result.allowed:
            return jsonify(
                {"error": safety_result.message, "safety_status": safety_result.category}
            ), 400
        result = rag_service.answer(
            user.id,
            message,
            top_k=app.config["RAG_TOP_K"],
            document_id=document.id,
        )
        return jsonify(
            {
                "response": result.response,
                "answer": result.response,
                "sources": result.sources,
                "citations": result.citations,
                "grounding_status": result.grounding_status,
                "needs_escalation": result.needs_escalation,
                "latency_ms": result.latency_ms,
                "document_id": document.id,
            }
        )

    @app.route("/feedback", methods=["GET", "POST"])
    def feedback():
        user = _current_user()
        if user is None:
            return _unauthorized_response(json_response=True)
        if request.method == "GET":
            items = (
                Feedback.query.filter_by(user_id=user.id)
                .order_by(Feedback.created_at.desc(), Feedback.id.desc())
                .limit(50)
                .all()
            )
            return jsonify(
                [
                    {
                        "reference_id": item.reference_id,
                        "rating": item.rating,
                        "category": item.category,
                        "created_at": item.created_at.isoformat() if item.created_at else None,
                    }
                    for item in items
                ]
            )

        rating = str(_request_value("rating", "")).strip().lower()
        rating = {"up": "positive", "down": "negative"}.get(rating, rating)
        category = str(_request_value("category", "other") or "other").strip().lower()
        comment = str(_request_value("comment", "") or "").strip()
        if rating not in {"positive", "negative"}:
            return jsonify({"error": "Rating must be positive or negative."}), 400
        if category not in VALID_FEEDBACK_CATEGORIES:
            return jsonify({"error": "Unsupported feedback category."}), 400
        if len(comment) > 1000:
            return jsonify({"error": "Feedback comments must be 1000 characters or fewer."}), 400

        raw_history_id = _request_value("chat_history_id", _request_value("message_id"))
        history_item = None
        if raw_history_id not in (None, ""):
            try:
                history_item = db.session.get(ChatHistory, int(raw_history_id))
            except (TypeError, ValueError):
                return jsonify({"error": "chat_history_id must be an integer."}), 400
            if history_item is None or history_item.user_id != user.id:
                return jsonify({"error": "Chat history item not found."}), 404

        raw_source_ids = _request_value("source_ids", [])
        if isinstance(raw_source_ids, str):
            try:
                raw_source_ids = json.loads(raw_source_ids)
            except (TypeError, ValueError):
                raw_source_ids = [raw_source_ids]
        if not isinstance(raw_source_ids, list):
            return jsonify({"error": "source_ids must be a list."}), 400
        valid_source_ids = set()
        if history_item and history_item.citations:
            try:
                valid_source_ids = {
                    str(item.get("citation_id"))
                    for item in json.loads(history_item.citations)
                    if isinstance(item, dict) and item.get("citation_id")
                }
            except (TypeError, ValueError):
                valid_source_ids = set()
        source_ids = [str(item) for item in raw_source_ids]
        if valid_source_ids and any(item not in valid_source_ids for item in source_ids):
            return jsonify({"error": "One or more source citations are invalid."}), 400

        feedback_item = Feedback(
            reference_id=_reference("FB"),
            user_id=user.id,
            chat_history_id=history_item.id if history_item else None,
            rating=rating,
            category=category,
            comment=comment or None,
            source_ids=json.dumps(source_ids),
        )
        db.session.add(feedback_item)
        db.session.flush()
        create_audit_event(
            "feedback_created",
            user_id=user.id,
            entity_type="feedback",
            entity_id=feedback_item.reference_id,
            metadata={"rating": rating, "category": category},
        )
        db.session.commit()
        return jsonify(
            {
                "created": True,
                "reference_id": feedback_item.reference_id,
                "rating": rating,
                "category": category,
            }
        ), 201

    @app.route("/escalations", methods=["GET", "POST"])
    def escalations():
        user = _current_user()
        if user is None:
            return _unauthorized_response(json_response=True)
        if request.method == "GET":
            items = (
                Escalation.query.filter_by(user_id=user.id)
                .order_by(Escalation.created_at.desc(), Escalation.id.desc())
                .limit(50)
                .all()
            )
            return jsonify(
                [
                    {
                        "reference_id": item.reference_id,
                        "category": item.category,
                        "status": item.status,
                        "created_at": item.created_at.isoformat() if item.created_at else None,
                    }
                    for item in items
                ]
            )

        category = str(_request_value("category", "general") or "general").strip().lower()
        summary = str(_request_value("summary", "") or "").strip()
        consent = _request_value("consent", False)
        consent = consent is True or str(consent).strip().lower() in {"true", "1", "yes", "on"}
        if category not in VALID_ESCALATION_CATEGORIES:
            return jsonify({"error": "Escalation category must be hr, it, or general."}), 400
        if not summary or len(summary) > 2000:
            return jsonify({"error": "Provide a summary of 1 to 2000 characters."}), 400
        if not consent:
            return jsonify({"error": "Consent is required before creating an escalation."}), 400

        raw_history_id = _request_value("chat_history_id", _request_value("message_id"))
        history_item = None
        if raw_history_id not in (None, ""):
            try:
                history_item = db.session.get(ChatHistory, int(raw_history_id))
            except (TypeError, ValueError):
                return jsonify({"error": "chat_history_id must be an integer."}), 400
            if history_item is None or history_item.user_id != user.id:
                return jsonify({"error": "Chat history item not found."}), 404

        escalation = Escalation(
            reference_id=_reference("ESC"),
            user_id=user.id,
            chat_history_id=history_item.id if history_item else None,
            category=category,
            summary=summary,
            consent=True,
            status="open",
        )
        db.session.add(escalation)
        db.session.flush()
        create_audit_event(
            "escalation_created",
            user_id=user.id,
            entity_type="escalation",
            entity_id=escalation.reference_id,
            metadata={"category": category, "status": escalation.status},
        )
        db.session.commit()
        return jsonify(
            {
                "created": True,
                "reference_id": escalation.reference_id,
                "status": escalation.status,
                "category": escalation.category,
            }
        ), 201

    @app.route("/me", methods=["GET"])
    def me():
        user = _current_user()
        if user is None:
            return _unauthorized_response(json_response=True)
        return jsonify({"id": user.id, "username": user.username, "email": user.email, "role": user.role})

    @app.route("/health", methods=["GET"])
    def health():
        try:
            db.session.execute(text("SELECT 1"))
            database_status = "ok"
        except Exception:
            database_status = "error"
        return jsonify(
            {
                "status": "ok" if database_status == "ok" else "degraded",
                "database": database_status,
                "retrieval": "local-tfidf",
                "external_providers": "disabled",
            }
        ), 200 if database_status == "ok" else 503

    @app.route("/admin/metrics", methods=["GET"])
    def admin_metrics():
        user = _current_user()
        if user is None:
            return _unauthorized_response(json_response=True)
        if user.role not in ADMIN_ROLES:
            return jsonify({"error": "Administrator access required."}), 403

        history_items = ChatHistory.query.with_entities(
            ChatHistory.grounding_status,
            ChatHistory.needs_escalation,
            ChatHistory.latency_ms,
        ).all()
        latencies = [int(item.latency_ms or 0) for item in history_items]
        return jsonify(
            {
                "users": User.query.count(),
                "documents": Document.query.count(),
                "ready_documents": Document.query.filter_by(ingestion_status="ready").count(),
                "failed_documents": Document.query.filter_by(ingestion_status="failed").count(),
                "questions": len(history_items),
                "unanswered_questions": sum(
                    1 for item in history_items if item.grounding_status != "grounded"
                ),
                "escalation_needed": sum(1 for item in history_items if item.needs_escalation),
                "feedback": Feedback.query.count(),
                "open_escalations": Escalation.query.filter_by(status="open").count(),
                "audit_events": AuditEvent.query.count(),
                "average_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0,
            }
        )

    @app.route("/admin/documents", methods=["GET"])
    def admin_documents():
        user = _current_user()
        if user is None:
            return _unauthorized_response(json_response=True)
        if user.role not in ADMIN_ROLES:
            return jsonify({"error": "Administrator access required."}), 403
        indexed_documents = Document.query.order_by(Document.created_at.desc(), Document.id.desc()).all()
        return jsonify([_document_payload(document) for document in indexed_documents])

    @app.route("/admin", methods=["GET"])
    def admin_view():
        user = _current_user()
        if user is None:
            return _unauthorized_response()
        if user.role not in ADMIN_ROLES:
            return jsonify({"error": "Administrator access required."}), 403
        return render_template("admin.html")

    @app.route("/admin/documents/<int:document_id>/review", methods=["POST"])
    def review_document(document_id: int):
        user = _current_user()
        if user is None:
            return _unauthorized_response(json_response=True)
        if user.role not in ADMIN_ROLES:
            return jsonify({"error": "Administrator access required."}), 403
        document = db.session.get(Document, document_id)
        if document is None:
            return jsonify({"error": "Document not found."}), 404

        status = str(_request_value("verification_status", document.verification_status) or "").strip().lower()
        if status not in VALID_DOCUMENT_STATUSES:
            return jsonify({"error": "Unsupported verification status."}), 400
        try:
            document.review_date = _parse_optional_date(_request_value("review_date"))
            document.effective_date = _parse_optional_date(_request_value("effective_date"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        document.verification_status = status
        if _request_value("category") is not None:
            document.category = str(_request_value("category")).strip()[:80] or document.category
        if _request_value("version") is not None:
            document.version = str(_request_value("version")).strip()[:64] or document.version
        if _request_value("title") is not None:
            document.title = str(_request_value("title")).strip()[:255] or document.title
        create_audit_event(
            "document_reviewed",
            user_id=user.id,
            entity_type="document",
            entity_id=document.id,
            metadata={"verification_status": status},
        )
        db.session.commit()
        return jsonify(_document_payload(document))

    @app.route("/admin/users/<int:user_id>/role", methods=["POST"])
    def update_user_role(user_id: int):
        user = _current_user()
        if user is None:
            return _unauthorized_response(json_response=True)
        if user.role != "system_admin":
            return jsonify({"error": "System administrator access required."}), 403
        target = db.session.get(User, user_id)
        role = str(_request_value("role", "") or "").strip().lower()
        if target is None:
            return jsonify({"error": "User not found."}), 404
        if role not in {"employee", "knowledge_admin", "system_admin"}:
            return jsonify({"error": "Unsupported role."}), 400
        target.role = role
        create_audit_event(
            "user_role_updated",
            user_id=user.id,
            entity_type="user",
            entity_id=target.id,
            metadata={"role": role},
        )
        db.session.commit()
        return jsonify({"id": target.id, "username": target.username, "role": target.role})

    @app.route("/documents/view", methods=["GET"])
    def documents_view():
        if not session.get("user_id"):
            return _unauthorized_response()
        return render_template("documents.html")

    @app.route("/history", methods=["GET"])
    def history():
        if not session.get("user_id"):
            return _unauthorized_response()
        return render_template("history.html")

    @app.route("/help", methods=["GET"])
    def help_page():
        return render_template("help.html")

    return app


# Preserve the original module-level Flask entry point while keeping all
# initialization inside create_app's application context.
app = create_app()


if __name__ == "__main__":  # pragma: no cover - manual server entry point.
    app.run(debug=True)
