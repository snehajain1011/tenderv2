from __future__ import annotations

import math
import re
from collections import Counter

from schema import AuditEvent, Citation, Document, RagChunk, RetrievalHit


MIN_RETRIEVAL_SCORE = 0.08


class RagIndex:
    def __init__(self, chunks: list[RagChunk]) -> None:
        self.chunks = chunks
        self._vectors = [_vector(chunk.text) for chunk in chunks]

    def retrieve(self, query: str, top_k: int = 4) -> list[RetrievalHit]:
        query_vector = _vector(query)
        scored = [
            RetrievalHit(chunk=chunk, score=_cosine(query_vector, vector))
            for chunk, vector in zip(self.chunks, self._vectors)
        ]
        return [hit for hit in sorted(scored, key=lambda item: item.score, reverse=True)[:top_k] if hit_score_ok(hit)]


def build_rag_index(documents: list[Document]) -> tuple[RagIndex, list[AuditEvent], list[str]]:
    chunks = chunk_documents(documents)
    issues = validate_chunks(chunks)
    audit = [
        AuditEvent(
            "chunking_and_indexing_checkpoint",
            "rag",
            {"chunk_count": len(chunks), "passed": not issues, "issues": issues},
        )
    ]
    return RagIndex(chunks), audit, issues


def chunk_documents(documents: list[Document], max_chars: int = 900) -> list[RagChunk]:
    chunks: list[RagChunk] = []
    for doc in documents:
        paragraphs = [item.strip() for item in re.split(r"\n\s*\n", doc.text) if item.strip()]
        offset = 0
        current = ""
        start = 0
        chunk_index = 1
        for paragraph in paragraphs or [doc.text]:
            if current and len(current) + len(paragraph) > max_chars:
                chunks.append(_chunk(doc, current, start, offset, chunk_index))
                chunk_index += 1
                current = ""
                start = offset
            current = f"{current}\n\n{paragraph}".strip()
            offset += len(paragraph) + 2
        if current:
            chunks.append(_chunk(doc, current, start, min(len(doc.text), offset), chunk_index))
    return chunks


def citation_from_hit(hit: RetrievalHit, section: str = "") -> Citation:
    chunk = hit.chunk
    return Citation(
        document=chunk.document_name,
        page=chunk.page,
        section=section or chunk.section,
        excerpt=chunk.text[:500],
        chunk_id=chunk.chunk_id,
    )


def validate_retrieval(hits: list[RetrievalHit], subject: str) -> AuditEvent:
    return AuditEvent(
        "retrieval_checkpoint",
        subject,
        {
            "top_k_returned": len(hits),
            "best_score": hits[0].score if hits else 0.0,
            "min_score": MIN_RETRIEVAL_SCORE,
            "passed": bool(hits),
        },
    )


def validate_grounded_value(value: str, citation: Citation, subject: str) -> AuditEvent:
    normalized_value = _norm(value)
    normalized_excerpt = _norm(citation.excerpt)
    found = not normalized_value or normalized_value in normalized_excerpt
    return AuditEvent(
        "grounded_extraction_checkpoint",
        subject,
        {"value": value, "source_document": citation.document, "passed": found},
    )


def validate_chunks(chunks: list[RagChunk]) -> list[str]:
    issues: list[str] = []
    for chunk in chunks:
        if not chunk.chunk_id or not chunk.document_name or not chunk.text or chunk.start < 0 or chunk.end < chunk.start:
            issues.append(f"Invalid trace metadata for chunk {chunk.chunk_id or '<missing>'}")
    return issues


def hit_score_ok(hit: RetrievalHit) -> bool:
    return hit.score >= MIN_RETRIEVAL_SCORE


def _chunk(doc: Document, text: str, start: int, end: int, index: int) -> RagChunk:
    first_line = text.splitlines()[0][:80] if text.splitlines() else "Document"
    return RagChunk(
        chunk_id=f"{doc.document_id}:{index}",
        document_id=doc.document_id,
        document_name=doc.name,
        text=text,
        page=_page_number(text),
        section=first_line,
        start=start,
        end=end,
        quality_flags=doc.quality.quality_flags,
    )


def _page_number(text: str) -> int:
    match = re.search(r"\[page\s+(\d+)\]", text, re.IGNORECASE)
    return int(match.group(1)) if match else 1


def _vector(text: str) -> Counter[str]:
    return Counter(re.findall(r"[a-z0-9]+", text.lower()))


def _cosine(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    numerator = sum(a[key] * b.get(key, 0) for key in a)
    denom_a = math.sqrt(sum(value * value for value in a.values()))
    denom_b = math.sqrt(sum(value * value for value in b.values()))
    return numerator / (denom_a * denom_b) if denom_a and denom_b else 0.0


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()
