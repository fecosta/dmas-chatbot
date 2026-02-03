import streamlit as st
from core.supabase_client import auth_sign_in, ensure_profile
from core.sidebar_ui import render_sidebar, bi, ensure_bootstrap_icons

st.set_page_config(page_title="Login", page_icon="🔐", layout="centered")
ensure_bootstrap_icons()
render_sidebar()

# Bootstrap Icons (visual-only)
st.markdown(
    '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css">',
    unsafe_allow_html=True,
)

st.markdown(f"# {bi('shield-lock')} Login", unsafe_allow_html=True)
st.caption("Sign in to access chat and your documents.")

if st.session_state.get("user"):
    st.success("You are already logged in.")
    st.page_link("pages/1_Chat.py", label="Go to Chat")
    st.stop()

email = st.text_input("Email", key="login_email")
password = st.text_input("Password", type="password", key="login_password")

if st.button("Login", type="primary", use_container_width=True):
    res = auth_sign_in(email, password)
    user = {"id": res["user"].id, "email": res["user"].email}
    st.session_state["user"] = user
    profile = ensure_profile(user["id"], user["email"])
    st.session_state["role"] = profile.get("role", "user")
    st.success("Logged in.")
    st.switch_page("pages/1_Chat.py")