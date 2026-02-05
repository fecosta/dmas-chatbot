import time
import streamlit as st
import extra_streamlit_components as stx
from core.supabase_client import supabase_anon_client, ensure_profile

COOKIE_PREFIX = "dplus_auth_"

_COOKIE_MANAGER_STATE_KEY = "_dplus_cookie_manager"
_COOKIE_MANAGER_COMPONENT_KEY = "dplus_cookie_manager"  # must match core/supabase_client.py


def cookie_manager():
    cm = st.session_state.get(_COOKIE_MANAGER_STATE_KEY)
    if cm is None:
        cm = stx.CookieManager(key=_COOKIE_MANAGER_COMPONENT_KEY)
        st.session_state[_COOKIE_MANAGER_STATE_KEY] = cm
    return cm

def save_supabase_session(session):
    """
    session: supabase-py session object or dict containing access_token/refresh_token/expires_at
    """
    cm = cookie_manager()

    access_token = getattr(session, "access_token", None) or session.get("access_token")
    refresh_token = getattr(session, "refresh_token", None) or session.get("refresh_token")
    expires_at = getattr(session, "expires_at", None) or session.get("expires_at")

    # store for ~30 days (you can tune)
    ttl_days = 30

    cm.set(f"{COOKIE_PREFIX}access_token", access_token, expires_at=ttl_days)
    cm.set(f"{COOKIE_PREFIX}refresh_token", refresh_token, expires_at=ttl_days)
    cm.set(f"{COOKIE_PREFIX}expires_at", str(expires_at or ""), expires_at=ttl_days)

def clear_session():
    cm = cookie_manager()
    for k in ["access_token", "refresh_token", "expires_at"]:
        cm.delete(f"{COOKIE_PREFIX}{k}")
    st.session_state.pop("user", None)
    st.session_state.pop("role", None)

def restore_session_if_needed():
    """
    Call this at the very top of every page (before auth guard).
    """
    if st.session_state.get("user"):
        return True

    cm = cookie_manager()
    access_token = cm.get(f"{COOKIE_PREFIX}access_token")
    refresh_token = cm.get(f"{COOKIE_PREFIX}refresh_token")
    expires_at_raw = cm.get(f"{COOKIE_PREFIX}expires_at")

    if not refresh_token:
        return False

    supabase = supabase_anon_client()

    # If token expired (or we can't parse), refresh it
    try:
        expires_at = int(float(expires_at_raw)) if expires_at_raw else 0
    except Exception:
        expires_at = 0

    now = int(time.time())
    needs_refresh = (not access_token) or (expires_at and now >= expires_at - 30)

    if needs_refresh:
        # refresh session
        refreshed = supabase.auth.refresh_session(refresh_token)
        sess = getattr(refreshed, "session", None) or refreshed.get("session") or refreshed
        save_supabase_session(sess)
        access_token = getattr(sess, "access_token", None) or sess.get("access_token")

    # fetch user using access token
    user = supabase.auth.get_user(access_token)
    user_obj = getattr(user, "user", None) or user.get("user")

    if not user_obj:
        clear_session()
        return False

    user_id = getattr(user_obj, "id", None) or user_obj.get("id")
    email = getattr(user_obj, "email", None) or user_obj.get("email")

    st.session_state["user"] = {"id": user_id, "email": email}
    profile = ensure_profile(user_id, email or "")
    st.session_state["role"] = profile.get("role", "user")
    return True