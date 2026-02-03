import streamlit as st
from typing import Optional, Tuple, Dict, Any
from core.supabase_client import auth_sign_out


from core.sidebar_ui import ensure_bootstrap_icons, bi


def _normalize_user_session() -> None:
    """Some older code paths stored a user object. Normalize to dict."""
    u = st.session_state.get("user")
    if u is not None and not isinstance(u, dict):
        st.session_state["user"] = {"id": getattr(u, "id", None), "email": getattr(u, "email", None)}


def get_user_and_role() -> Tuple[Optional[Dict[str, Any]], str]:
    _normalize_user_session()
    user = st.session_state.get("user")
    role = st.session_state.get("role", "user")
    return user, role


def require_login(redirect_page: str = "pages/0_Login.py") -> Dict[str, Any]:
    user, _ = get_user_and_role()
    if not user:
        st.switch_page(redirect_page)
    return user  # type: ignore


def require_admin() -> None:
    _, role = get_user_and_role()
    if role != "admin":
        st.error("Admin access required.")
        st.stop()


def sidebar_nav(app_title: str = "D+ Chatbot") -> Tuple[Optional[Dict[str, Any]], str]:
    """Render the shared sidebar (icons + nav). Returns (user, role)."""
    ensure_bootstrap_icons()
    user, role = get_user_and_role()

    st.sidebar.markdown(f"## {app_title}")

    # User chip / login link
    if user:
        email = (user.get("email") or user.get("id") or "unknown") if isinstance(user, dict) else "unknown"
        st.sidebar.markdown(f"{bi('person-circle')} **{email}**", unsafe_allow_html=True)
        st.sidebar.caption(f"Role: {role}")
        if st.sidebar.button("Logout", key="global_logout", use_container_width=True):
            auth_sign_out()
            st.session_state.clear()
            st.rerun()
    else:
        st.sidebar.info("You are not logged in.")
        st.sidebar.page_link("pages/0_Login.py", label="Go to Login")

    st.sidebar.markdown("---")
    st.sidebar.caption("Navigation")

    def _row(icon: str, label: str, page: str) -> None:
        c1, c2 = st.sidebar.columns([1, 10], gap="small")
        with c1:
            st.markdown(bi(icon), unsafe_allow_html=True)
        with c2:
            st.page_link(page, label=label)

    _row("chat-square-text", "Chat", "pages/1_Chat.py")
    _row("clock-history", "History", "pages/2_History.py")
    _row("person-badge", "User", "pages/5_User.py")

    # Option A: hide admin links unless admin
    if role == "admin":
        st.sidebar.markdown("---")
        st.sidebar.caption("Admin")
        _row("people", "Admin — Users", "pages/2_Admin_Users.py")
        _row("folder2-open", "Admin — Data", "pages/3_Admin_Data.py")
        _row("cpu", "Admin — Model", "pages/4_Admin_Model.py")

    return user, role