import os
import time
from typing import Any, Dict, List, Optional

from supabase import create_client, Client

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/") + "/"
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

# Server-side client (bypasses RLS). Use this in worker and server operations.
svc: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# Client-side-ish (still server in Streamlit, but uses anon + email/pass auth)
anon: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def storage_upload(bucket: str, path: str, content: bytes, content_type: str = "application/pdf") -> None:
    # Supabase Python API uses .storage.from_(bucket).upload(...)
    # upsert=True to avoid collisions on retries (we use sha-based filenames)
    svc.storage.from_(bucket).upload(
        path=path,
        file=content,
        file_options={"content-type": content_type, "x-upsert": "true"},
    )


def storage_download(bucket: str, path: str) -> bytes:
    # Use service role to download private objects reliably
    return svc.storage.from_(bucket).download(path)


def storage_remove(bucket: str, paths: List[str]) -> None:
    if not paths:
        return
    svc.storage.from_(bucket).remove(paths)


# ---------------- Auth helpers ----------------

def auth_sign_in(email: str, password: str) -> Dict[str, Any]:
    res = anon.auth.sign_in_with_password({"email": email, "password": password})
    # res.user, res.session
    return {"user": res.user, "session": res.session}


def auth_sign_out() -> None:
    try:
        anon.auth.sign_out()
    except Exception:
        pass


def get_profile(user_id: str) -> Optional[Dict[str, Any]]:
    r = svc.table("profiles").select("*").eq("id", user_id).limit(1).execute()
    if r.data:
        return r.data[0]
    return None


# ---------------- DB helpers ----------------

def ensure_profile(user_id: str, email: str) -> Dict[str, Any]:
    # Upsert profile row
    svc.table("profiles").upsert({"id": user_id, "email": email}).execute()
    return get_profile(user_id) or {"id": user_id, "email": email, "role": "user"}


def create_event(user_id: Optional[str], action: str, document_id: Optional[str] = None, details: Optional[Dict[str, Any]] = None) -> None:
    svc.table("events").insert({
        "user_id": user_id,
        "action": action,
        "document_id": document_id,
        "details": details or {},
    }).execute()


def list_documents(admin: bool, user_id: str) -> List[Dict[str, Any]]:
    q = svc.table("documents").select("*").neq("status", "deleted").order("created_at", desc=True)
    if not admin:
        q = q.eq("owner_id", user_id)
    return q.execute().data or []


def insert_document(owner_id: str, filename: str, sha256: str, bucket: str, storage_path: str) -> Dict[str, Any]:
    r = svc.table("documents").insert({
        "owner_id": owner_id,
        "filename": filename,
        "sha256": sha256,
        "bucket": bucket,
        "storage_path": storage_path,
        "status": "uploaded",
    }).execute()
    return (r.data or [None])[0]


def find_document_by_sha256(sha256: str) -> Optional[Dict[str, Any]]:
    r = svc.table("documents").select("*").eq("sha256", sha256).neq("status", "deleted").limit(1).execute()
    if r.data:
        return r.data[0]
    return None


def update_document_status(doc_id: str, status: str, error: Optional[str] = None) -> None:
    payload: Dict[str, Any] = {"status": status}
    if status == "ready":
        payload["processed_at"] = "now()"
        payload["error"] = None
    if status == "failed":
        payload["error"] = error or "unknown"
    if status == "deleted":
        payload["deleted_at"] = "now()"
    svc.table("documents").update(payload).eq("id", doc_id).execute()


def delete_document(doc_id: str) -> None:
    # soft delete + cascade deletes sections via FK if you actually delete doc row;
    # we keep row but mark deleted, and manually delete sections.
    svc.table("sections").delete().eq("document_id", doc_id).execute()
    update_document_status(doc_id, "deleted")


def insert_sections_with_embeddings(doc_id: str, sections: List[Dict[str, Any]]) -> None:
    # sections: list of {path,page_start,page_end,content,embedding}
    # Insert in batches to avoid payload limits.
    batch_size = 50
    for i in range(0, len(sections), batch_size):
        svc.table("sections").insert([
            {
                "document_id": doc_id,
                "path": s.get("path"),
                "page_start": s.get("page_start"),
                "page_end": s.get("page_end"),
                "content": s["content"],
                "embedding": s.get("embedding"),
            }
            for s in sections[i:i+batch_size]
        ]).execute()


def rpc_match_sections(query_embedding: List[float], k: int = 8, filter_document_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    payload = {
        "query_embedding": query_embedding,
        "match_count": int(k),
        "filter_document_ids": filter_document_ids,
    }
    r = svc.rpc("match_sections", payload).execute()
    return r.data or []
