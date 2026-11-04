from io import BytesIO
from pathlib import Path
from docx import Document
from pypdf import PdfReader

ACCEPTED = {".pdf", ".docx", ".txt"}
MAX_BYTES = 8 * 1024 * 1024

# PostgreSQL rejects NUL bytes in text. PDF extractors can return NULs
# and invalid Unicode codepoints, even for a legitimate resume.
_CONTROL_CHARS = {i: None for i in range(32) if i not in (9, 10, 13)}


def clean_text(value: str) -> str:
    """Normalize extracted text for PostgreSQL while keeping readable lines."""
    return value.translate(_CONTROL_CHARS).encode("utf-8", errors="replace").decode("utf-8")


def parse_cv(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ACCEPTED:
        raise ValueError("Supported formats: PDF, DOCX, TXT")
    if not data or len(data) > MAX_BYTES:
        raise ValueError("File is empty or exceeds 8 MB")
    if suffix == ".pdf":
        if not data.startswith(b"%PDF"):
            raise ValueError("Invalid PDF header")
        reader = PdfReader(BytesIO(data))
        if len(reader.pages) > 100:
            raise ValueError("Maximum 100 pages")
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    elif suffix == ".docx":
        if not data.startswith(b"PK"):
            raise ValueError("Invalid DOCX header")
        doc = Document(BytesIO(data))
        text = "\n".join([p.text for p in doc.paragraphs] + [c.text for t in doc.tables for row in t.rows for c in row.cells])
    else:
        text = data.decode("utf-8-sig", errors="strict")
    text = clean_text(text)[:200_000].strip()
    if not text:
        raise ValueError("No extractable text. Scanned documents require an OCR phase.")
    return text
