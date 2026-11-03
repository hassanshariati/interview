from io import BytesIO
from pathlib import Path
from docx import Document
from pypdf import PdfReader

ACCEPTED = {".pdf", ".docx", ".txt"}
MAX_BYTES = 8 * 1024 * 1024

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
    text = text[:200_000].strip()
    if not text:
        raise ValueError("No extractable text. Scanned documents require an OCR phase.")
    return text
