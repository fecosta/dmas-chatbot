import os
import uuid
import pandas as pd
import streamlit as st
from supabase_auth.errors import AuthApiError

from core.pdf_extract import build_sections_from_pdf  # optional: you can process sync for tiny files
from core.utils import safe_filename, sha256_bytes

from core.supabase_client import (
    auth_sign_in,
    auth_sign_out,
    ensure_profile,
    get_profile,
    list_documents,
    insert_document,
    find_document_by_sha256,
    update_document_status,
    delete_document,
    storage_upload,
    storage_remove,
    create_event,
    svc,
)

BUCKET = "documents"

def _user_email(u):
    if isinstance(u, dict):
        return u.get("email") or (u.get("user_metadata") or {}).get("email") or u.get("id")
    return getattr(u, "email", None) or getattr(u, "id", None)


st.set_page_config(page_title="Admin — Data", page_icon="📄", layout="wide")


def sidebar_auth():
    st.sidebar.header("Login")
    if st.session_state.get("user"):
        u = st.session_state["user"]
        st.sidebar.success(f"Logged in: {(u.get('email') or _user_email(u))}")
        if st.sidebar.button("Logout"):
            auth_sign_out()
            st.session_state.clear()
            st.rerun()
        return

    email = st.sidebar.text_input("Email")
    password = st.sidebar.text_input("Password", type="password")
    if st.sidebar.button("Login"):
        try:
            res = auth_sign_in(email, password)
        except AuthApiError:
            st.sidebar.error("Invalid email or password.")
            return
        u = res["user"]
        user = {"id": getattr(u, "id", None), "email": getattr(u, "email", None) or (getattr(u, "user_metadata", None) or {}).get("email") or email}
        st.session_state["user"] = user
        profile = ensure_profile(user["id"], user.get("email") or email)
        st.session_state["role"] = profile.get("role", "user")
        st.rerun()


sidebar_auth()
user = st.session_state.get("user")
if not user:
    st.title("📄 Admin — Data")
    st.info("Please log in.")
    st.stop()

user_id = user["id"]
role = st.session_state.get("role", "user")
if role != "admin":
    st.title("📄 Admin — Data")
    st.error("Admin access required.")
    st.stop()

st.title("📄 Admin — Data upload & management")

# -------- Upload --------
st.subheader("Upload documents (stored in Supabase Storage)")

with st.form("upload_form", clear_on_submit=True):
    files = st.file_uploader(
        "Select files to upload (.pdf, .txt, .md)",
        type=["pdf", "txt", "md"],
        accept_multiple_files=True,
        key="admin_uploader",
    )
    submitted = st.form_submit_button("Upload")

if submitted and files:
    batch_id = str(uuid.uuid4())
    create_event(user_id, "upload_submit", details={"batch_id": batch_id, "count": len(files)})

    uploaded = 0
    skipped = 0

    for uf in files:
        raw_name = uf.name
        name = safe_filename(raw_name)
        content = uf.getvalue()
        digest = sha256_bytes(content)

        create_event(user_id, "upload_seen", details={"batch_id": batch_id, "filename": raw_name, "sha256": digest, "size": len(content)})

        existing = find_document_by_sha256(digest)
        if existing:
            skipped += 1
            create_event(user_id, "upload_skip_duplicate", document_id=existing["id"], details={"batch_id": batch_id, "filename": raw_name})
            continue

        # storage path uses sha prefix for idempotency
        ext = os.path.splitext(name)[1].lower() or ".bin"
        storage_path = f"{digest[:16]}/{digest}{ext}"

        content_type = "application/pdf" if ext == ".pdf" else "text/plain"
        storage_upload(BUCKET, storage_path, content, content_type=content_type)

        doc = insert_document(
            owner_id=user_id,
            filename=name,
            sha256=digest,
            bucket=BUCKET,
            storage_path=storage_path,
        )
        create_event(user_id, "upload_saved", document_id=doc["id"], details={"batch_id": batch_id, "storage_path": storage_path})

        # Mark as uploaded; worker will pick it up
        update_document_status(doc["id"], "uploaded")
        uploaded += 1

    st.success(f"Upload complete. Uploaded: {uploaded}, skipped duplicates: {skipped}.")
    st.rerun()

# -------- Documents list (Option B table view) --------
st.markdown("---")
st.subheader("Documents")

docs = list_documents(admin=True, user_id=user_id)

if not docs:
    st.info("No documents.")
    st.stop()

# Filter
ft = st.text_input("Filter by filename", value="")
if ft.strip():
    docs = [d for d in docs if ft.strip().lower() in (d.get("filename") or "").lower()]

rows = []
for d in docs:
    rows.append({
        "Select": False,
        "id": d["id"],
        "filename": d["filename"],
        "status": d["status"],
        "created_at": d["created_at"],
        "processed_at": d.get("processed_at") or "",
        "sha12": (d["sha256"][:12] + "…") if d.get("sha256") else "",
        "storage_path": d["storage_path"],
    })

df = pd.DataFrame(rows)

# Persist selection across reruns
prev = st.session_state.get("docs_table_state")
prev_sel = {}
if prev is not None and not prev.empty:
    prev_sel = dict(zip(prev["id"].astype(str), prev["Select"].astype(bool)))

df["Select"] = df["id"].astype(str).map(lambda x: bool(prev_sel.get(x, False)))
st.session_state["docs_table_state"] = df.copy()

edited = st.data_editor(
    st.session_state["docs_table_state"],
    hide_index=True,
    use_container_width=True,
    disabled=["id", "filename", "status", "created_at", "processed_at", "sha12", "storage_path"],
    column_config={
        "Select": st.column_config.CheckboxColumn("Select"),
        "filename": st.column_config.TextColumn("File"),
        "status": st.column_config.TextColumn("Status"),
        "created_at": st.column_config.TextColumn("Created"),
        "processed_at": st.column_config.TextColumn("Processed"),
        "sha12": st.column_config.TextColumn("SHA"),
        "storage_path": st.column_config.TextColumn("Storage path"),
    },
    key="docs_table_editor",
)
st.session_state["docs_table_state"] = edited

selected_ids = edited.loc[edited["Select"] == True, "id"].astype(str).tolist()

c1, c2, c3, c4 = st.columns([1, 1, 1, 3])
with c1:
    if st.button("Select all"):
        st.session_state["docs_table_state"]["Select"] = True
        st.rerun()
with c2:
    if st.button("Clear"):
        st.session_state["docs_table_state"]["Select"] = False
        st.rerun()
with c3:
    if st.button("Mark selected for reprocess", disabled=(len(selected_ids) == 0)):
        for doc_id in selected_ids:
            update_document_status(doc_id, "uploaded")
            create_event(user_id, "reprocess_requested", document_id=doc_id)
        st.success("Marked for reprocess.")
        st.session_state.pop("docs_table_state", None)
        st.rerun()
with c4:
    st.caption(f"Selected: {len(selected_ids)} / {len(edited)}")

colA, colB = st.columns([1, 2])
with colA:
    if st.button("Delete selected", type="primary", disabled=(len(selected_ids) == 0)):
        # delete storage + db rows
        id_to_doc = {d["id"]: d for d in docs}
        for doc_id in selected_ids:
            d = id_to_doc.get(doc_id)
            if d:
                storage_remove(d["bucket"], [d["storage_path"]])
            delete_document(doc_id)
            create_event(user_id, "delete_doc", document_id=doc_id, details={"mode": "selected"})
        st.success(f"Deleted {len(selected_ids)} documents.")
        st.session_state.pop("docs_table_state", None)
        st.rerun()

with colB:
    if st.button("Delete ALL (danger)"):
        st.session_state["confirm_delete_all"] = True

if st.session_state.get("confirm_delete_all"):
    st.warning("This will delete ALL documents. Confirm below.")
    ok, cancel = st.columns([1, 1])
    with ok:
        if st.button("CONFIRM DELETE ALL", type="primary"):
            for d in docs:
                storage_remove(d["bucket"], [d["storage_path"]])
                delete_document(d["id"])
                create_event(user_id, "delete_doc", document_id=d["id"], details={"mode": "all"})
            st.session_state["confirm_delete_all"] = False
            st.session_state.pop("docs_table_state", None)
            st.success("All documents deleted.")
            st.rerun()
    with cancel:
        if st.button("Cancel"):
            st.session_state["confirm_delete_all"] = False

with st.expander("Recent events"):
    ev = svc.table("events").select("*").order("created_at", desc=True).limit(50).execute().data or []
    for e in ev:
        st.code(f"{e['created_at']} | {e['action']} | doc={e.get('document_id')} | {e.get('details')}")
