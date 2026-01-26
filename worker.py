import os
import time
from typing import List

from openai import OpenAI

from core.supabase_client import (
    storage_download,
    update_document_status,
    insert_sections_with_embeddings,
    create_event,
    svc,
)
from core.pdf_extract import build_sections_from_pdf

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
EMBED_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")  # 1536 dims

client = OpenAI(api_key=OPENAI_API_KEY)


def embed_texts(texts: List[str]) -> List[List[float]]:
    # OpenAI embeddings API batch
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [d.embedding for d in resp.data]


def fetch_next_doc():
    # Use SQL ordering to keep it simple; worker claims 1 at a time
    r = (
        svc.table("documents")
        .select("*")
        .in_("status", ["uploaded", "failed"])
        .order("created_at", desc=False)
        .limit(1)
        .execute()
    )
    if not r.data:
        return None
    return r.data[0]


def main():
    print("Worker started. Polling for documents…")
    while True:
        doc = fetch_next_doc()
        if not doc:
            time.sleep(10)
            continue

        doc_id = doc["id"]
        user_id = doc["owner_id"]
        bucket = doc["bucket"]
        path = doc["storage_path"]
        filename = doc["filename"]

        try:
            update_document_status(doc_id, "processing")
            create_event(user_id, "worker_processing_start", doc_id, {"filename": filename})

            file_bytes = storage_download(bucket, path)

            # Save to temp file for pypdf
            tmp_path = f"/tmp/{doc_id}.pdf"
            with open(tmp_path, "wb") as f:
                f.write(file_bytes)

            sections = build_sections_from_pdf(tmp_path, filename)
            if not sections:
                raise RuntimeError("No text extracted from PDF. It may be scanned/protected.")

            # Prepare texts for embedding (keep them reasonable size)
            payload = []
            texts = []
            for s in sections:
                txt = (s.text or "").strip()
                if not txt:
                    continue
                # soft cap to reduce token/embedding cost
                if len(txt) > 8000:
                    txt = txt[:8000]
                payload.append({
                    "path": s.path,
                    "page_start": s.page_start,
                    "page_end": s.page_end,
                    "content": txt,
                })
                texts.append(txt)

            vectors = embed_texts(texts)
            for i, v in enumerate(vectors):
                payload[i]["embedding"] = v

            # Replace existing sections if reprocessing
            svc.table("sections").delete().eq("document_id", doc_id).execute()
            insert_sections_with_embeddings(doc_id, payload)

            update_document_status(doc_id, "ready")
            create_event(user_id, "worker_processing_done", doc_id, {"sections": len(payload), "filename": filename})
            print(f"Processed {filename} ({doc_id}) sections={len(payload)}")

        except Exception as e:
            update_document_status(doc_id, "failed", error=str(e))
            create_event(user_id, "worker_processing_failed", doc_id, {"error": str(e), "filename": filename})
            print(f"FAILED {filename} ({doc_id}): {e}")

        time.sleep(2)


if __name__ == "__main__":
    main()