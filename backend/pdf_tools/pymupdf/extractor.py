"""Extract one PDF to Markdown and parser-compatible layout JSON."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def extract_pdf(pdf_path: Path, output_dir: Path) -> tuple[Path, Path, dict[str, Any]]:
    """Write Markdown and a lightweight layout JSON for company candidate parsing."""
    try:
        import pymupdf4llm
    except ImportError as exc:
        raise RuntimeError("PyMuPDF extractor requires PyMuPDF and pymupdf4llm. Install backend/requirements.txt.") from exc

    pdf_path = Path(pdf_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / f"{pdf_path.stem}.md"
    json_path = output_dir / f"{pdf_path.stem}.json"
    markdown = pymupdf4llm.to_markdown(str(pdf_path), write_images=False)
    markdown_path.write_text(markdown, encoding="utf-8")

    # Keep the same broad shape consumed by extract_company_candidates.py.
    try:
        import pymupdf
    except ImportError:
        import fitz as pymupdf
    elements: list[dict[str, Any]] = []
    with pymupdf.open(str(pdf_path)) as document:
        page_count = len(document)
        for page_number, page in enumerate(document, start=1):
            for block in page.get_text("blocks"):
                text = str(block[4]).strip() if len(block) > 4 else ""
                if text:
                    elements.append({"content": text, "page number": page_number, "bounding box": list(block[:4])})
    payload = {"file name": pdf_path.name, "number of pages": page_count, "elements": elements}
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return json_path, markdown_path, {"elements": len(elements), "pages": payload["number of pages"], "characters": len(markdown)}
