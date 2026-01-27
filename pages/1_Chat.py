import os
import streamlit as st
from anthropic import Anthropic
from openai import OpenAI
from supabase_auth.errors import AuthApiError

from core.supabase_client import (
    auth_sign_in,
    auth_sign_out,
    ensure_profile,
    list_documents,
    rpc_match_sections,
    svc,
)

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

EMBED_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")

# Prefer env var, but fall back to commonly available "latest" aliases.
_CLAUDE_ENV = os.environ.get("CLAUDE_MODEL", "").strip()
CLAUDE_MODELS = [m for m in [_CLAUDE_ENV, "claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"] if m]

oai = OpenAI(api_key=OPENAI_API_KEY)
claude = Anthropic(api_key=ANTHROPIC_API_KEY)

st.set_page_config(page_title="Chat", page_icon="💬", layout="wide")


def _user_email(u) -> str:
    if isinstance(u, dict):
        return u.get("email") or u.get("id") or "unknown"
    return getattr(u, "email", None) or getattr(u, "id", None) or "unknown"


def sidebar_auth() -> None:
    st.sidebar.header("Login")

    # Normalize any older session shapes
    if st.session_state.get("user") is not None and not isinstance(st.session_state["user"], dict):
        u = st.session_state["user"]
        st.session_state["user"] = {"id": getattr(u, "id", None), "email": getattr(u, "email", None)}

    if st.session_state.get("user"):
        u = st.session_state["user"]
        st.sidebar.success(f"Logged in: {_user_email(u)}")
        if st.sidebar.button("Logout", key="chat_logout"):
            try:
                auth_sign_out()
            finally:
                st.session_state.clear()
                st.rerun()
        return

    email = st.sidebar.text_input("Email", key="chat_login_email")
    password = st.sidebar.text_input("Password", type="password", key="chat_login_password")

    if st.sidebar.button("Login", key="chat_login_btn"):
        try:
            res = auth_sign_in(email, password)
        except AuthApiError:
            st.sidebar.error("Invalid email or password.")
            st.stop()

        u = res["user"]
        user = {
            "id": u.id,
            "email": getattr(u, "email", None) or None,
        }
        st.session_state["user"] = user

        # Ensure profile exists (FK required by conversations)
        profile = ensure_profile(user["id"], user.get("email") or "")
        st.session_state["role"] = (profile or {}).get("role", "user")
        st.rerun()


def get_or_create_conversation(user_id: str) -> str:
    if st.session_state.get("conversation_id"):
        return st.session_state["conversation_id"]

    r = svc.table("conversations").insert({"user_id": user_id, "title": "Chat"}).execute()
    cid = r.data[0]["id"]
    st.session_state["conversation_id"] = cid
    return cid


def embed_query(q: str):
    resp = oai.embeddings.create(model=EMBED_MODEL, input=q)
    return resp.data[0].embedding


sidebar_auth()
user = st.session_state.get("user")
if not user:
    st.title("💬 D+ Chatbot")
    st.info("Please log in to continue.")
    st.stop()

# Safety net: ensure profile exists even if session was restored
ensure_profile(user["id"], user.get("email") or "")

user_id = user["id"]
role = st.session_state.get("role", "user")
is_admin = role == "admin"

st.title("💬 D+ Chatbot")

# Document filter (optional)
docs = list_documents(admin=is_admin, user_id=user_id)
ready_docs = [d for d in docs if d.get("status") == "ready"]

doc_options = {f"{d.get('filename','')} — {str(d.get('id'))[:8]}": d["id"] for d in ready_docs if d.get("id")}

with st.sidebar:
    st.subheader("Sources")
    selected_labels = st.multiselect(
        "Limit retrieval to selected documents",
        options=list(doc_options.keys()),
        default=[],
        key="chat_doc_filter",
    )
    filter_doc_ids = [doc_options[x] for x in selected_labels] if selected_labels else None
    top_k = st.slider("Retrieved chunks", 3, 15, 8, key="chat_topk")

cid = get_or_create_conversation(user_id)

# Load messages from DB
msgs = (
    svc.table("messages")
    .select("*")
    .eq("conversation_id", cid)
    .order("created_at", desc=False)
    .execute()
    .data
    or []
)

for m in msgs:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

prompt = st.chat_input("Ask a question…")
if prompt:
    # store user msg
    svc.table("messages").insert({"conversation_id": cid, "role": "user", "content": prompt}).execute()
    with st.chat_message("user"):
        st.markdown(prompt)

    # retrieve context
    q_emb = embed_query(prompt)
    hits = rpc_match_sections(q_emb, k=top_k, filter_document_ids=filter_doc_ids)

    context_blocks = []
    for i, h in enumerate(hits or [], start=1):
        context_blocks.append(
            f"[{i}] {h.get('path','')}\nPages {h.get('page_start')}–{h.get('page_end')}\n{h.get('content','')}"
        )

    system = (
        "You are Democracia+’s assistant. Answer using ONLY the provided sources when possible. "
        "If the sources don’t contain the answer, say what’s missing and suggest what document would help."
    )

    user_message = (
        f"QUESTION:\n{prompt}\n\nSOURCES:\n" + ("\n\n".join(context_blocks) if context_blocks else "(none)")
    )

    # Claude answer with fallback models (prevents hard 404s)
    answer = ""
    last_err = None
    for model in CLAUDE_MODELS:
        try:
            resp = claude.messages.create(
                model=model,
                max_tokens=900,
                temperature=0.2,
                system=system,
                messages=[{"role": "user", "content": user_message}],
            )
            answer = resp.content[0].text if resp.content else ""
            break
        except Exception as e:
            last_err = e

    if not answer:
        raise RuntimeError(f"Claude call failed for models={CLAUDE_MODELS}. Last error: {last_err}")

    # store assistant msg
    svc.table("messages").insert({"conversation_id": cid, "role": "assistant", "content": answer}).execute()

    with st.chat_message("assistant"):
        st.markdown(answer)

        if hits:
            with st.expander("Sources used"):
                for i, h in enumerate(hits, start=1):
                    st.markdown(f"**[{i}]** {h.get('path','')}")
                    sim = h.get("similarity")
                    if sim is not None:
                        st.caption(f"Pages {h.get('page_start')}–{h.get('page_end')} • similarity {float(sim):.3f}")
                    else:
                        st.caption(f"Pages {h.get('page_start')}–{h.get('page_end')}")
                    snippet = (h.get("content", "")[:700] + ("…" if len(h.get("content", "")) > 700 else ""))
                    st.text(snippet)
