import os

from core.sidebar_ui import ensure_bootstrap_icons, render_sidebar
from core.supabase_client import restore_supabase_session
# Load .env locally (Render already injects env vars, so this is safe)
if os.path.exists(".env"):
    from dotenv import load_dotenv
    load_dotenv()
import streamlit as st

st.set_page_config(page_title="D+ Chatbot", page_icon="🗳️", layout="wide")
ensure_bootstrap_icons()
render_sidebar()

st.markdown(
    """
    <link rel="stylesheet"
          href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css">
    """,
    unsafe_allow_html=True,
)

# ------------------------- Auth -------------------------
restore_supabase_session()

user = st.session_state.get("user")
if not user:
    st.info("Please log in.")
    st.switch_page("pages/0_Login.py")
    st.stop()

# Home page is NOT admin-only; admin checks should be on admin pages only.

st.title("D+ Chatbot — Democracia+")

st.markdown(
    """
This app is split into independent sections:

- **Chat** — the user interface
- **Admin → Users** — manage accounts and roles
- **Admin → Data** — upload documents and process PDFs
- **Admin → Model** — model & retrieval settings

Use the sidebar to navigate pages.
"""
)

# Just show env sanity (optional)
missing = []
for k in ["SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]:
    if not os.environ.get(k):
        missing.append(k)

if missing:
    st.warning("Missing env vars: " + ", ".join(missing))
else:
    st.success("Environment looks good.")
