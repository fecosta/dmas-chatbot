import streamlit as st
from core.supabase_client import auth_sign_out, get_profile

def ensure_bootstrap_icons() -> None:
    """Load Bootstrap Icons once per Streamlit session.

    Streamlit can re-run scripts many times per session; this guard prevents
    repeated <link> injections across pages.
    """
    if st.session_state.get("_bootstrap_icons_loaded"):
        return
    st.markdown(
        '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css">',
        unsafe_allow_html=True,
    )
    st.session_state["_bootstrap_icons_loaded"] = True


def bi(name: str, size: str = "1em") -> str:
    return f'<i class="bi bi-{name}" style="font-size:{size}; vertical-align:-0.125em;"></i>'

def nav_item(icon: str, label: str, page: str):
    # icon + page link in one row
    c1, c2 = st.sidebar.columns([1, 9], gap="small")
    with c1:
        st.markdown(bi(icon), unsafe_allow_html=True)
    with c2:
        st.page_link(page, label=label)

def render_sidebar(app_title="D+ Chat"):
    ensure_bootstrap_icons()

    user = st.session_state.get("user")
    role = st.session_state.get("role", "user")

    st.sidebar.markdown(f"## {app_title}")

    # --- User chip (or login CTA) ---
    if user:
        profile = get_profile(user["id"]) or {}
        name = (profile.get("name") or profile.get("full_name") or "").strip()
        email = user.get("email") or ""
        display = name if name else email

        st.sidebar.markdown(f"{bi('person-circle')} **{display}**", unsafe_allow_html=True)
        st.sidebar.caption(f"Role: {role}")

        if st.sidebar.button("Logout", use_container_width=True):
            auth_sign_out()
            st.session_state.clear()
            st.rerun()
    else:
        st.sidebar.info("You are not logged in.")
        st.sidebar.page_link("pages/0_Login.py", label="Go to Login")

    st.sidebar.markdown("---")

    # --- Navigation ---
    st.sidebar.caption("Navigation")
    nav_item("chat-square-text", "Chat", "pages/1_Chat.py")
    nav_item("clock-history", "History", "pages/2_History.py")
    # nav_item("person-badge", "User", "pages/5_User.py")

    st.sidebar.markdown("---")
    st.sidebar.caption("Admin")
    if role == "admin":
        nav_item("people", "Admin — Users", "pages/2_Admin_Users.py")
        nav_item("folder2-open", "Admin — Data", "pages/3_Admin_Data.py")
        nav_item("cpu", "Admin — Model", "pages/4_Admin_Model.py")
    else:
        st.sidebar.caption("Admin pages are available to admins only.")

    st.sidebar.markdown("---")
    st.sidebar.caption("Legal")
    nav_item("file-text", "Privacy Policy", "pages/9_Privacy.py")