import os

from core.sidebar_ui import ensure_bootstrap_icons, render_sidebar
from core.supabase_client import restore_supabase_session
# Load .env locally (Render already injects env vars, so this is safe)
if os.path.exists(".env"):
    from dotenv import load_dotenv
    load_dotenv()
import streamlit as st

APP_NAME = "D+ Chat"

st.set_page_config(page_title=APP_NAME, page_icon="./static/shield-lock.svg", layout="wide")
ensure_bootstrap_icons()
render_sidebar(app_title=APP_NAME)

# ------------------------- Auth -------------------------
restore_supabase_session()

def _legal_footer() -> None:
    st.markdown(
        """
---
**Legal**

- [Privacy Policy](Privacy)
"""
    )

user = st.session_state.get("user")
role = st.session_state.get("role", "user")

if not user:
    st.title(APP_NAME)
    st.caption("Democracia+ — document Q&A with citations for internal and public PDFs.")

    st.markdown(
        """
### What this app does

Democracia Mas Chat lets you **upload PDFs** and then **chat with them**. It uses a retrieval system to find the
most relevant passages and an AI model to answer your questions, so you can:

- quickly understand long documents
- ask questions and get grounded answers (with sources)
- keep a searchable history of your conversations
"""
    )

    c1, c2 = st.columns([1, 2], gap="small")
    with c1:
        if st.button("Go to Login", type="primary", use_container_width=True):
            st.switch_page("pages/0_Login.py")
    _legal_footer()
    st.stop()

# Home page is NOT admin-only; admin checks should be on admin pages only.

st.title(f"{APP_NAME} — Democracia+")

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

_legal_footer()

if role == "admin":
    missing = []
    for k in ["SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]:
        if not os.environ.get(k):
            missing.append(k)

    if missing:
        st.warning("Missing env vars: " + ", ".join(missing))
    else:
        st.success("Environment looks good.")
