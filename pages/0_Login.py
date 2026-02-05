import os
import urllib.parse

import streamlit as st

from core.sidebar_ui import bi, ensure_bootstrap_icons, render_sidebar
from core.supabase_client import (
    auth_sign_in,
    auth_user_from_access_token,
    ensure_profile,
    normalize_site_url,
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


# --- OAuth return bridge ---
# Supabase implicit flow returns tokens in the URL fragment (#...), which Streamlit
# cannot read server-side. Convert any fragment to query params.
st.markdown(
    """
    <script>
      (function() {
        try {
          const hash = window.location.hash || "";
          if (!hash || hash.length < 2) return;

          const url = new URL(window.location.href);
          // Only run once
          if (url.searchParams.get('access_token')) return;

          // Convert '#a=b&c=d' -> '?a=b&c=d'
          url.search = hash.substring(1);
          url.hash = '';
          window.location.replace(url.toString());
        } catch (e) {
          // no-op
        }
      })();
    </script>
    """,
    unsafe_allow_html=True,
)


# If we came back from OAuth, we should now have ?access_token=... in the URL.
access_token = st.query_params.get("access_token")
if access_token:
    try:
        u = auth_user_from_access_token(access_token)
        user_id = u.get("id")
        email = u.get("email")
        if user_id:
            st.session_state["user"] = {"id": user_id, "email": email}
            profile = ensure_profile(user_id, email or "")
            st.session_state["role"] = profile.get("role", "user")
            st.query_params.clear()  # remove tokens from URL
            st.success("Logged in with Google.")
            st.switch_page("pages/1_Chat.py")
        else:
            st.warning("Google login returned no user id. Please try again.")
    except Exception as e:
        st.error(f"Google login failed: {e}")


if st.session_state.get("user"):
    st.success("You are already logged in.")
    st.page_link("pages/1_Chat.py", label="Go to Chat")
    st.stop()


# --- Google OAuth button ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SITE_URL_RAW = os.environ.get("SITE_URL", "https://chat.democraciamas.com")
SITE_URL = normalize_site_url(SITE_URL_RAW) or "https://chat.democraciamas.com"

if SUPABASE_URL:
    google_oauth_url = (
        f"{SUPABASE_URL}/auth/v1/authorize"
        f"?provider=google"
        f"&response_type=token"
        f"&redirect_to={urllib.parse.quote(SITE_URL, safe='')}"
    )

    st.markdown(
        f"""
        <a href="{google_oauth_url}" style="text-decoration:none;">
          <button style="
            width: 100%;
            padding: 0.7rem;
            border-radius: 10px;
            border: 1px solid #ddd;
            background: white;
            font-size: 16px;
            cursor: pointer;
            margin-bottom: 0.75rem;
          ">
            <i class="bi bi-google" style="margin-right:8px;"></i>
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
