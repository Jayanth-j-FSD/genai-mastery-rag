"""Pipeline stage 1 of 6 - LOAD.

Reads every document file in data/corpus/ and returns its plain
text. Supports .txt, .md and .pdf; anything else (or a file it can't read) is skipped.
"""
import os
import glob

from pypdf import PdfReader

SUPPORTED = (".txt", ".md", ".pdf")   # file types we know how to read


def _read_file(path: str, ext: str) -> str:
    """Return the text of one file (PDFs are extracted page by page)."""
    if ext == ".pdf":
        reader = PdfReader(path)
        # Some PDF pages have no extractable text (e.g. scans) -> treat as empty.
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    # .txt / .md — errors="ignore" so one odd character can't crash the whole load.
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()


def load_documents(corpus_dir: str):
    """Return a list of {"text", "source"} records, one per readable file."""
    docs = []
    # "**" with recursive=True walks sub-folders too, so nested documents are found.
    for path in sorted(glob.glob(os.path.join(corpus_dir, "**", "*"), recursive=True)):
        if os.path.isdir(path):
            continue
        ext = os.path.splitext(path)[1].lower()
        if ext not in SUPPORTED:
            continue
        # A short, readable name used in citations, e.g. "annual-leave.md".
        source = os.path.relpath(path, corpus_dir).replace("\\", "/")
        try:
            text = _read_file(path, ext)
        except Exception as exc:            # one bad file shouldn't stop the whole ingest
            print(f"  ! skipped {source}: {exc}")
            continue
        if text.strip():                    # ignore empty / unreadable files
            docs.append({"text": text, "source": source})
    return docs
