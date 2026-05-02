from __future__ import annotations

import hashlib
from pathlib import Path

from schema import AuditEvent, Document, ReviewTask, Citation


TEXT_EXTENSIONS = {".txt", ".md", ".csv"}
PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | PDF_EXTENSIONS | IMAGE_EXTENSIONS


def load_tender_documents(folder: Path) -> tuple[list[Document], list[AuditEvent], list[ReviewTask]]:
    docs, audit, reviews = _load_documents(folder, subject_prefix="tender")
    if not docs:
        raise FileNotFoundError(f"No tender documents found in {folder}")
    return docs, audit, reviews


def load_bidder_documents(folder: Path) -> tuple[dict[str, list[Document]], list[AuditEvent], list[ReviewTask]]:
    if not folder.exists():
        raise FileNotFoundError(f"Bidder folder not found: {folder}")

    bidders: dict[str, list[Document]] = {}
    audit: list[AuditEvent] = []
    reviews: list[ReviewTask] = []
    for bidder_dir in sorted(path for path in folder.iterdir() if path.is_dir()):
        docs, doc_audit, doc_reviews = _load_documents(bidder_dir, subject_prefix=bidder_dir.name)
        if docs:
            bidders[bidder_dir.name] = docs
            audit.extend(doc_audit)
            reviews.extend(doc_reviews)

    if not bidders:
        raise FileNotFoundError(f"No bidder documents found in {folder}")
    return bidders, audit, reviews


def _load_documents(folder: Path, subject_prefix: str) -> tuple[list[Document], list[AuditEvent], list[ReviewTask]]:
    if not folder.exists():
        raise FileNotFoundError(f"Folder not found: {folder}")

    docs: list[Document] = []
    audit: list[AuditEvent] = []
    reviews: list[ReviewTask] = []
    for path in sorted(item for item in folder.rglob("*") if item.is_file()):
        if _effective_suffix(path) not in SUPPORTED_EXTENSIONS:
            continue
        doc = _load_one(path)
        docs.append(doc)
        audit.append(
            AuditEvent(
                "document_ingestion_checkpoint",
                f"{subject_prefix}:{doc.name}",
                {
                    "file_type": doc.source_type,
                    "parser": doc.parser,
                    "page_count": doc.page_count,
                    "ocr_or_parse_confidence": doc.confidence,
                    "checksum_sha256": doc.checksum_sha256,
                    "passed": doc.confidence >= 0.65,
                },
            )
        )
        if doc.confidence < 0.65:
            reviews.append(
                ReviewTask(
                    task_id=f"DOC-{doc.document_id[:8]}",
                    bidder=subject_prefix if subject_prefix != "tender" else "",
                    criterion_id="",
                    reason="Document parsing/OCR confidence is below threshold.",
                    priority="high",
                    source=Citation(doc.name, 1, "Document ingestion", doc.text[:240]),
                )
            )
    return docs, audit, reviews


def _load_one(path: Path) -> Document:
    suffix = _effective_suffix(path)
    checksum = _sha256(path)
    document_id = checksum[:16]
    if suffix in TEXT_EXTENSIONS:
        return _load_text(path, checksum, document_id)
    if suffix in PDF_EXTENSIONS:
        return _load_pdf(path, checksum, document_id)
    return _load_image(path, checksum, document_id)


def _load_text(path: Path, checksum: str, document_id: str) -> Document:
    text = path.read_text(encoding="utf-8")
    confidence = 0.45 if "ocr confidence note: low" in text.lower() else 1.0
    return Document(document_id, path.name, str(path), checksum, text, confidence, "text", 1, "text")


def _load_pdf(path: Path, checksum: str, document_id: str) -> Document:
    try:
        import fitz

        parts: list[str] = []
        page_count = 0
        with fitz.open(path) as pdf:
            page_count = len(pdf)
            for index, page in enumerate(pdf, start=1):
                page_text = page.get_text("text").strip()
                if page_text:
                    parts.append(f"[page {index}]\n{page_text}")
        confidence = 0.95 if parts else 0.35
        text = "\n\n".join(parts) if parts else "PDF text could not be extracted; OCR/manual review required."
        return Document(document_id, path.name, str(path), checksum, text, confidence, "pdf", max(page_count, 1), "pymupdf")
    except Exception as exc:
        return Document(document_id, path.name, str(path), checksum, f"PDF parser failed: {exc}", 0.2, "pdf", 1, "pymupdf")


def _load_image(path: Path, checksum: str, document_id: str) -> Document:
    rapid = _load_image_with_rapidocr(path, checksum, document_id)
    if rapid:
        return rapid
    tesseract = _load_image_with_tesseract(path, checksum, document_id)
    if tesseract:
        return tesseract
    return Document(
        document_id,
        path.name,
        str(path),
        checksum,
        "OCR failed: install rapidocr-onnxruntime or Tesseract OCR to parse image submissions.",
        0.2,
        "image",
        1,
        "ocr_unavailable",
    )


def _load_image_with_rapidocr(path: Path, checksum: str, document_id: str) -> Document | None:
    try:
        from rapidocr_onnxruntime import RapidOCR

        result, _ = RapidOCR()(str(path))
        if not result:
            return Document(document_id, path.name, str(path), checksum, "OCR completed but no text was detected.", 0.3, "image", 1, "rapidocr")
        lines = [str(item[1]).strip() for item in result if len(item) >= 2 and str(item[1]).strip()]
        scores = [float(item[2]) for item in result if len(item) >= 3]
        text = "\n".join(lines).strip()
        average_score = sum(scores) / len(scores) if scores else 0.0
        density_bonus = 0.1 if len(text) >= 120 else 0.0
        confidence = min(0.98, max(0.35, average_score + density_bonus)) if text else 0.3
        return Document(document_id, path.name, str(path), checksum, text, confidence, "image", 1, "rapidocr")
    except Exception:
        return None


def _load_image_with_tesseract(path: Path, checksum: str, document_id: str) -> Document | None:
    try:
        from PIL import Image, ImageOps
        import pytesseract

        image = Image.open(path)
        text = pytesseract.image_to_string(_prepare_ocr_image(image)).strip()
        confidence = 0.75 if len(text) >= 80 else 0.45 if text else 0.25
        return Document(document_id, path.name, str(path), checksum, text or "OCR completed but no text was detected.", confidence, "image", 1, "tesseract")
    except Exception:
        return None


def _prepare_ocr_image(image):
    from PIL import ImageOps

    grayscale = ImageOps.grayscale(image)
    width, height = grayscale.size
    scale = max(1, min(3, 1600 // max(width, 1)))
    if scale > 1:
        grayscale = grayscale.resize((width * scale, height * scale))
    return ImageOps.autocontrast(grayscale)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _effective_suffix(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix:
        return suffix
    lower_name = path.name.lower()
    if lower_name.endswith("_pdf"):
        return ".pdf"
    if lower_name.endswith("_txt"):
        return ".txt"
    return suffix
