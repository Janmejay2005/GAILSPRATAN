"""Flask backend for the API-free local GAILSPARTAN RAG MVP."""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

try:  # Support both ``python -m backend.app`` and ``python backend/app.py``.
    from .extensions import db
    from .models import ChatHistory, Document, User
    from .rag import LocalRAGService
except ImportError:  # pragma: no cover - exercised only for direct script use.
    from extensions import db
    from models import ChatHistory, Document, User
    from rag import LocalRAGService


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
        RAG_CHUNK_SIZE=1000,
        RAG_CHUNK_OVERLAP=150,
        RAG_TOP_K=5,
    )
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    with app.app_context():
        db.create_all()

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
        return redirect(url_for("chat"))

    @app.route("/logout", methods=["GET", "POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/chat", methods=["GET", "POST"])
    def chat():
        user_id = session.get("user_id")
        if not user_id:
            return _unauthorized_response(json_response=request.method == "POST")

        if request.method == "GET":
            return render_template("chat.html")

        message = request.form.get("message", "").strip()
        if not message:
            return jsonify({"error": "Message is required."}), 400

        uploaded_file = request.files.get("pdf_file")
        if uploaded_file is not None and uploaded_file.filename:
            filename = secure_filename(uploaded_file.filename) or "uploaded.pdf"
            if not filename.lower().endswith(".pdf"):
                return jsonify({"error": "Only PDF files can be indexed."}), 400
        else:
            filename = ""

        try:
            if filename:
                rag_service.index_pdf(user_id, uploaded_file, filename)
            result = rag_service.answer(
                user_id,
                message,
                top_k=app.config["RAG_TOP_K"],
            )
            db.session.add(
                ChatHistory(
                    user_id=user_id,
                    message=message,
                    response=result.response,
                )
            )
            db.session.commit()
        except ValueError as exc:
            db.session.rollback()
            return jsonify({"error": str(exc)}), 400
        except Exception:
            db.session.rollback()
            raise

        return jsonify({"response": result.response, "sources": result.sources})

    @app.route("/get_chat_history", methods=["GET"])
    def get_chat_history():
        user_id = session.get("user_id")
        if not user_id:
            return _unauthorized_response(json_response=True)

        history = (
            ChatHistory.query.filter_by(user_id=user_id)
            .order_by(ChatHistory.timestamp.desc(), ChatHistory.id.desc())
            .limit(10)
            .all()
        )
        return jsonify(
            [
                {
                    "id": item.id,
                    "message": item.message,
                    "response": item.response,
                    "timestamp": item.timestamp.isoformat()
                    if item.timestamp is not None
                    else None,
                }
                for item in history
            ]
        )

    @app.route("/documents", methods=["GET"])
    def documents():
        user_id = session.get("user_id")
        if not user_id:
            return _unauthorized_response(json_response=True)

        indexed_documents = (
            Document.query.filter_by(user_id=user_id)
            .order_by(Document.created_at.desc(), Document.id.desc())
            .all()
        )
        return jsonify(
            [
                {
                    "id": document.id,
                    "filename": document.filename,
                    "created_at": document.created_at.isoformat()
                    if document.created_at is not None
                    else None,
                    "chunk_count": len(document.chunks),
                }
                for document in indexed_documents
            ]
        )

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
