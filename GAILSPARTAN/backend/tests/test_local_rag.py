from __future__ import annotations

from io import BytesIO

from backend.extensions import db
from backend.models import User
from backend.rag import (
    LocalRAGService,
    UNSUPPORTED_ANSWER,
    chunk_text,
    extract_pdf_pages,
)
from werkzeug.security import generate_password_hash


def test_pdf_extraction_chunk_overlap_and_grounded_answer(app, text_pdf):
    pdf_bytes = text_pdf(
        "The local retention policy requires seven years of retention for audit records. "
        "Only authorized reviewers may change those records."
    )

    with app.app_context():
        pages = extract_pdf_pages(BytesIO(pdf_bytes))
        assert pages[0].page_number == 1
        assert "seven years" in pages[0].text

        chunks = chunk_text("alpha beta gamma delta epsilon zeta", chunk_size=20, overlap=6)
        assert len(chunks) > 1
        assert set(chunks[0].split()) & set(chunks[1].split())

        user = User(
            username="retrieval-user",
            email="retrieval@example.com",
            password=generate_password_hash("password"),
        )
        db.session.add(user)
        db.session.commit()

        service = LocalRAGService(chunk_size=240, overlap=40)
        document = service.index_pdf(user.id, BytesIO(pdf_bytes), "retention-policy.pdf")
        db.session.commit()

        answer = service.answer(user.id, "How long is retention required for audit records?")
        assert "seven years" in answer.response.lower()
        assert answer.sources
        assert answer.sources[0]["filename"] == "retention-policy.pdf"
        assert answer.sources[0]["page"] == 1
        assert answer.sources[0]["chunk"] == 0

        unsupported = service.answer(user.id, "What is the recipe for chocolate cake?")
        assert unsupported.response == UNSUPPORTED_ANSWER
        assert unsupported.sources == []

        other_user = User(
            username="other-user",
            email="other@example.com",
            password=generate_password_hash("password"),
        )
        db.session.add(other_user)
        db.session.commit()
        service.index_pdf(
            other_user.id,
            BytesIO(text_pdf("Other user's confidential project code is ORBIT-42.")),
            "other.pdf",
        )
        db.session.commit()

        isolated = service.answer(user.id, "What is the confidential project code?")
        assert isolated.response == UNSUPPORTED_ANSWER
        assert isolated.sources == []
        assert document.id is not None
