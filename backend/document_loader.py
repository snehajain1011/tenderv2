from __future__ import annotations

import hashlib
import re
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

from schema import AuditEvent, Citation, Document, DocumentQuality, ReviewTask


TEXT_EXTENSIONS = {".txt", ".md", ".csv"}
DOCX_EXTENSIONS = {".docx"}
DOC_EXTENSIONS = {".doc"}
PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | DOCX_EXTENSIONS | DOC_EXTENSIONS | PDF_EXTENSIONS | IMAGE_EXTENSIONS


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
                    "document_quality": _quality_dict(doc.quality),
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
                    issue_type="LOW_OCR_CONFIDENCE" if doc.source_type == "image" else "UNSUPPORTED_FORMAT",
                    extracted_value="",
                    confidence=doc.confidence,
                    suggested_action="Inspect the source document image/PDF quality and request a clearer copy if the text is unreadable.",
                )
            )
    return docs, audit, reviews


def _load_one(path: Path) -> Document:
    suffix = _effective_suffix(path)
    checksum = _sha256(path)
    document_id = checksum[:16]
    if suffix in TEXT_EXTENSIONS:
        return _load_text(path, checksum, document_id)
    if suffix in DOCX_EXTENSIONS:
        return _load_docx(path, checksum, document_id)
    if suffix in DOC_EXTENSIONS:
        return _load_doc(path, checksum, document_id)
    if suffix in PDF_EXTENSIONS:
        return _load_pdf(path, checksum, document_id)
    return _load_image(path, checksum, document_id)


def _load_text(path: Path, checksum: str, document_id: str) -> Document:
    try:
        text = path.read_text(encoding="utf-8")
        confidence = 0.45 if "ocr confidence note: low" in text.lower() else 1.0
    except UnicodeDecodeError:
        # Do not crash evaluation when an uploaded text-like file is binary/invalid UTF-8.
        text = "Text file could not be decoded as UTF-8; manual review required."
        confidence = 0.2
    quality = _document_quality(text, confidence, "text", 1, "", "")
    return Document(document_id, path.name, str(path), checksum, text, confidence, "text", 1, "text", quality)

def _load_docx(path: Path, checksum: str, document_id: str) -> Document:
    try:
        with ZipFile(path) as archive:
            xml_content = archive.read("word/document.xml")
    except (BadZipFile, KeyError, FileNotFoundError):
        text = "DOCX could not be parsed; manual review required."
        quality = _document_quality(text, 0.2, "docx", 1, "", "")
        return Document(document_id, path.name, str(path), checksum, text, 0.2, "text", 1, "docx", quality)
    root = ET.fromstring(xml_content)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = [
        "".join(node.text or "" for node in para.findall(".//w:t", namespace)).strip()
        for para in root.findall(".//w:p", namespace)
    ]
    lines = [line for line in paragraphs if line]
    text = "\n".join(lines).strip() or "DOCX parsed but no visible text found."
    confidence = 0.9 if lines else 0.3
    quality = _document_quality(text, confidence, "docx", 1, "", "")
    return Document(document_id, path.name, str(path), checksum, text, confidence, "text", 1, "docx", quality)

def _load_doc(path: Path, checksum: str, document_id: str) -> Document:
    text = "Legacy .doc files are not parsed in this prototype; convert to .docx or .pdf for evaluation."
    quality = _document_quality(text, 0.2, "doc", 1, "", "")
    return Document(document_id, path.name, str(path), checksum, text, 0.2, "text", 1, "doc", quality)

def _load_pdf(path: Path, checksum: str, document_id: str) -> Document:
    try:
        import fitz

        page_texts: list[tuple[int, str]] = []
        page_count = 0
        with fitz.open(path) as pdf:
            page_count = len(pdf)
            for index, page in enumerate(pdf, start=1):
                page_text = page.get_text("text").strip()
                page_texts.append((index, page_text))

            embedded_word_count = sum(len(re.findall(r"\w+", page_text)) for _, page_text in page_texts)
            run_pdf_ocr = embedded_word_count < max(25, page_count * 8)
            parts: list[str] = []
            empty_pages: list[int] = []
            used_page_ocr = False
            for index, page_text in page_texts:
                if page_text:
                    parts.append(f"[page {index}]\n{page_text}")
                else:
                    empty_pages.append(index)
                    if not run_pdf_ocr:
                        continue
                    page = pdf[index - 1]
                    ocr_text, ocr_confidence, ocr_engine, quality_flags = _ocr_pdf_page(page, index)
                    if ocr_text:
                        used_page_ocr = True
                        parts.append(f"[page {index}]\n{ocr_text}")
                        empty_pages.pop()
        confidence = 0.95 if parts else 0.35
        if empty_pages and parts:
            confidence = min(confidence, 0.68)
        text = "\n\n".join(parts) if parts else "PDF text could not be extracted; OCR/manual review required."
        parser = "pymupdf+ocr" if used_page_ocr else "pymupdf"
        quality = _document_quality(text, confidence, parser, max(page_count, 1), "", "", empty_pages)
        return Document(document_id, path.name, str(path), checksum, text, confidence, "pdf", max(page_count, 1), parser, quality)
    except Exception as exc:
        text = f"PDF parser failed: {exc}"
        quality = _document_quality(text, 0.2, "pymupdf", 1, "", "", [1], ["parser_failed"])
        return Document(document_id, path.name, str(path), checksum, text, 0.2, "pdf", 1, "pymupdf", quality)


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
        _document_quality("", 0.2, "ocr_unavailable", 1, "", "", [1], ["ocr_unavailable"]),
    )


def _load_image_with_rapidocr(path: Path, checksum: str, document_id: str) -> Document | None:
    try:
        from rapidocr_onnxruntime import RapidOCR

        result, _ = RapidOCR()(str(path))
        if not result:
            quality = _image_quality(path, "", 0.3, "rapidocr", ["empty_ocr"])
            return Document(document_id, path.name, str(path), checksum, "OCR completed but no text was detected.", 0.3, "image", 1, "rapidocr", quality)
        lines = [str(item[1]).strip() for item in result if len(item) >= 2 and str(item[1]).strip()]
        scores = [float(item[2]) for item in result if len(item) >= 3]
        text = "\n".join(lines).strip()
        average_score = sum(scores) / len(scores) if scores else 0.0
        density_bonus = 0.1 if len(text) >= 120 else 0.0
        confidence = min(0.98, max(0.35, average_score + density_bonus)) if text else 0.3
        quality = _image_quality(path, text, confidence, "rapidocr")
        return Document(document_id, path.name, str(path), checksum, text, confidence, "image", 1, "rapidocr", quality)
    except Exception:
        return None


def _load_image_with_tesseract(path: Path, checksum: str, document_id: str) -> Document | None:
    try:
        from PIL import Image, ImageOps
        import pytesseract

        image = Image.open(path)
        text = pytesseract.image_to_string(_prepare_ocr_image(image)).strip()
        confidence = 0.75 if len(text) >= 80 else 0.45 if text else 0.25
        text = text or "OCR completed but no text was detected."
        quality = _image_quality(path, text, confidence, "tesseract", [] if text else ["empty_ocr"])
        return Document(document_id, path.name, str(path), checksum, text, confidence, "image", 1, "tesseract", quality)
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


def _ocr_pdf_page(page, page_number: int) -> tuple[str, float, str, list[str]]:
    try:
        from PIL import Image
        from rapidocr_onnxruntime import RapidOCR

        pix = page.get_pixmap(matrix=__import__("fitz").Matrix(2, 2), alpha=False)
        image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        prepared = _prepare_ocr_image(image)
        temp_path = Path(f".ocr_page_{page_number}.png")
        try:
            prepared.save(temp_path)
            result, _ = RapidOCR()(str(temp_path))
        finally:
            if temp_path.exists():
                temp_path.unlink()
        if not result:
            return "", 0.3, "rapidocr", ["empty_ocr"]
        lines = [str(item[1]).strip() for item in result if len(item) >= 2 and str(item[1]).strip()]
        scores = [float(item[2]) for item in result if len(item) >= 3]
        confidence = sum(scores) / len(scores) if scores else 0.4
        return "\n".join(lines), confidence, "rapidocr", []
    except Exception:
        return "", 0.2, "rapidocr", ["pdf_page_ocr_failed"]


def _document_quality(
    text: str,
    confidence: float,
    engine: str,
    page_count: int,
    image_resolution: str,
    source_type: str,
    empty_pages: list[int] | None = None,
    quality_flags: list[str] | None = None,
) -> DocumentQuality:
    flags = list(quality_flags or [])
    density = _text_density(text, page_count)
    if density < 40:
        flags.append("low_text_density")
    if confidence < 0.65:
        flags.append("low_confidence")
    tables = _tables_detected(text)
    return DocumentQuality(
        text_density=density,
        ocr_engine=engine if "ocr" in engine or engine in {"rapidocr", "tesseract", "ocr_unavailable"} else "",
        ocr_confidence=confidence,
        image_resolution=image_resolution,
        skew_or_blur_detected="blur" in flags or "skew" in flags,
        page_count=page_count,
        empty_pages=empty_pages or [],
        tables_detected=tables,
        quality_flags=sorted(set(flags)),
    )


def _image_quality(path: Path, text: str, confidence: float, engine: str, extra_flags: list[str] | None = None) -> DocumentQuality:
    flags = list(extra_flags or [])
    resolution = ""
    try:
        from PIL import Image, ImageStat

        image = Image.open(path)
        resolution = f"{image.width}x{image.height}"
        if min(image.width, image.height) < 700:
            flags.append("low_resolution")
        grayscale = image.convert("L")
        if ImageStat.Stat(grayscale).stddev[0] < 18:
            flags.append("low_contrast_or_blur")
    except Exception:
        flags.append("image_quality_unavailable")
    return _document_quality(text, confidence, engine, 1, resolution, "image", [] if text else [1], flags)


def _text_density(text: str, page_count: int) -> float:
    return len(re.findall(r"\w+", text)) / max(page_count, 1)


_CURRENCY_PATTERN = re.compile(
    r"(?:"
    r"Rs\.?|INR|₹"           # Indian Rupee
    r"|USD|\$"               # US Dollar
    r"|EUR|€"                # Euro
    r"|GBP|£"                # British Pound
    r"|JPY|¥"                # Japanese Yen / Chinese Yuan
    r"|CNY|RMB"              # Chinese Yuan
    r"|AED|AUD|CAD|CHF"      # UAE Dirham, Australian/Canadian Dollar, Swiss Franc
    r"|SGD|MYR|BDT|PKR|LKR"  # SE Asia / South Asia
    r")\s*[0-9]",
    re.IGNORECASE,
)


def _tables_detected(text: str) -> int:
    rows = 0
    for line in text.splitlines():
        has_money = bool(_CURRENCY_PATTERN.search(line))
        has_columns = line.count("|") >= 2 or len(re.findall(r"\s{2,}", line)) >= 2
        if has_money or has_columns:
            rows += 1
    return rows


def _quality_dict(quality: DocumentQuality) -> dict[str, object]:
    return {
        "text_density": quality.text_density,
        "ocr_engine": quality.ocr_engine,
        "ocr_confidence": quality.ocr_confidence,
        "image_resolution": quality.image_resolution,
        "skew_or_blur_detected": quality.skew_or_blur_detected,
        "page_count": quality.page_count,
        "empty_pages": quality.empty_pages,
        "tables_detected": quality.tables_detected,
        "quality_flags": quality.quality_flags,
    }


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
