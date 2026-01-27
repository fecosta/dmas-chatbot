import streamlit as st
from core.supabase_client import auth_sign_in, auth_sign_out, ensure_profile, svc

st.set_page_config(page_title="Admin — Model", page_icon="🧠", layout="wide")

def sidebar_auth():
    st.sidebar.header("Login")
    if st.session_state.get("user"):
        u = st.session_state["user"]
        email = u.get("email") or u.get("id", "unknown")
        st.sidebar.success(f"Logged in: {email}")
        if st.sidebar.button("Logout", key="model_logout"):
            auth_sign_out()
            st.session_state.clear()
            st.rerun()
        return

    email = st.sidebar.text_input("Email", key="model_login_email")
    password = st.sidebar.text_input("Password", type="password", key="model_login_password")
    if st.sidebar.button("Login", key="model_login_btn"):
        res = auth_sign_in(email, password)
        u = res["user"]
        user = {"id": u.id, "email": getattr(u, "email", None) or email}
        st.session_state["user"] = user
        profile = ensure_profile(user["id"], user["email"] or "")
        st.session_state["role"] = profile.get("role", "user")
        st.rerun()

sidebar_auth()
user = st.session_state.get("user")
if not user:
    st.title("🧠 Admin — Model setup")
    st.info("Please log in.")
    st.stop()

if st.session_state.get("role") != "admin":
    st.title("🧠 Admin — Model setup")
    st.error("Admin access required.")
    st.stop()

st.title("🧠 Admin — Model setup")

# Load settings row
rows = svc.table("model_settings").select("*").eq("scope", "global").limit(1).execute().data or []
if not rows:
    svc.table("model_settings").insert({"scope": "global"}).execute()
    rows = svc.table("model_settings").select("*").eq("scope", "global").limit(1).execute().data or []

settings = rows[0]

claude_model = st.text_input("Claude model", value=settings["claude_model"])
embedding_model = st.text_input("Embedding model", value=settings["embedding_model"])
top_k = st.slider("Top K (retrieved chunks)", 3, 20, int(settings["top_k"]))

if st.button("Save", type="primary"):
    svc.table("model_settings").update({
        "claude_model": claude_model.strip(),
        "embedding_model": embedding_model.strip(),
        "top_k": int(top_k),
        "updated_at": "now()",
    }).eq("id", settings["id"]).execute()
    st.success("Saved model settings.")
    st.rerun()