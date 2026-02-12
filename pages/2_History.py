import streamlit as st
from core.sidebar_ui import ensure_bootstrap_icons, render_sidebar
from core.ui import apply_ui, sidebar_brand, page_header
from core.supabase_client import svc, ensure_profile, restore_supabase_session
from supabase_auth.errors import AuthApiError
from datetime import datetime

st.set_page_config(page_title="History", page_icon="./static/logo-dmas.svg", layout="centered")
ensure_bootstrap_icons()
render_sidebar()

# Bootstrap Icons (visual-only)
st.markdown(
    '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css">',
    unsafe_allow_html=True,
)

def bi(name: str, size: str = "1em") -> str:
    return f'<i class="bi bi-{name}" style="font-size:{size}; vertical-align:-0.125em;"></i>'

apply_ui()

def _safe_dt_label(iso_ts: str | None) -> str:
    if not iso_ts:
        return ""
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso_ts[:16]

def _user_email(u) -> str:
    if isinstance(u, dict):
        return u.get("email") or u.get("id") or "unknown"
    return getattr(u, "email", None) or getattr(u, "id", None) or "unknown"


def list_conversations_for_user(user_id: str) -> list[dict]:
    return (
        svc.table("conversations")
        .select("id,title,created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(500)
        .execute()
        .data
        or []
    )

# ------------------------- Auth -------------------------
restore_supabase_session()

user = st.session_state.get("user")
if not user:
    st.info("Please log in.")
    st.switch_page("pages/0_Login.py")
    st.stop()

ensure_profile(user["id"], user.get("email") or "")
user_id = user["id"]

st.markdown(f"# {bi('clock-history')} Conversation history", unsafe_allow_html=True)
st.caption("Browse and reopen past chats.")

colA, colB = st.columns([2, 1])
with colA:
    q = st.text_input("Search titles", placeholder="Type to filter…", key="history_search")
with colB:
    st.markdown(f"{bi('arrow-left')} ", unsafe_allow_html=True)
    if st.button("Back to Chat", key="history_back_chat", use_container_width=True):
        st.switch_page("pages/1_Chat.py")

convs = list_conversations_for_user(user_id)
if q.strip():
    qq = q.strip().lower()
    convs = [c for c in convs if (c.get("title") or "").lower().find(qq) >= 0]

if not convs:
    st.caption("No conversations found.")
    st.stop()

for c in convs:
    cid = c.get("id")
    title = (c.get("title") or "Chat").strip()
    when = _safe_dt_label(c.get("created_at"))

    with st.container(border=True):
        st.markdown(f"**{title}**")
        if when:
            st.caption(when)

        cols = st.columns([1, 1, 2])
        with cols[0]:
            if st.button("Open", key=f"history_open_{cid}"):
                st.session_state["conversation_id"] = cid
                st.switch_page("pages/1_Chat.py")
        with cols[1]:
            if st.button("Rename", key=f"history_rename_btn_{cid}"):
                st.session_state[f"rename_{cid}"] = True

        if st.session_state.get(f"rename_{cid}"):
            new_title = st.text_input("New title", value=title, key=f"history_rename_input_{cid}")
            c2 = st.columns([1, 1, 3])
            with c2[0]:
                if st.button("Save", key=f"history_rename_save_{cid}"):
                    svc.table("conversations").update({"title": new_title.strip() or "Chat"}).eq("id", cid).execute()
                    st.session_state.pop(f"rename_{cid}", None)
                    st.rerun()
            with c2[1]:
                if st.button("Cancel", key=f"history_rename_cancel_{cid}"):
                    st.session_state.pop(f"rename_{cid}", None)
                    st.rerun()