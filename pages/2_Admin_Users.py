import streamlit as st
import pandas as pd
from core.sidebar_ui import ensure_bootstrap_icons, render_sidebar
from core.supabase_client import ensure_profile, restore_supabase_session, svc
from core.ui import apply_ui

st.set_page_config(page_title="Admin — Users", page_icon="./static/logo-dmas.svg", layout="centered")
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
restore_supabase_session()

user = st.session_state.get("user")
if not user:
    st.info("Please log in.")
    st.switch_page("pages/0_Login.py")
    st.stop()

if st.session_state.get("role") != "admin":
    st.error("Admin access required.")
    st.stop()

st.markdown(f"# {bi('people')} Admin — Users", unsafe_allow_html=True)
st.caption("Manage user accounts and roles.")

profiles = svc.table("profiles").select("id,email,role,created_at").order("created_at", desc=True).execute().data or []
if not profiles:
    st.info("No users found.")
    st.stop()

df = pd.DataFrame(profiles)
st.dataframe(df, use_container_width=True, hide_index=True)

st.markdown("---")
st.markdown(f"### {bi('shield-lock')} Change role", unsafe_allow_html=True)

emails = [p["email"] for p in profiles if p.get("email")]
selected_email = st.selectbox("User", options=emails, key="users_pick_email")
new_role = st.selectbox("Role", options=["user", "admin"], key="users_pick_role")

if st.button("Update role", type="primary", key="users_update_role"):
    row = next((p for p in profiles if p.get("email") == selected_email), None)
    if not row:
        st.error("User not found.")
    else:
        svc.table("profiles").update({"role": new_role}).eq("id", row["id"]).execute()
        st.success(f"Updated {selected_email} → {new_role}")
        st.rerun()