from __future__ import annotations

from pathlib import Path

from schema import Document


TEXT_EXTENSIONS = {".txt", ".md", ".csv"}
PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}


def load_tender_documents(folder: Path) -> list[Document]:
    docs = _load_documents(folder)
    if not docs:
        raise FileNotFoundError(f"No tender documents found in {folder}")
    return docs


def load_bidder_documents(folder: Path) -> dict[str, list[Document]]:
    if not folder.exists():
        raise FileNotFoundError(f"Bidder folder not found: {folder}")

    bidders: dict[str, list[Document]] = {}
    for bidder_dir in sorted(path for path in folder.iterdir() if path.is_dir()):
        docs = _load_documents(bidder_dir)
        if docs:
            bidders[bidder_dir.name] = docs

    if not bidders:
        raise FileNotFoundError(f"No bidder documents found in {folder}")
    return bidders


def _load_documents(folder: Path) -> list[Document]:
    if not folder.exists():
        raise FileNotFoundError(f"Folder not found: {folder}")

    docs: list[Document] = []
    for path in sorted(item for item in folder.rglob("*") if item.is_file()):
        suffix = path.suffix.lower()
        if suffix in TEXT_EXTENSIONS:
            docs.append(_load_text(path))
        elif suffix in PDF_EXTENSIONS:
            docs.append(_load_pdf(path))
        elif suffix in IMAGE_EXTENSIONS:
            docs.append(_load_image(path))
    return docs


def _load_text(path: Path) -> Document:
    text = path.read_text(encoding="utf-8")
    confidence = 0.45 if "ocr confidence note: low" in text.lower() else 1.0
    return Document(name=path.name, path=str(path), text=text, confidence=confidence, source_type="text")


def _load_pdf(path: Path) -> Document:
    try:
        import fitz  # PyMuPDF

        parts: list[str] = []
        with fitz.open(path) as pdf:
            for index, page in enumerate(pdf, start=1):
                page_text = page.get_text("text").strip()
                if page_text:
                    parts.append(f"[page {index}]\n{page_text}")
        confidence = 0.95 if parts else 0.35
        text = "\n\n".join(parts) if parts else "PDF text could not be extracted; OCR/manual review required."
        return Document(name=path.name, path=str(path), text=text, confidence=confidence, source_type="pdf")
    except Exception as exc:
        return Document(
            name=path.name,
            path=str(path),
            text=f"PDF parser unavailable or failed: {exc}",
            confidence=0.2,
            source_type="pdf",
        )


def _load_image(path: Path) -> Document:
    try:
        from PIL import Image
        import pytesseract

        text = pytesseract.image_to_string(Image.open(path)).strip()
        confidence = 0.7 if text else 0.25
        return Document(name=path.name, path=str(path), text=text, confidence=confidence, source_type="image")
    except Exception as exc:
        return Document(
            name=path.name,
            path=str(path),
            text=f"OCR unavailable or failed: {exc}",
            confidence=0.2,
            source_type="image",
        )
