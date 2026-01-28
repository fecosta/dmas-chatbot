import os
import json
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
ENV_EMBED_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
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

    # Backward compat with older schema
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
    # Note: changing the embedding model without re-embedding documents will harm retrieval.
    # We accept the setting, but keep a safe fallback.
    top_k = int(s.get("top_k") or DEFAULTS["top_k"])
    min_score = float(s.get("min_score") or DEFAULTS["min_score"])
    max_context_chars = int(s.get("max_context_chars") or DEFAULTS["max_context_chars"])

    max_tokens = int(s.get("claude_max_tokens") or DEFAULTS["claude_max_tokens"])
    temperature = float(s.get("claude_temperature") if s.get("claude_temperature") is not None else DEFAULTS["claude_temperature"])

    system_prompt = s.get("system_prompt") or DEFAULTS["system_prompt"]
    answer_style = str(s.get("answer_style") or DEFAULTS["answer_style"])
    include_citations = bool(s.get("include_citations") if s.get("include_citations") is not None else DEFAULTS["include_citations"])

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


def embed_query(q: str, embed_model: str):
    resp = oai.embeddings.create(model=embed_model, input=q)
    return resp.data[0].embedding


def _style_instruction(style: str) -> str:
    style = (style or "").strip().lower()
    if style == "detailed":
        return "Write a detailed, structured answer with headings and bullet points where helpful."
    if style == "balanced":
        return "Write a clear answer with brief structure and 1–2 short bullets if helpful."
    return "Be concise and direct. Use short paragraphs."


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

settings = _load_model_settings()

# Optional: warn admins if the embedding model differs from the environment default
if is_admin and settings["embedding_model"] != ENV_EMBED_MODEL:
    st.warning(
        "Admin note: Embedding model differs from the environment default. "
        "Changing embedding models requires re-embedding documents to maintain retrieval quality."
    )

st.title("💬 D+ Chatbot")

# Keep for future use (admin-only doc listing), but no UI filters in Chat
docs = list_documents(admin=is_admin, user_id=user_id)
_ = [d for d in docs if d.get("status") == "ready"]  # ready_docs (unused, but keeps intent explicit)

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
    q_emb = embed_query(prompt, settings["embedding_model"])
    hits = rpc_match_sections(q_emb, k=int(settings["top_k"]), filter_document_ids=None)

    # Apply similarity threshold (if provided by RPC)
    if hits and settings["min_score"] > 0:
        filtered = []
        for h in hits:
            sim = h.get("similarity")
            if sim is None:
                filtered.append(h)
            else:
                try:
                    if float(sim) >= float(settings["min_score"]):
                        filtered.append(h)
                except Exception:
                    filtered.append(h)
        hits = filtered

    # Build context with a hard character cap
    context_blocks = []
    used = 0
    cap = int(settings["max_context_chars"])
    for i, h in enumerate(hits or [], start=1):
        block = (
            f"[{i}] {h.get('path','')}"
            f"Pages {h.get('page_start')}–{h.get('page_end')}"
            f"{h.get('content','')}"
        )
        if used + len(block) > cap:
            remaining = max(0, cap - used)
            if remaining > 200:  # keep at least a bit if we can
                context_blocks.append(block[:remaining] + "…")
            break
        context_blocks.append(block)
        used += len(block)

    system = settings["system_prompt"].strip() + "\n\n" + _style_instruction(settings.get("answer_style", "concise"))

    user_message = (
        f"QUESTION:\n{prompt}\n\nSOURCES:\n" + ("\n\n".join(context_blocks) if context_blocks else "(none)")
    )

    # Claude answer with fallback models (prevents hard 404s)
    answer = ""
    last_err = None
    for model in settings["claude_models"]:
        try:
            resp = claude.messages.create(
                model=model,
                max_tokens=int(settings["claude_max_tokens"]),
                temperature=float(settings["claude_temperature"]),
                system=system,
                messages=[{"role": "user", "content": user_message}],
            )
            answer = resp.content[0].text if resp.content else ""
            break
        except Exception as e:
            last_err = e

    if not answer:
        raise RuntimeError(f"Claude call failed for models={settings['claude_models']}. Last error: {last_err}")

    # store assistant msg
    svc.table("messages").insert({"conversation_id": cid, "role": "assistant", "content": answer}).execute()

    with st.chat_message("assistant"):
        st.markdown(answer)

        if settings.get("include_citations") and hits:
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
