import os
import streamlit as st
from anthropic import Anthropic
from openai import OpenAI

from core.supabase_client import (
    auth_sign_in,
    auth_sign_out,
    ensure_profile,
    get_profile,
    list_documents,
    rpc_match_sections,
    svc,
)

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
EMBED_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-3-5-sonnet-20240620")  # change if you prefer

oai = OpenAI(api_key=OPENAI_API_KEY)
claude = Anthropic(api_key=ANTHROPIC_API_KEY)

st.set_page_config(page_title="Chat", page_icon="💬", layout="wide")


def sidebar_auth():
    st.sidebar.header("Login")
    if st.session_state.get("user"):
        u = st.session_state["user"]
        st.sidebar.success(f"Logged in: {u['email']}")
        if st.sidebar.button("Logout"):
            auth_sign_out()
            st.session_state.clear()
            st.rerun()
        return

    email = st.sidebar.text_input("Email")
    password = st.sidebar.text_input("Password", type="password")
    if st.sidebar.button("Login"):
        res = auth_sign_in(email, password)
        user = {"id": res["user"].id, "email": res["user"].email}
        st.session_state["user"] = user
        profile = ensure_profile(user["id"], user["email"])
        st.session_state["role"] = profile.get("role", "user")
        st.rerun()


def get_or_create_conversation(user_id: str):
    if st.session_state.get("conversation_id"):
        return st.session_state["conversation_id"]

    r = svc.table("conversations").insert({"user_id": user_id, "title": "Chat"}).execute()
    cid = r.data[0]["id"]
    st.session_state["conversation_id"] = cid
    return cid


def embed_query(q: str):
    resp = oai.embeddings.create(model=EMBED_MODEL, input=q)
    return resp.data[0].embedding


def list_conversations_for_user(user_id: str):
    return (
        svc.table("conversations")
        .select("id,title,created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )


def create_conversation(user_id: str, title: str = "Chat") -> str:
    r = svc.table("conversations").insert({"user_id": user_id, "title": title}).execute()
    return r.data[0]["id"]


sidebar_auth()
user = st.session_state.get("user")
if not user:
    st.title("💬 D+ Chatbot")
    st.info("Please log in to continue.")
    st.stop()

user_id = user["id"]
role = st.session_state.get("role", "user")
is_admin = role == "admin"

st.title("💬 D+ Chatbot")

# Conversations (UX)
convs = list_conversations_for_user(user_id)

with st.sidebar:
    st.markdown("---")
    st.subheader("Conversations")

    if st.button("+ New chat", key="chat_new_chat"):
        # Create immediately so the list updates and chat opens on it.
        new_id = create_conversation(user_id, title="Chat")
        st.session_state["conversation_id"] = new_id
        st.rerun()

    if convs:
        # Build stable labels (title + date) for selection UI
        labels = []
        label_to_id = {}
        for c in convs:
            created = (c.get("created_at") or "")[:10]
            title = (c.get("title") or "Chat").strip() or "Chat"
            label = f"{title} · {created}" if created else title
            # disambiguate duplicates
            if label in label_to_id:
                label = f"{label} ({c['id'][:6]})"
            labels.append(label)
            label_to_id[label] = c["id"]

        current_id = st.session_state.get("conversation_id")
        # Default selection: current conversation if present, else most recent
        default_label = None
        if current_id:
            for lbl, cid_ in label_to_id.items():
                if cid_ == current_id:
                    default_label = lbl
                    break
        if default_label is None:
            default_label = labels[0]
            st.session_state["conversation_id"] = label_to_id[default_label]

        picked = st.selectbox(
            "",
            options=labels,
            index=labels.index(default_label) if default_label in labels else 0,
            key="chat_conversation_select",
            label_visibility="collapsed",
        )
        picked_id = label_to_id.get(picked)
        if picked_id and picked_id != st.session_state.get("conversation_id"):
            st.session_state["conversation_id"] = picked_id
            st.rerun()
    else:
        st.caption("No conversations yet. Click **+ New chat**.")

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
    hits = rpc_match_sections(q_emb, k=DEFAULT_TOP_K, filter_document_ids=None)

    context_blocks = []
    for i, h in enumerate(hits, start=1):
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

    # Claude answer
    resp = claude.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=900,
        temperature=0.2,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    answer = resp.content[0].text if resp.content else ""

    # store assistant msg
    svc.table("messages").insert({"conversation_id": cid, "role": "assistant", "content": answer}).execute()

    with st.chat_message("assistant"):
        st.markdown(answer)

        if hits:
            with st.expander("Sources used"):
                for i, h in enumerate(hits, start=1):
                    st.markdown(f"**[{i}]** {h.get('path','')}")
                    st.caption(f"Pages {h.get('page_start')}–{h.get('page_end')} • similarity {h.get('similarity'):.3f}")
                    snippet = (h.get("content", "")[:700] + ("…" if len(h.get("content", "")) > 700 else ""))
                    st.text(snippet)