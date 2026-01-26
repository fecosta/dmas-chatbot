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

# Document filter (optional)
docs = list_documents(admin=is_admin, user_id=user_id)
ready_docs = [d for d in docs if d["status"] == "ready"]

doc_options = {f"{d['filename']} — {d['id'][:8]}": d["id"] for d in ready_docs}

with st.sidebar:
    st.subheader("Sources")
    selected_labels = st.multiselect(
        "Limit retrieval to selected documents",
        options=list(doc_options.keys()),
        default=[],
    )
    filter_doc_ids = [doc_options[x] for x in selected_labels] if selected_labels else None
    top_k = st.slider("Retrieved chunks", 3, 15, 8)

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