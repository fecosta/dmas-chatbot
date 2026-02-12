import streamlit as st

from core.sidebar_ui import ensure_bootstrap_icons, render_sidebar
from core.supabase_client import restore_supabase_session


APP_NAME = "Democracia Mas Chat"

st.set_page_config(page_title="Privacy Policy", page_icon="./static/shield-lock.svg", layout="wide")
ensure_bootstrap_icons()
render_sidebar(app_title=APP_NAME)

# If the user is logged in, keep the session fresh.
restore_supabase_session()

st.title("Privacy Policy")
st.caption("Last updated: 2026-02-12")

st.markdown(
    """
This Privacy Policy explains how **D+ Chat** ("the app") handles data.

### What the app is

D+ Chat is a document-based chatbot. You can upload documents (for example, PDFs) and ask questions.
The app retrieves relevant passages and uses AI to generate answers.

### Data we collect

Depending on how the app is configured, we may process:

- **Account data**: name and email address used for authentication.
- **Uploaded documents**: files you upload for analysis.
- **Chat content**: messages you send and the assistant's responses.
- **Usage and security logs**: to operate the service, prevent abuse, and debug issues.

### How we use data

We use your data to:

- authenticate users and enforce access controls
- provide document search and chat functionality
- store conversation history (if enabled)
- improve reliability and security (monitoring, error handling)

### Sharing and third parties

The app may rely on third-party providers for infrastructure and AI processing (for example, authentication,
database storage, and model inference). We only share the minimum data necessary to provide the service.

### Data retention

Documents and chat history may be stored to support features like history and re-use. Retention periods depend on
the organization’s policies and the app configuration.

### Your choices

If you need access, deletion, or export of your data, contact the administrator of the service.

### Contact

For privacy questions, contact: **contato@democraciamas.com**
"""
)

st.markdown("---")
st.page_link("app.py", label="Back to Home")
st.page_link("pages/0_Login.py", label="Go to Login")