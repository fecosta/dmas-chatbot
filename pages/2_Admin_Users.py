import streamlit as st
import pandas as pd
from core.supabase_client import auth_sign_in, auth_sign_out, ensure_profile, svc

st.set_page_config(page_title="Admin — Users", page_icon="👥", layout="wide")

def sidebar_auth():
    st.sidebar.header("Login")
    if st.session_state.get("user"):
        u = st.session_state["user"]
        email = u.get("email") or u.get("id", "unknown")
        st.sidebar.success(f"Logged in: {email}")
        if st.sidebar.button("Logout", key="users_logout"):
            auth_sign_out()
            st.session_state.clear()
            st.rerun()
        return

    email = st.sidebar.text_input("Email", key="users_login_email")
    password = st.sidebar.text_input("Password", type="password", key="users_login_password")
    if st.sidebar.button("Login", key="users_login_btn"):
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
    st.title("👥 Admin — Users")
    st.info("Please log in.")
    st.stop()

if st.session_state.get("role") != "admin":
    st.title("👥 Admin — Users")
    st.error("Admin access required.")
    st.stop()

st.title("👥 Admin — Users")

profiles = svc.table("profiles").select("id,email,role,created_at").order("created_at", desc=True).execute().data or []
if not profiles:
    st.info("No users found.")
    st.stop()

df = pd.DataFrame(profiles)
st.dataframe(df, use_container_width=True, hide_index=True)

st.markdown("---")
st.subheader("Change role")

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