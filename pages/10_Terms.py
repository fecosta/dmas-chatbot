import streamlit as st

from core.sidebar_ui import ensure_bootstrap_icons, render_sidebar
from core.supabase_client import restore_supabase_session
from core.ui import apply_ui

APP_NAME = "D+ Agora"

st.set_page_config(page_title="Terms & Conditions", page_icon="./static/shield-lock.svg", layout="wide")
ensure_bootstrap_icons()
render_sidebar(app_title=APP_NAME)

# Bootstrap Icons (visual-only)
st.markdown(
    '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css">',
    unsafe_allow_html=True,
)

apply_ui()

# If the user is logged in, keep the session fresh.
restore_supabase_session()

st.title("Terms & Conditions")
st.caption("Last updated: 2026-02-12")

st.markdown(
    """
By accessing or using **D+ Agora**, you agree to these Terms.

### Acceptable use

You agree not to:

- attempt to bypass authentication or access controls
- upload or submit unlawful, harmful, or abusive content
- interfere with or disrupt the service (including probing, scanning, or load testing without permission)
- submit sensitive data unless your organization has explicitly approved it

### Information quality

D+ Agora provides responses based on the organization’s knowledge base and system configuration. Outputs may be incomplete
or incorrect. You are responsible for verifying information before making decisions.

### Data and confidentiality

Your organization may store documents and conversation history to support features like search, continuity, and auditability.
You are responsible for ensuring you have the rights to provide any content you submit.

### Service availability

We may update, suspend, or discontinue parts of the service at any time. We do not guarantee uninterrupted availability.

### Limitation of liability

To the maximum extent permitted by law, D+ Agora and its operators are not liable for indirect or consequential damages
arising from use of the service.

### Changes to these terms

We may update these terms from time to time. The “Last updated” date above reflects the latest revision.

### Contact

For questions about these Terms, contact: **contato@democraciamas.com**
"""
)

st.markdown("---")
st.page_link("app.py", label="Back to Home")
st.page_link("pages/0_Login.py", label="Go to Login")
st.page_link("pages/9_Privacy.py", label="Privacy Policy")