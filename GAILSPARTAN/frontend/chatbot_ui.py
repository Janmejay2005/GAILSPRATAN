"""Optional Streamlit client for the local GAILSPARTAN Flask server.

This client only talks to the local Flask application. It intentionally has no
OpenAI, Gemini, SerpAPI, email, or other external provider integration.
"""

from __future__ import annotations

import os

import requests
import streamlit as st


BACKEND_URL = os.environ.get("GAILSPARTAN_BACKEND_URL", "http://127.0.0.1:5000").rstrip("/")


def get_client() -> requests.Session:
    if "http_client" not in st.session_state:
        st.session_state["http_client"] = requests.Session()
    return st.session_state["http_client"]


def rerun() -> None:
    if hasattr(st, "rerun"):
        st.rerun()
    st.experimental_rerun()


def request_json(method: str, path: str, **kwargs):
    try:
        response = get_client().request(method, f"{BACKEND_URL}{path}", timeout=60, **kwargs)
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": response.text or "The server returned an invalid response."}
        return response, payload
    except requests.RequestException as exc:
        return None, {"error": f"Could not reach the local Flask server: {exc}"}


st.set_page_config(page_title="GAILSPARTAN", page_icon="✦", layout="wide")
st.title("GAILSPARTAN")
st.caption("Local, source-grounded document assistance")

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    st.subheader("Sign in")
    with st.form("login-form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        response, payload = request_json(
            "POST",
            "/login",
            data={"username": username, "password": password},
        )
        if response is not None and response.ok:
            st.session_state["logged_in"] = True
            rerun()
        else:
            st.error(payload.get("error", "Login failed. Check your credentials."))
    st.info("Run the Flask server first, then use the same local account here.")
else:
    with st.sidebar:
        st.header("Workspace")
        if st.button("Sign out", use_container_width=True):
            request_json("GET", "/logout")
            st.session_state["logged_in"] = False
            rerun()

        st.divider()
        st.caption(f"Backend: {BACKEND_URL}")

    st.subheader("Ask your documents")
    question = st.text_area(
        "Question",
        placeholder="Ask a question about an indexed PDF...",
        height=110,
    )
    uploaded_file = st.file_uploader("Attach a PDF (optional)", type=["pdf"])
    if st.button("Ask GAILSPARTAN", type="primary"):
        if not question.strip():
            st.warning("Enter a question first.")
        else:
            files = None
            if uploaded_file is not None:
                files = {
                    "pdf_file": (
                        uploaded_file.name,
                        uploaded_file.getvalue(),
                        "application/pdf",
                    )
                }
            response, payload = request_json(
                "POST",
                "/chat",
                data={"message": question.strip()},
                files=files,
            )
            if response is not None and response.ok:
                st.markdown("### Answer")
                st.write(payload.get("response", "No answer was returned."))
                sources = payload.get("sources", [])
                if sources:
                    st.markdown("### Sources")
                    for source in sources:
                        page = source.get("page_number") or source.get("page")
                        suffix = f" · page {page}" if page else ""
                        st.caption(f"{source.get('filename', 'Unknown document')}{suffix}")
                else:
                    st.warning("No supporting source was found in your indexed documents.")
            else:
                st.error(payload.get("error", "The request failed."))

    st.divider()
    documents_tab, history_tab = st.tabs(["Documents", "Recent history"])
    with documents_tab:
        response, payload = request_json("GET", "/documents")
        if response is not None and response.ok:
            if payload:
                for document in payload:
                    st.write(f"**{document['filename']}** — {document['chunk_count']} chunks")
            else:
                st.caption("No documents indexed yet.")
        else:
            st.error(payload.get("error", "Could not load documents."))

    with history_tab:
        response, payload = request_json("GET", "/get_chat_history")
        if response is not None and response.ok:
            if payload:
                for item in payload:
                    with st.expander(item["message"]):
                        st.write(item["response"])
            else:
                st.caption("No conversation history yet.")
        else:
            st.error(payload.get("error", "Could not load conversation history."))
