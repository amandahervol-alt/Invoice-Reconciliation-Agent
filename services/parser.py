import os
import io
from typing import Union
import pypdf

def extract_invoice_text(file_source: Union[str, bytes], filename: str = "") -> str:
    """
    Extracts raw text from a PDF or text file.
    Supports either a filepath string or raw bytes.
    """
    if isinstance(file_source, str):
        if not os.path.exists(file_source):
            raise FileNotFoundError(f"Invoice file not found: {file_source}")
        
        ext = os.path.splitext(file_source)[1].lower()
        if ext == ".pdf":
            with open(file_source, "rb") as f:
                return _extract_from_pdf_bytes(f.read())
        else:
            with open(file_source, "r", encoding="utf-8", errors="replace") as f:
                return f.read()

    elif isinstance(file_source, bytes):
        ext = os.path.splitext(filename)[1].lower() if filename else ""
        if ext == ".pdf" or file_source.startswith(b"%PDF"):
            return _extract_from_pdf_bytes(file_source)
        else:
            try:
                return file_source.decode("utf-8")
            except UnicodeDecodeError:
                return file_source.decode("latin-1", errors="replace")

    else:
        raise ValueError("Invalid file_source: must be filepath str or bytes.")

def _extract_from_pdf_bytes(file_bytes: bytes) -> str:
    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    pages_text = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            pages_text.append(text.strip())
    return "\n\n".join(pages_text)
