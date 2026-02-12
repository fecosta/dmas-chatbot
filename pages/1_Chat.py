import os
import json
import re
from datetime import datetime

import streamlit as st
from anthropic import Anthropic
from openai import OpenAI
from supabase_auth.errors import AuthApiError

from core.sidebar_ui import ensure_bootstrap_icons, render_sidebar
from core.supabase_client import (
    auth_sign_out,
    ensure_profile,
    list_documents,
    restore_supabase_session,
    rpc_match_sections,
    svc,
)
from core.ui import apply_ui
from core.llm import detect_user_language, language_instruction, conversational_instruction, lexical_overlap_count, is_language_mismatch, enforced_rules_header

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
    "answer_style": "balanced",  # concise|balanced|detailed
    "include_citations": True,
}

oai = OpenAI(api_key=OPENAI_API_KEY)
claude = Anthropic(api_key=ANTHROPIC_API_KEY)

st.set_page_config(page_title="D+ Agora — Chat", page_icon="./static/logo-dmas.svg", layout="wide")
ensure_bootstrap_icons()
render_sidebar(app_title="D+ Agora")

# Bootstrap Icons (visual-only)
st.markdown(
    '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css">',
    unsafe_allow_html=True,
)

apply_ui()

def bi(name: str, size: str = "1em") -> str:
    return f'<i class="bi bi-{name}" style="font-size:{size}; vertical-align:-0.125em;"></i>'


def _user_email(u) -> str:
    if isinstance(u, dict):
        return u.get("email") or u.get("id") or "unknown"
    return getattr(u, "email", None) or getattr(u, "id", None) or "unknown"


def _style_instruction(style: str) -> str:
    """Additional runtime style hint layered on top of the admin system prompt.

    IMPORTANT: Default to narrative prose. Use bullets only for a short recap when explicitly requested.
    """
    style = (style or "").strip().lower()
    if style == "detailed":
        return (
            "Default to narrative prose with context and reasoning. "
            "Aim for 4–8 short paragraphs. "
            "Only use headings/bullets if the user explicitly asks for a checklist/summary."
        )
    if style == "balanced":
        return (
            "Default to narrative prose with context and reasoning. "
            "Aim for 3–5 short paragraphs. "
            "Avoid bullet points unless explicitly requested."
        )
    return (
        "Default to narrative prose with context and reasoning. "
        "Aim for 2–4 short paragraphs. "
        "Avoid bullet points unless explicitly requested."
    )

# --- Response mode switching (narrative-first vs structured summary) ---
_STRUCTURED_TRIGGERS = re.compile(
    r"\b(checklist|bullet|bullets|framework|tl;dr|tldr|summary|summarize|key points|in points)\b",
    re.IGNORECASE,
)


def _pick_mode(user_text: str) -> str:
    return "STRUCTURED_SUMMARY" if _STRUCTURED_TRIGGERS.search(user_text or "") else "NARRATIVE_FIRST"


def _mode_hint(user_text: str) -> str:
    mode = _pick_mode(user_text)
    if mode == "STRUCTURED_SUMMARY":
        return (
            "[MODE: STRUCTURED_SUMMARY]\n"
            "Use headings and bullet points. Keep it concise and scannable.\n\n"
        )
    return (
        "[MODE: NARRATIVE_FIRST]\n"
        "Write in connected paragraphs with context and reasoning. "
        "Avoid bullet points unless explicitly requested.\n\n"
    )


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

 # ------------------------- Auth -------------------------
restore_supabase_session()

user = st.session_state.get("user")
if not user:
    st.info("Please log in.")
    st.switch_page("pages/0_Login.py")
    st.stop()

ensure_profile(user["id"], user.get("email") or "")

user_id = user["id"]
role = st.session_state.get("role", "user")
is_admin = role == "admin"

settings = _load_model_settings()

def _truncate_title(s: str, max_len: int = 50) -> str:
    s = " ".join((s or "").strip().split())
    if not s:
        return "Chat"
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


def maybe_autotitle_conversation(conversation_id: str, prompt: str) -> None:
    """
    If the conversation title is still the default ('Chat'),
    update it using the first user prompt.
    """
    try:
        row = (
            svc.table("conversations")
            .select("title")
            .eq("id", conversation_id)
            .limit(1)
            .execute()
            .data
        )
        if not row:
            return

        current_title = (row[0].get("title") or "").strip()
        if current_title.lower() != "chat":
            return  # already titled

        new_title = _truncate_title(prompt, 50)
        if new_title.lower() == "chat":
            return

        svc.table("conversations").update(
            {"title": new_title}
        ).eq("id", conversation_id).execute()

    except Exception:
        # Never block chat if titling fails
        return
    

if is_admin and settings["embedding_model"] != ENV_EMBED_MODEL:
    st.warning(
        "Admin note: Embedding model differs from the environment default. "
        "Changing embedding models requires re-embedding documents to maintain retrieval quality."
    )

# Sidebar: conversation list + new chat
with st.sidebar:
    st.markdown("---")
    st.sidebar.markdown(f"### {bi('clock-history')} Conversations", unsafe_allow_html=True)

    convs = list_conversations_for_user(user_id)  # already sorted desc in your helper
    current_id = st.session_state.get("conversation_id")

    colA, colB = st.columns([1, 1])
    with colA:
        if st.button("+ New chat", key="chat_new_chat", use_container_width=True):
            create_conversation(user_id, title="Chat")
            st.rerun()

    with colB:
        # Goes to a dedicated full history page (we'll create it below)
        if st.button("View all", key="chat_view_all_history", use_container_width=True):
            st.switch_page("pages/2_History.py")

    st.caption("Recent (last 4)")
    recent = convs[:4]

    if not recent:
        st.caption("No conversations yet.")
    else:
        for c in recent:
            cid = c.get("id")
            title = (c.get("title") or "Chat").strip()
            when = _safe_dt_label(c.get("created_at"))
            label = f"{title}"
            if when:
                label += f" · {when}"

            # Use a small list-style nav: buttons
            is_active = (cid == current_id)
            btn_label = ("● " if is_active else "· ") + label

            if st.button(btn_label, key=f"chat_conv_{cid}", use_container_width=True):
                if cid and cid != current_id:
                    st.session_state["conversation_id"] = cid
                    st.rerun()

# (No UI filters here; we keep docs available for future admin-only tooling)
docs = list_documents(admin=is_admin, user_id=user_id)

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

# Keep a tiny, safer tail of recent turns to preserve local coherence
# without resurfacing early-topic assistant content.
# Strategy: last 2 USER messages + last 1 ASSISTANT message (if present).
recent_turns = []
user_kept = 0
assistant_kept = 0

for m in reversed(msgs or []):
    role = (m.get("role") or "").strip().lower()
    content = (m.get("content") or "").strip()
    if not content or role not in ("user", "assistant"):
        continue

    if role == "user":
        if user_kept >= 2:
            continue
        user_kept += 1
    else:
        if assistant_kept >= 1:
            continue
        assistant_kept += 1

    # Cap per-message length to keep prompts tight
    if len(content) > 500:
        content = content[:497].rstrip() + "…"

    recent_turns.append(f"{role.upper()}: {content}")

    # Stop early once we have enough
    if user_kept >= 2 and assistant_kept >= 1:
        break

# Reverse back to chronological order
recent_history_block = "\n".join(reversed(recent_turns))

prompt = st.chat_input("Ask a question…") 

if prompt:
    detected_lang = detect_user_language(prompt)
    prev_lang = st.session_state.get("conversation_lang")

    # Sticky language: if we previously established PT/ES and the detector falls back to EN
    # on a short prompt, keep the previous language unless the user clearly switches.
    if prev_lang in ("pt", "es") and detected_lang == "en":
        answer_lang = prev_lang
    else:
        answer_lang = detected_lang

    st.session_state["conversation_lang"] = answer_lang
    # Auto-title conversation if still default
    maybe_autotitle_conversation(cid, prompt)

    # Deterministic handling: this app does not do live web browsing.
    if re.search(r"\b(busca\s+na\s+web|pesquis(a|ar)\s+na\s+web|buscar\s+na\s+internet|pesquis(a|ar)\s+na\s+internet|web\s+search|browse\s+the\s+web|buscar\s+en\s+la\s+web|buscar\s+en\s+internet|búsqueda\s+en\s+la\s+web)\b", prompt, re.IGNORECASE):
        if answer_lang == "pt":
            answer = (
                "Consigo te ajudar a formular a busca, mas este chat (no app) não faz navegação na web em tempo real. "
                "Se você me disser o que quer encontrar, eu monto as melhores consultas, fontes recomendadas e critérios de verificação — "
                "ou posso responder com base nos documentos que você enviou."
            )
        elif answer_lang == "es":
            answer = (
                "Puedo ayudarte a formular la búsqueda, pero este chat (en la app) no navega la web en tiempo real. "
                "Si me dices qué quieres encontrar, preparo las mejores consultas, fuentes recomendadas y criterios de verificación — "
                "o puedo responder basándome en los documentos que subiste."
            )
        else:
            answer = (
                "I can help you craft the web search, but this in-app chat doesn't browse the web in real time. "
                "Tell me what you want to find and I’ll propose the best queries, sources to check, and verification steps — "
                "or I can answer based on the documents you uploaded."
            )

        svc.table("messages").insert({"conversation_id": cid, "role": "user", "content": prompt}).execute()
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            st.markdown(answer)

        svc.table("messages").insert({"conversation_id": cid, "role": "assistant", "content": answer}).execute()
        st.stop()

    svc.table("messages").insert(
        {"conversation_id": cid, "role": "user", "content": prompt}
    ).execute()

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
            # Cheap relevance filter to prevent unrelated chunks from dominating.
            # This helps avoid the model "bringing back" old topics.
            overlap = lexical_overlap_count(prompt, txt)
            # For very short prompts, allow small overlap; otherwise require more.
            min_overlap = 1 if len(prompt.strip()) < 40 else 2
            if overlap < min_overlap:
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
            if answer_lang == "pt":
                answer = (
                    "Não encontrei informações relevantes nos documentos enviados para responder a isso. "
                    "Tente reformular a pergunta ou envie um documento que trate desse tema."
                )
            elif answer_lang == "es":
                answer = (
                    "No encontré información relevante en los documentos cargados para responder eso. "
                    "Intenta reformular tu pregunta o sube un documento que cubra este tema."
                )
            else:
                answer = (
                    "I couldn’t find relevant information in the uploaded documents to answer that. "
                    "Try rephrasing your question or upload a document that covers this topic."
                )
            st.markdown(answer)
            svc.table("messages").insert({"conversation_id": cid, "role": "assistant", "content": answer}).execute()
        else:
            sys = (
                enforced_rules_header(answer_lang)
                + language_instruction(answer_lang)
                + "\n\n"
                + "Cheque final antes de responder:\n"
                + "- Garanta que toda a resposta está no idioma exigido.\n"
                + "- Se alguma frase estiver em outro idioma, reescreva tudo no idioma exigido.\n\n"
                + conversational_instruction(answer_lang)
                + "\n\n"
                + _style_instruction(settings.get("answer_style", "concise"))
                + "\n\n"
                + (settings["system_prompt"].strip() or "")
            )
            ctx = "\n\n".join(sources)
            user_msg = (
                _mode_hint(prompt)
                + ("RECENT CHAT (for resolving references only; ignore if unrelated):\n" + recent_history_block + "\n\n" if recent_history_block else "")
                + f"QUESTION:\n{prompt}\n\n"
                + "CONTEXT (reference only; do not mirror its formatting):\n"
                + f"{ctx}\n\n"
                + "Use the context above as evidence for any factual claims. "
                + "If the context is insufficient, say what is missing and ask 1 clarifying question."
            )

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

            # If the model drifted into English for PT/ES, do a single rewrite pass.
            if is_language_mismatch(answer_lang, answer):
                rewrite_lang = "PT-BR" if answer_lang == "pt" else "ES"
                rewrite_user = (
                    f"Rewrite the following answer entirely in {rewrite_lang}. "
                    "Do not add new facts. Do not mention protocols or internal rules.\n\n"
                    f"ANSWER TO REWRITE:\n{answer}"
                )
                try:
                    resp2 = claude.messages.create(
                        model=models[0],
                        max_tokens=int(settings["claude_max_tokens"]),
                        temperature=0.0,
                        system=sys,
                        messages=[{"role": "user", "content": rewrite_user}],
                    )
                    rewritten = resp2.content[0].text if resp2.content else ""
                    if rewritten:
                        answer = rewritten
                except Exception:
                    # If rewrite fails, keep original answer (do not break chat)
                    pass

            st.markdown(answer)
            svc.table("messages").insert({"conversation_id": cid, "role": "assistant", "content": answer}).execute()

            if settings.get("include_citations", True):
                with st.expander("Sources used"):
                    st.markdown(f"#### {bi('book')} Sources", unsafe_allow_html=True)
                    for s in sources:
                        st.markdown(s)