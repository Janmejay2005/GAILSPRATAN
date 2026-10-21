from __future__ import annotations

from io import BytesIO


def _register_and_login(client):
    register_response = client.post(
        "/register",
        data={
            "username": "flow-user",
            "email": "flow@example.com",
            "password": "password",
        },
    )
    assert register_response.status_code == 302

    login_response = client.post(
        "/login",
        data={"username": "flow-user", "password": "password"},
    )
    assert login_response.status_code == 302


def test_local_chat_flow_is_authenticated_and_user_scoped(app, text_pdf):
    client = app.test_client()

    assert client.get("/documents").status_code == 401
    assert client.get("/get_chat_history").status_code == 401
    assert client.post("/chat", data={"message": "hello"}).status_code == 401

    _register_and_login(client)
    pdf_bytes = text_pdf(
        "The incident response plan requires notification within twenty four hours."
    )
    response = client.post(
        "/chat",
        data={
            "message": "When is notification required?",
            "pdf_file": (BytesIO(pdf_bytes), "incident-plan.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert "twenty four hours" in payload["response"].lower()
    assert payload["sources"][0]["filename"] == "incident-plan.pdf"

    history = client.get("/get_chat_history")
    assert history.status_code == 200
    assert history.get_json()[0]["message"] == "When is notification required?"

    documents = client.get("/documents")
    assert documents.status_code == 200
    assert documents.get_json()[0]["filename"] == "incident-plan.pdf"
    assert documents.get_json()[0]["chunk_count"] >= 1

    assert client.get("/search").status_code == 404
    assert client.post("/openai").status_code == 404
    assert client.post("/gemini").status_code == 404

    assert client.get("/logout").status_code == 302
    assert client.get("/chat").status_code == 302


def test_registration_rejects_missing_and_duplicate_fields(app):
    client = app.test_client()
    assert client.post("/register", data={"username": "", "email": "bad"}).status_code == 400

    _register_and_login(client)
    client.get("/logout")
    duplicate = client.post(
        "/register",
        data={
            "username": "flow-user",
            "email": "different@example.com",
            "password": "password",
        },
    )
    assert duplicate.status_code == 409


def test_local_ui_routes_render_gailspratan_pages(app):
    client = app.test_client()

    public_pages = ["/", "/login", "/register", "/help"]
    for path in public_pages:
        response = client.get(path)
        assert response.status_code == 200
        assert b"GAILSPARTAN" in response.data
        assert b"OrgAssist" not in response.data

    _register_and_login(client)
    for path in ["/chat", "/documents/view", "/history"]:
        response = client.get(path)
        assert response.status_code == 200
        assert b"GAILSPARTAN" in response.data
        assert b"OrgAssist" not in response.data
