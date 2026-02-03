import streamlit as st
from core.supabase_client import get_profile
from core.sidebar_ui import render_sidebar, bi, ensure_bootstrap_icons

st.set_page_config(page_title="User", page_icon="👤", layout="centered")
ensure_bootstrap_icons()
render_sidebar()

# Bootstrap Icons (visual-only)
st.markdown(
    '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css">',
    unsafe_allow_html=True,
)

user = st.session_state.get("user")
if not user:
    st.info("Please log in to view your profile.")
    st.switch_page("pages/0_Login.py")

profile = get_profile(user["id"]) or {}

name = (profile.get("name") or profile.get("full_name") or "").strip()
email = user.get("email") or ""
avatar = profile.get("avatar_url") or profile.get("photo_url") or profile.get("picture_url")

st.markdown(f"# {bi('person-badge')} User profile", unsafe_allow_html=True)

col1, col2 = st.columns([1, 2], gap="large")
with col1:
    if avatar:
        st.image(avatar, use_container_width=True)
    else:
        st.markdown("###")
        st.markdown(f"{bi('person-circle', '3em')} ", unsafe_allow_html=True)
        st.caption("No photo available")

with col2:
    st.markdown(f"**Name:** {name if name else '—'}")
    st.markdown(f"**Email:** {email}")
    st.markdown(f"**Role:** {st.session_state.get('role', 'user')}")
