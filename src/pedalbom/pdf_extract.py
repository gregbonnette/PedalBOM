from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


def extract_pdf_text(path: str | Path) -> str:
    pdf_path = Path(path)
    reader = PdfReader(str(pdf_path))
    pages: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append(f"\n--- PAGE {index} ---\n{text}")
    return "\n".join(pages)
