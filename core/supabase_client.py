import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import streamlit as st

import requests
from urllib.parse import urlsplit

import extra_streamlit_components as stx

from supabase import create_client, Client

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/") + "/"
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

# Server-side client (bypasses RLS). Use this in worker and server operations.
svc: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# Client-side-ish (still server in Streamlit, but uses anon + email/pass auth)
anon: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# Required table in Supabase (SQL):
# create table if not exists oauth_states (
#   state text primary key,
#   code_verifier text not null,
#   created_at timestamptz not null default now()
# );


def storage_upload(bucket: str, path: str, content: bytes, content_type: str = "application/pdf") -> None:
    # Supabase Python API uses .storage.from_(bucket).upload(...)
    # upsert=True to avoid collisions on retries (we use sha-based filenames)
    svc.storage.from_(bucket).upload(
        path=path,
        file=content,
        file_options={"content-type": content_type, "x-upsert": "true"},
    )


def storage_download(bucket: str, path: str) -> bytes:
    # Use service role to download private objects reliably
    return svc.storage.from_(bucket).download(path)


def storage_remove(bucket: str, paths: List[str]) -> None:
    if not paths:
        return
    svc.storage.from_(bucket).remove(paths)


# ---------------- Auth helpers ----------------

def auth_sign_in(email: str, password: str) -> Dict[str, Any]:
    res = anon.auth.sign_in_with_password({"email": email, "password": password})
    # res.user, res.session
    return {"user": res.user, "session": res.session}


def auth_sign_out() -> None:
    try:
        anon.auth.sign_out()
    except Exception:
        pass


def supabase_anon_client() -> Client:
    """Return an anon-key Supabase client (used for PKCE code exchange)."""
    return anon


# ---------------- Session persistence (cookies) ----------------

_COOKIE_PREFIX = "dplus_auth_"
_COOKIE_MANAGER_STATE_KEY = "_dplus_cookie_manager"
_COOKIE_MANAGER_COMPONENT_KEY = "dplus_cookie_manager"  # must be unique app-wide


def _cookie_manager():
    """Return a singleton CookieManager to avoid StreamlitDuplicateElementKey('init')."""
    cm = st.session_state.get(_COOKIE_MANAGER_STATE_KEY)
    if cm is None:
        cm = stx.CookieManager(key=_COOKIE_MANAGER_COMPONENT_KEY)
        st.session_state[_COOKIE_MANAGER_STATE_KEY] = cm
    return cm


def save_supabase_session(session) -> None:
    """Persist Supabase session tokens in cookies."""
    cm = _cookie_manager()

    access_token = getattr(session, "access_token", None) or session.get("access_token")
    refresh_token = getattr(session, "refresh_token", None) or session.get("refresh_token")
    expires_at = getattr(session, "expires_at", None) or session.get("expires_at")

    max_age = 30 * 24 * 60 * 60  # 30 days
    cookie_path = "/"  # IMPORTANT: share across /Login, /Chat, etc.

    if access_token:
        cm.set(
            f"{_COOKIE_PREFIX}access_token",
            access_token,
            key="dplus_set_access_token",
            path=cookie_path,
            max_age=max_age,
        )
    if refresh_token:
        cm.set(
            f"{_COOKIE_PREFIX}refresh_token",
            refresh_token,
            key="dplus_set_refresh_token",
            path=cookie_path,
            max_age=max_age,
        )
    if expires_at:
        cm.set(
            f"{_COOKIE_PREFIX}expires_at",
            str(expires_at),
            key="dplus_set_expires_at",
            path=cookie_path,
            max_age=max_age,
        )


def restore_supabase_session() -> Optional[Dict[str, Any]]:
    """Restore Supabase session from cookies and rehydrate st.session_state."""
    if st.session_state.get("user"):
        return st.session_state["user"]

    cm = _cookie_manager()
    access_token = cm.get(f"{_COOKIE_PREFIX}access_token", key="dplus_get_access_token")
    refresh_token = cm.get(f"{_COOKIE_PREFIX}refresh_token", key="dplus_get_refresh_token")
    expires_at_raw = cm.get(f"{_COOKIE_PREFIX}expires_at", key="dplus_get_expires_at")

    if not refresh_token:
        return None

    supabase = anon

    # refresh if needed
    try:
        expires_at = int(float(expires_at_raw)) if expires_at_raw else 0
    except Exception:
        expires_at = 0

    now = int(time.time())
    if not access_token or (expires_at and now >= expires_at - 30):
        refreshed = supabase.auth.refresh_session(refresh_token)
        session = getattr(refreshed, "session", None) or refreshed.get("session") or refreshed
        save_supabase_session(session)
        access_token = getattr(session, "access_token", None) or session.get("access_token")

    user_resp = supabase.auth.get_user(access_token)
    user_obj = getattr(user_resp, "user", None) or user_resp.get("user")

    if not user_obj:
        return None

    user_id = getattr(user_obj, "id", None) or user_obj.get("id")
    email = getattr(user_obj, "email", None) or user_obj.get("email")

    st.session_state["user"] = {"id": user_id, "email": email}
    profile = ensure_profile(user_id, email or "")
    st.session_state["role"] = profile.get("role", "user")
    return st.session_state["user"]


def clear_supabase_session() -> None:
    cm = _cookie_manager()
    cookie_path = "/"
    cm.delete(f"{_COOKIE_PREFIX}access_token", key="dplus_del_access_token", path=cookie_path)
    cm.delete(f"{_COOKIE_PREFIX}refresh_token", key="dplus_del_refresh_token", path=cookie_path)
    cm.delete(f"{_COOKIE_PREFIX}expires_at", key="dplus_del_expires_at", path=cookie_path)
    st.session_state.pop("user", None)
    st.session_state.pop("role", None)


_OAUTH_STATE_TABLE = os.environ.get("DPLUS_OAUTH_STATE_TABLE", "oauth_states")
_OAUTH_STATE_TTL_SECONDS = int(os.environ.get("DPLUS_OAUTH_STATE_TTL_SECONDS", "900"))  # 15 min


def oauth_store_state(state: str, code_verifier: str) -> None:
    """Store PKCE verifier keyed by state so Streamlit can exchange after redirect."""
    svc.table(_OAUTH_STATE_TABLE).upsert(
        {
            "state": state,
            "code_verifier": code_verifier,
        }
    ).execute()


def oauth_pop_state(state: str) -> Optional[str]:
    """Fetch and delete the PKCE verifier for a given state. Returns None if missing/expired."""
    res = (
        svc.table(_OAUTH_STATE_TABLE)
        .select("code_verifier, created_at")
        .eq("state", state)
        .maybe_single()
        .execute()
    )

    data = getattr(res, "data", None) or (res.get("data") if isinstance(res, dict) else None)
    if not data:
        return None

    created_at = data.get("created_at")
    created_at_dt = None
    if isinstance(created_at, str) and created_at:
        try:
            # Supabase returns ISO8601 strings, often ending with 'Z'
            created_at_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except Exception:
            created_at_dt = None

    if created_at_dt is not None:
        age_seconds = (datetime.now(timezone.utc) - created_at_dt.astimezone(timezone.utc)).total_seconds()
        if age_seconds > _OAUTH_STATE_TTL_SECONDS:
            svc.table(_OAUTH_STATE_TABLE).delete().eq("state", state).execute()
            return None

    # delete after read
    svc.table(_OAUTH_STATE_TABLE).delete().eq("state", state).execute()
    return data.get("code_verifier")


def normalize_site_url(raw: str) -> str:
    """Normalize a SITE_URL for use as Supabase `redirect_to`.

    We only keep scheme + host (+ optional base path) and drop any extra
    multipage/route fragments like `/Chat/oauth/consent`.
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        return raw.rstrip("/")
    # Keep origin only (most reliable with Supabase allowlist)
    return f"{parts.scheme}://{parts.netloc}".rstrip("/")


def auth_user_from_access_token(access_token: str) -> Dict[str, Any]:
    """Fetch user info for an OAuth access token (implicit flow)."""
    url = SUPABASE_URL.rstrip("/") + "/auth/v1/user"
    r = requests.get(
        url,
        headers={
            "apikey": SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {access_token}",
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def get_profile(user_id: str) -> Optional[Dict[str, Any]]:
    r = svc.table("profiles").select("*").eq("id", user_id).limit(1).execute()
    if r.data:
        return r.data[0]
    return None


# ---------------- DB helpers ----------------

def ensure_profile(user_id: str, email: str) -> Dict[str, Any]:
    # Upsert profile row
    svc.table("profiles").upsert({"id": user_id, "email": email}).execute()
    return get_profile(user_id) or {"id": user_id, "email": email, "role": "user"}


def create_event(user_id: Optional[str], action: str, document_id: Optional[str] = None, details: Optional[Dict[str, Any]] = None) -> None:
    svc.table("events").insert({
        "user_id": user_id,
        "action": action,
        "document_id": document_id,
        "details": details or {},
    }).execute()


def list_documents(admin: bool, user_id: str) -> List[Dict[str, Any]]:
    q = svc.table("documents").select("*").neq("status", "deleted").order("created_at", desc=True)
    if not admin:
        q = q.eq("owner_id", user_id)
    return q.execute().data or []


def insert_document(owner_id: str, filename: str, sha256: str, bucket: str, storage_path: str) -> Dict[str, Any]:
    r = svc.table("documents").insert({
        "owner_id": owner_id,
        "filename": filename,
        "sha256": sha256,
        "bucket": bucket,
        "storage_path": storage_path,
        "status": "uploaded",
    }).execute()
    return (r.data or [None])[0]


def find_document_by_sha256(sha256: str) -> Optional[Dict[str, Any]]:
    r = svc.table("documents").select("*").eq("sha256", sha256).neq("status", "deleted").limit(1).execute()
    if r.data:
        return r.data[0]
    return None


def update_document_status(doc_id: str, status: str, error: Optional[str] = None) -> None:
    payload: Dict[str, Any] = {"status": status}

    # PostgREST expects concrete timestamp values; avoid SQL-function strings like "now()".
    now_iso = datetime.now(timezone.utc).isoformat()

    if status == "ready":
        payload["processed_at"] = now_iso
        payload["error"] = None
    elif status == "failed":
        payload["error"] = error or "unknown"
    elif status == "deleted":
        payload["deleted_at"] = now_iso

    svc.table("documents").update(payload).eq("id", doc_id).execute()


def delete_document(doc_id: str) -> None:
    # soft delete + cascade deletes sections via FK if you actually delete doc row;
    # we keep row but mark deleted, and manually delete sections.
    svc.table("sections").delete().eq("document_id", doc_id).execute()
    update_document_status(doc_id, "deleted")


def insert_sections_with_embeddings(doc_id: str, sections: List[Dict[str, Any]]) -> None:
    # sections: list of {path,page_start,page_end,content,embedding}
    # Insert in batches to avoid payload limits.
    batch_size = 50
    for i in range(0, len(sections), batch_size):
        svc.table("sections").insert([
            {
                "document_id": doc_id,
                "path": s.get("path"),
                "page_start": s.get("page_start"),
                "page_end": s.get("page_end"),
                "content": s["content"],
                "embedding": s.get("embedding"),
            }
            for s in sections[i:i+batch_size]
        ]).execute()


def rpc_match_sections(query_embedding: List[float], k: int = 8, filter_document_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    payload = {
        "query_embedding": query_embedding,
        "match_count": int(k),
        "filter_document_ids": filter_document_ids,
    }
    r = svc.rpc("match_sections", payload).execute()
    return r.data or []
