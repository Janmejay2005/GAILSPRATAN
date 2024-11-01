import streamlit as st
import requests

st.title("GAILSPARTAN")

if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False

def login(username, password):
    response = requests.post("http://127.0.0.1:5000/login", data={'username': username, 'password': password})
    if response.status_code == 200:
        st.session_state['logged_in'] = True
        st.experimental_rerun()
    else:
        st.error("Login failed")

if st.session_state['logged_in']:
    st.write("You are logged in!")
    user_input = st.text_input("You: ", key="input")
    if st.button("Send"):
        response = requests.post("http://127.0.0.1:5000/chat", data={'message': user_input})
        st.write(f"GAILSPARTAN: {response.text}")

    # SERPAPI Integration
    query = st.text_input("Search Query:")
    if st.button("Search"):
        response = requests.get(f"http://127.0.0.1:5000/search?query={query}")
        st.write(response.json())

    # OpenAI API Integration
    prompt = st.text_area("OpenAI Prompt:")
    if st.button("Generate"):
        response = requests.post("http://127.0.0.1:5000/openai", json={'prompt': prompt})
        st.write(response.text)

    # Gemini API Integration
    data = {"some_key": "some_value"}
    if st.button("Call Gemini API"):
        response = requests.post("http://127.0.0.1:5000/gemini", json=data)
        st.write(response.json())
else:
    st.subheader("Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        login(username, password)
