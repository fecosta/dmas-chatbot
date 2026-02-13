import os
import time
from typing import List, Optional

from openai import OpenAI

from core.supabase_client import (
    storage_download,
    update_document_status,
    insert_sections_with_embeddings,
    create_event,
    svc,
)
from core.pdf_extract import build_sections_from_pdf
from core.env_validator import get_required_env, get_optional_env

OPENAI_API_KEY = get_required_env("OPENAI_API_KEY", "OpenAI API key for embeddings")
EMBED_MODEL = get_optional_env("EMBEDDING_MODEL", "text-embedding-3-small")  # 1536 dims

client = OpenAI(api_key=OPENAI_API_KEY)


def embed_texts(texts: List[str]) -> List[List[float]]:
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [d.embedding for d in resp.data]


def fetch_next_doc() -> Optional[dict]:
    # Only process 'uploaded'. Failed docs should be retried by admin (set back to 'uploaded').
    r = (
        svc.table("documents")
        .select("*")
        .eq("status", "uploaded")
        .order("created_at", desc=False)
        .limit(1)
        .execute()
    )
    if not r.data:
        return None
    return r.data[0]


def ext_from_doc(doc: dict) -> str:
    sp = (doc.get("storage_path") or "").lower()
    fn = (doc.get("filename") or "").lower()
    ext = os.path.splitext(sp)[1] or os.path.splitext(fn)[1]
    return (ext or "").lower()


def build_sections_payload_from_bytes(file_bytes: bytes, doc: dict) -> List[dict]:
    filename = doc.get("filename") or "document"
    ext = ext_from_doc(doc)

    if ext in [".md", ".txt"]:
        text = file_bytes.decode("utf-8", errors="replace").strip()
        if not text:
            raise RuntimeError("Empty text file.")
        return [{
            "path": filename,
            "page_start": 1,
            "page_end": 1,
            "content": text[:8000],
        }]

    # Default: treat as PDF
    tmp_path = f"/tmp/{doc['id']}.pdf"
    with open(tmp_path, "wb") as f:
        f.write(file_bytes)

    sections = build_sections_from_pdf(tmp_path, filename)
    if not sections:
        raise RuntimeError("No text extracted from PDF. It may be scanned/protected.")

    payload: List[dict] = []
    for s in sections:
        txt = (s.text or "").strip()
        if not txt:
            continue
        if len(txt) > 8000:
            txt = txt[:8000]
        payload.append({
            "path": s.path,
            "page_start": s.page_start,
            "page_end": s.page_end,
            "content": txt,
        })

    if not payload:
        raise RuntimeError("All extracted sections were empty after cleaning.")
    return payload


def main() -> None:
    print("Worker started. Polling for documents…")
    while True:
        doc = fetch_next_doc()
        if not doc:
            time.sleep(10)
            continue

        doc_id = doc["id"]
        user_id = doc["owner_id"]
        bucket = doc.get("bucket", "documents")
        path = doc["storage_path"]
        filename = doc.get("filename", "")

        try:
            update_document_status(doc_id, "processing")
            create_event(user_id, "worker_processing_start", doc_id, {"filename": filename})

            file_bytes = storage_download(bucket, path)

            sections_payload = build_sections_payload_from_bytes(file_bytes, doc)

            texts = [s["content"] for s in sections_payload]
            vectors = embed_texts(texts)
            for i, v in enumerate(vectors):
                sections_payload[i]["embedding"] = v

            svc.table("sections").delete().eq("document_id", doc_id).execute()
            insert_sections_with_embeddings(doc_id, sections_payload)

            update_document_status(doc_id, "ready")
            create_event(user_id, "worker_processing_done", doc_id, {"sections": len(sections_payload), "filename": filename})
            print(f"Processed {filename} ({doc_id}) sections={len(sections_payload)}")

        except Exception as e:
            update_document_status(doc_id, "failed", error=str(e))
            create_event(user_id, "worker_processing_failed", doc_id, {"error": str(e), "filename": filename})
            print(f"FAILED {filename} ({doc_id}): {e}")

        time.sleep(2)


if __name__ == "__main__":
    main()
