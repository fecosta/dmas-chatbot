import os
import json
from datetime import datetime

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

# Environment defaults (Admin → Model can override at runtime)
ENV_EMBED_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small").strip()
ENV_CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "").strip()

DEFAULTS = {
    # Embeddings / retrieval
    "embedding_model": ENV_EMBED_MODEL,
    "top_k": 8,
    "min_score": 0.0,
    "max_context_chars": 18000,
    # LLM
    "claude_model_primary": ENV_CLAUDE_MODEL or "claude-3-5-sonnet-latest",
    "claude_model_fallbacks": ["claude-3-5-haiku-latest"],
    "claude_max_tokens": 900,
    "claude_temperature": 0.2,
    # Prompt / UX
    "system_prompt": (
        "You are Democracia+’s assistant. Answer using ONLY the provided sources when possible. "
        "If the sources don’t contain the answer, say what’s missing and suggest what document would help."
    ),
    "answer_style": "concise",  # concise|balanced|detailed
    "include_citations": True,
}

oai = OpenAI(api_key=OPENAI_API_KEY)
claude = Anthropic(api_key=ANTHROPIC_API_KEY)

st.set_page_config(page_title="Chat", page_icon="💬", layout="wide")


def _user_email(u) -> str:
    if isinstance(u, dict):
        return u.get("email") or u.get("id") or "unknown"
    return getattr(u, "email", None) or getattr(u, "id", None) or "unknown"


def _style_instruction(style: str) -> str:
    style = (style or "").strip().lower()
    if style == "detailed":
        return "Write a detailed, structured answer with headings and bullet points where helpful."
    if style == "balanced":
        return "Write a clear answer with brief structure and 1–2 short bullets if helpful."
    return "Be concise and direct. Use short paragraphs."


def _safe_dt_label(iso_ts: str | None) -> str:
    if not iso_ts:
        return ""
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso_ts[:16]


def _load_model_settings() -> dict:
    """Load global model settings from Supabase. Falls back to safe defaults."""
    try:
        rows = (
            svc.table("model_settings")
            .select("*")
            .eq("scope", "global")
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception:
        rows = []

    if not rows:
        return dict(DEFAULTS)

    s = rows[0] or {}

    primary = (s.get("claude_model_primary") or s.get("claude_model") or DEFAULTS["claude_model_primary"]).strip()

    fallbacks = DEFAULTS["claude_model_fallbacks"]
    raw = s.get("claude_model_fallbacks_json")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
                fallbacks = parsed
        except Exception:
            pass

    embed_model = (s.get("embedding_model") or DEFAULTS["embedding_model"]).strip()
    top_k = int(s.get("top_k") or DEFAULTS["top_k"])
    min_score = float(s.get("min_score") or DEFAULTS["min_score"])
    max_context_chars = int(s.get("max_context_chars") or DEFAULTS["max_context_chars"])

    max_tokens = int(s.get("claude_max_tokens") or DEFAULTS["claude_max_tokens"])
    temperature = float(
        s.get("claude_temperature") if s.get("claude_temperature") is not None else DEFAULTS["claude_temperature"]
    )

    system_prompt = s.get("system_prompt") or DEFAULTS["system_prompt"]
    answer_style = str(s.get("answer_style") or DEFAULTS["answer_style"])
    include_citations = bool(
        s.get("include_citations") if s.get("include_citations") is not None else DEFAULTS["include_citations"]
    )

    return {
        "embedding_model": embed_model,
        "top_k": max(1, min(50, top_k)),
        "min_score": max(0.0, min(1.0, min_score)),
        "max_context_chars": max(2000, min(100000, max_context_chars)),
        "claude_models": [m for m in [primary, *fallbacks] if m],
        "claude_max_tokens": max(128, min(4000, max_tokens)),
        "claude_temperature": max(0.0, min(1.0, temperature)),
        "system_prompt": system_prompt,
        "answer_style": answer_style,
        "include_citations": include_citations,
    }


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
        user = {"id": u.id, "email": getattr(u, "email", None) or None}
        st.session_state["user"] = user

        profile = ensure_profile(user["id"], user.get("email") or "")
        st.session_state["role"] = (profile or {}).get("role", "user")
        st.rerun()


def list_conversations_for_user(user_id: str) -> list[dict]:
    try:
        return (
            svc.table("conversations")
            .select("id,title,created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(200)
            .execute()
            .data
            or []
        )
    except Exception:
        return []


def create_conversation(user_id: str, title: str = "Chat") -> str:
    r = svc.table("conversations").insert({"user_id": user_id, "title": title}).execute()
    cid = r.data[0]["id"]
    st.session_state["conversation_id"] = cid
    return cid


def get_or_create_conversation(user_id: str) -> str:
    if st.session_state.get("conversation_id"):
        return st.session_state["conversation_id"]

    convs = list_conversations_for_user(user_id)
    if convs:
        st.session_state["conversation_id"] = convs[0]["id"]
        return convs[0]["id"]

    return create_conversation(user_id, title="Chat")


def embed_query(q: str, embed_model: str):
    resp = oai.embeddings.create(model=embed_model, input=q)
    return resp.data[0].embedding


# ---------- App start ----------

sidebar_auth()
user = st.session_state.get("user")
if not user:
    st.title("💬 D+ Chatbot")
    st.info("Please log in to continue.")
    st.stop()

ensure_profile(user["id"], user.get("email") or "")

user_id = user["id"]
role = st.session_state.get("role", "user")
is_admin = role == "admin"

settings = _load_model_settings()

if is_admin and settings["embedding_model"] != ENV_EMBED_MODEL:
    st.warning(
        "Admin note: Embedding model differs from the environment default. "
        "Changing embedding models requires re-embedding documents to maintain retrieval quality."
    )

# Sidebar: conversation list + new chat
with st.sidebar:
    st.markdown("---")
    st.subheader("Conversations")

    convs = list_conversations_for_user(user_id)
    labels: list[str] = []
    id_by_label: dict[str, str] = {}

    for c in convs:
        title = (c.get("title") or "Chat").strip()
        when = _safe_dt_label(c.get("created_at"))
        label = f"{title} · {when}" if when else title
        if label in id_by_label:
            label = f"{label} · {str(c.get('id',''))[:6]}"
        labels.append(label)
        if c.get("id"):
            id_by_label[label] = c["id"]

    current_id = st.session_state.get("conversation_id")
    current_label = None
    if current_id:
        for lbl, cid in id_by_label.items():
            if cid == current_id:
                current_label = lbl
                break

    if st.button("+ New chat", key="chat_new_chat"):
        create_conversation(user_id, title="Chat")
        st.rerun()

    if labels:
        picked = st.selectbox(
            "Select a conversation",
            options=labels,
            index=labels.index(current_label) if current_label in labels else 0,
            key="chat_conv_pick",
            label_visibility="collapsed",
        )
        picked_id = id_by_label.get(picked)
        if picked_id and picked_id != st.session_state.get("conversation_id"):
            st.session_state["conversation_id"] = picked_id
            st.rerun()
    else:
        st.caption("No conversations yet. Click “New chat”.")

st.title("💬 D+ Chatbot")

# (No UI filters here; we keep docs available for future admin-only tooling)
docs = list_documents(admin=is_admin, user_id=user_id)
_ = [d for d in docs if d.get("status") == "ready"]

cid = get_or_create_conversation(user_id)

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
    svc.table("messages").insert({"conversation_id": cid, "role": "user", "content": prompt}).execute()
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Searching documents…"):
            q_emb = embed_query(prompt, settings["embedding_model"])
            hits = rpc_match_sections(q_emb, k=int(settings["top_k"]), filter_document_ids=None)

        # Similarity threshold
        if isinstance(hits, list) and settings.get("min_score", 0.0) > 0:
            ms = float(settings["min_score"])
            filtered = []
            for h in hits:
                if not isinstance(h, dict):
                    continue
                sim = h.get("similarity")
                if sim is None:
                    filtered.append(h)
                else:
                    try:
                        if float(sim) >= ms:
                            filtered.append(h)
                    except Exception:
                        filtered.append(h)
            hits = filtered

        max_chars = int(settings.get("max_context_chars", DEFAULTS["max_context_chars"]))
        sources = []
        used_chars = 0

        for i, h in enumerate(hits or [], start=1):
            if not isinstance(h, dict):
                continue
            txt = (h.get("content") or h.get("text") or "").strip()
            if not txt:
                continue

            path = (h.get("path") or h.get("section_path") or h.get("filename") or "Source").strip()
            doc_id = h.get("document_id") or h.get("doc_id")
            header = f"[{i}] {path}"
            if doc_id:
                header += f" (doc {str(doc_id)[:8]})"

            chunk = f"{header}\n{txt}"
            if used_chars + len(chunk) > max_chars:
                break
            used_chars += len(chunk) + 2
            sources.append(chunk)

        if not sources:
            answer = (
                "I couldn’t find relevant information in the uploaded documents to answer that. "
                "Try rephrasing your question or upload a document that covers this topic."
            )
            st.markdown(answer)
            svc.table("messages").insert({"conversation_id": cid, "role": "assistant", "content": answer}).execute()
        else:
            sys = settings["system_prompt"].strip() + "\n\n" + _style_instruction(settings.get("answer_style", "concise"))
            ctx = "\n\n".join(sources)
            user_msg = f"QUESTION:\n{prompt}\n\nSOURCES:\n{ctx}\n\nAnswer using the sources above."

            models = settings.get("claude_models") or [
                DEFAULTS["claude_model_primary"],
                *DEFAULTS["claude_model_fallbacks"],
            ]

            answer = ""
            last_err = None
            with st.spinner("Writing answer…"):
                for model in models:
                    try:
                        resp = claude.messages.create(
                            model=model,
                            max_tokens=int(settings["claude_max_tokens"]),
                            temperature=float(settings["claude_temperature"]),
                            system=sys,
                            messages=[{"role": "user", "content": user_msg}],
                        )
                        answer = resp.content[0].text if resp.content else ""
                        if answer:
                            break
                    except Exception as e:
                        last_err = e

            if not answer:
                raise RuntimeError(f"Claude call failed for models={models}. Last error: {last_err}")

            st.markdown(answer)
            svc.table("messages").insert({"conversation_id": cid, "role": "assistant", "content": answer}).execute()

            if settings.get("include_citations", True):
                with st.expander("Sources used", expanded=False):
                    for s in sources:
                        st.markdown(s)