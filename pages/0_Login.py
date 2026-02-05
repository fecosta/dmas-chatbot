import os
import urllib.parse
import base64
import hashlib
import secrets

import streamlit as st

from core.sidebar_ui import bi, ensure_bootstrap_icons, render_sidebar
from core.supabase_client import (
    auth_sign_in,
    ensure_profile,
    normalize_site_url,
    oauth_pop_state,
    oauth_store_state,
    supabase_anon_client,
)


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


# --- Google OAuth (PKCE) ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SITE_URL_RAW = os.environ.get("SITE_URL", "https://chat.democraciamas.com")
SITE_URL = normalize_site_url(SITE_URL_RAW) or "https://chat.democraciamas.com"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _make_pkce() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("utf-8")).digest())
    return verifier, challenge


# Handle OAuth return (?code=...&oauth_nonce=...)
code = st.query_params.get("code")
oauth_nonce = st.query_params.get("oauth_nonce")
if code and oauth_nonce:
    try:
        code_verifier = oauth_pop_state(oauth_nonce)
        if not code_verifier:
            st.error(
                "Google login callback is missing oauth nonce. "
                "This can happen if the state expired. Please try again."
            )
            st.stop()

        supabase = supabase_anon_client()
        session = supabase.auth.exchange_code_for_session(
            {"auth_code": code, "code_verifier": code_verifier}
        )

        # Support different supabase-py return shapes
        user_obj = getattr(session, "user", None) or getattr(getattr(session, "session", None), "user", None)
        if not user_obj and isinstance(session, dict):
            user_obj = session.get("user") or (session.get("session") or {}).get("user")

        if not user_obj:
            st.error("Google login succeeded but no user was returned.")
            st.stop()

        user_id = getattr(user_obj, "id", None) or user_obj.get("id")
        email = getattr(user_obj, "email", None) or user_obj.get("email")

        st.session_state["user"] = {"id": user_id, "email": email}
        profile = ensure_profile(user_id, email or "")
        st.session_state["role"] = profile.get("role", "user")

        # Clear the callback params so reruns don't re-exchange
        st.query_params.clear()

        st.success("Logged in with Google.")
        st.switch_page("pages/1_Chat.py")
    except Exception as e:
        st.error(f"Google login failed: {e}")
        st.stop()


# Render OAuth button (start PKCE)
if SUPABASE_URL:
    oauth_nonce = secrets.token_urlsafe(32)
    code_verifier, code_challenge = _make_pkce()

    # Store verifier so we can exchange after redirect
    oauth_store_state(oauth_nonce, code_verifier)

    # We do NOT override Supabase's OAuth `state` (it is signed/managed by Supabase).
    # Instead, we pass our own nonce via redirect_to so we can retrieve the PKCE verifier.
    redirect_to = f"{SITE_URL}/?oauth_nonce={urllib.parse.quote(oauth_nonce, safe='')}"

    google_oauth_url = (
        f"{SUPABASE_URL}/auth/v1/authorize"
        f"?provider=google"
        f"&response_type=code"
        f"&redirect_to={urllib.parse.quote(redirect_to, safe='')}"
        f"&code_challenge={urllib.parse.quote(code_challenge, safe='')}"
        f"&code_challenge_method=s256"
    )

    st.markdown(
        f"""
        <a href=\"{google_oauth_url}\" style=\"text-decoration:none;\">
          <button style=\"
            width: 100%;
            padding: 0.7rem;
            border-radius: 10px;
            border: 1px solid #ddd;
            background: white;
            font-size: 16px;
            cursor: pointer;
            margin-bottom: 0.75rem;
          \">
            <i class=\"bi bi-google\" style=\"margin-right:8px;\"></i>
            Continue with Google
          </button>
        </a>
        """,
        unsafe_allow_html=True,
    )
else:
    st.warning("Google login is not configured: missing SUPABASE_URL environment variable.")

st.divider()


# --- Email/password fallback ---
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
