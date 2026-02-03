import json
import streamlit as st
from supabase_auth.errors import AuthApiError

from core.sidebar_ui import ensure_bootstrap_icons, render_sidebar
from core.supabase_client import auth_sign_in, auth_sign_out, ensure_profile, svc
from core.ui import apply_ui

st.set_page_config(page_title="Admin — Model", page_icon="🧠", layout="centered")
ensure_bootstrap_icons()
render_sidebar()

# Bootstrap Icons (visual-only)
st.markdown(
    '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css">',
    unsafe_allow_html=True,
)

apply_ui()

def bi(name: str, size: str = "1em") -> str:
    return f'<i class="bi bi-{name}" style="font-size:{size}; vertical-align:-0.125em;"></i>'


# ------------------------- Auth -------------------------
user = st.session_state.get("user")
if not user:
    st.info("Please log in.")
    st.switch_page("pages/0_Login.py")

if st.session_state.get("role") != "admin":
    st.error("Admin access required.")
    st.stop()

# ------------------------- Load/Create settings row -------------------------

st.markdown(f"# {bi('cpu')} Admin — Model setup", unsafe_allow_html=True)
st.caption("These are global settings applied to the Chat experience.")

rows = svc.table("model_settings").select("*").eq("scope", "global").limit(1).execute().data or []
if not rows:
    svc.table("model_settings").insert({"scope": "global"}).execute()
    rows = svc.table("model_settings").select("*").eq("scope", "global").limit(1).execute().data or []

settings = rows[0]


def get(key: str, default):
    v = settings.get(key, None)
    return default if v is None else v


# ------------------------- UI -------------------------

tabs = st.tabs(["Claude", "Retrieval", "Prompt & UX", "Advanced"])
st.caption("Tune global model + retrieval behavior. Visual labels use Bootstrap icons; features are unchanged.")

# ---- Claude ----
with tabs[0]:
    st.markdown(f"### {bi('chat-text')} Claude configuration", unsafe_allow_html=True)

    # Backward compat: if only claude_model exists, use it as the primary
    primary_default = settings.get("claude_model_primary") or settings.get("claude_model") or "claude-3-5-sonnet-latest"
    primary = st.text_input(
        "Primary model",
        value=str(primary_default).strip(),
        help="Example: claude-3-5-sonnet-latest",
    )

    fallbacks_default = get("claude_model_fallbacks_json", '["claude-3-5-haiku-latest"]')
    fallbacks_raw = st.text_area(
        "Fallback models (JSON array)",
        value=str(fallbacks_default),
        height=90,
        help='Example: ["claude-3-5-haiku-latest"]',
    )

    col1, col2 = st.columns(2)
    with col1:
        max_tokens = st.number_input(
            "Max tokens (answer)",
            min_value=128,
            max_value=4000,
            value=int(get("claude_max_tokens", 900)),
            step=64,
        )
    with col2:
        temperature = st.slider(
            "Temperature",
            0.0,
            1.0,
            value=float(get("claude_temperature", 0.2)),
            step=0.05,
        )

    # Validate fallbacks JSON
    try:
        parsed = json.loads(fallbacks_raw)
        if not isinstance(parsed, list) or not all(isinstance(x, str) for x in parsed):
            raise ValueError("Fallbacks must be a JSON array of strings.")
        fallbacks_json = json.dumps(parsed)
        st.success(f"Fallbacks parsed: {len(parsed)} model(s).")
    except Exception as e:
        fallbacks_json = '["claude-3-5-haiku-latest"]'
        st.error(f"Invalid JSON: {e}")

    st.markdown("---")
    st.markdown(f"### {bi('vector-pen')} Embeddings (OpenAI)", unsafe_allow_html=True)
    embedding_model = st.text_input(
        "Embedding model",
        value=str(get("embedding_model", "text-embedding-3-small")).strip(),
        help="Must match your pgvector dimension. If your table uses vector(1536), use text-embedding-3-small.",
    )

# ---- Retrieval ----
with tabs[1]:
    st.markdown(f"### {bi('sliders')} Retrieval behavior (RAG)", unsafe_allow_html=True)
    top_k = st.slider("Top K chunks", 3, 30, int(get("top_k", 8)))
    min_score = st.slider(
        "Minimum similarity threshold (0 = off)",
        0.0,
        1.0,
        float(get("min_score", 0.0)),
        0.01,
        help="If set too high, retrieval can return nothing.",
    )
    max_context_chars = st.number_input(
        "Max context size (characters)",
        min_value=4000,
        max_value=60000,
        value=int(get("max_context_chars", 18000)),
        step=500,
        help="Caps the amount of retrieved text injected into the prompt.",
    )

# ---- Prompt & UX ----
with tabs[2]:
    st.markdown(f"### {bi('terminal')} Prompting & UX", unsafe_allow_html=True)
    system_prompt = st.text_area(
        "System prompt",
        value=str(get(
            "system_prompt",
            "You are the Democracia+ assistant. Answer using the provided sources. If sources are insufficient, say what is missing and ask a clarifying question."
        )),
        height=180,
    )
    answer_style = st.selectbox(
        "Answer style",
        options=["concise", "balanced", "detailed"],
        index=["concise", "balanced", "detailed"].index(str(get("answer_style", "concise"))),
    )
    include_citations = st.toggle(
        "Show citations under answers",
        value=bool(get("include_citations", True)),
    )

# ---- Advanced ----
with tabs[3]:
    st.markdown(f"### {bi('bug')} Advanced / Debug", unsafe_allow_html=True)
    st.caption("This is the raw row from model_settings (read-only).")
    st.json(settings)

    st.markdown("If you see errors about missing columns, run the SQL migration shown at the bottom of this page.")

# ------------------------- Save -------------------------

st.markdown("---")
save = st.button("Save settings", type="primary")

if save:
    payload = {
        # New columns
        "claude_model_primary": primary.strip(),
        "claude_model_fallbacks_json": fallbacks_json,
        "claude_max_tokens": int(max_tokens),
        "claude_temperature": float(temperature),
        "embedding_model": embedding_model.strip(),
        "top_k": int(top_k),
        "min_score": float(min_score),
        "system_prompt": system_prompt,
        "answer_style": str(answer_style),
        "include_citations": bool(include_citations),
        "max_context_chars": int(max_context_chars),
        "updated_at": "now()",
        # Backward compatible fields (if your Chat still reads these)
        "claude_model": primary.strip(),
    }

    try:
        svc.table("model_settings").update(payload).eq("id", settings["id"]).execute()
        st.success("Saved model settings.")
        st.rerun()
    except Exception as e:
        st.error("Failed to save. This usually means some columns don’t exist yet.")
        st.code(str(e))

with st.expander("SQL migration (add missing columns)", expanded=False):
    st.code(
        """alter table public.model_settings
  add column if not exists claude_model_primary text,
  add column if not exists claude_model_fallbacks_json text,
  add column if not exists claude_max_tokens integer,
  add column if not exists claude_temperature double precision,
  add column if not exists min_score double precision,
  add column if not exists include_citations boolean,
  add column if not exists system_prompt text,
  add column if not exists answer_style text,
  add column if not exists max_context_chars integer;""",
        language="sql",
    )