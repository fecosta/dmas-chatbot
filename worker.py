import os

def _ext_from_doc(doc: dict) -> str:
    # Prefer storage_path extension, fallback to filename extension
    sp = (doc.get("storage_path") or "").lower()
    fn = (doc.get("filename") or "").lower()
    ext = os.path.splitext(sp)[1] or os.path.splitext(fn)[1]
    return ext.lower()

# ...

ext = _ext_from_doc(doc)

if ext in [".md", ".txt"]:
    text = file_bytes.decode("utf-8", errors="replace").strip()
    if not text:
        raise RuntimeError("Empty text file.")
    # one “section”
    sections_payload = [{
        "path": filename,
        "page_start": 1,
        "page_end": 1,
        "content": text[:8000],
    }]
else:
    # default PDF path
    tmp_path = f"/tmp/{doc_id}.pdf"
    with open(tmp_path, "wb") as f:
        f.write(file_bytes)

    sections = build_sections_from_pdf(tmp_path, filename)
    if not sections:
        raise RuntimeError("No text extracted from PDF. It may be scanned/protected.")

    sections_payload = []
    for s in sections:
        txt = (s.text or "").strip()
        if not txt:
            continue
        if len(txt) > 8000:
            txt = txt[:8000]
        sections_payload.append({
            "path": s.path,
            "page_start": s.page_start,
            "page_end": s.page_end,
            "content": txt,
        })