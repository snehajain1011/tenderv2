from __future__ import annotations

import json
import re
from collections import defaultdict

from prompts import CRITERIA_EXTRACTION_PROMPT, EVIDENCE_EXTRACTION_PROMPT
from schema import AuditEvent, BidderResult, Criterion, Document, EvaluationResult, Evidence, Verdict


MIN_CONFIDENCE = 0.65


def extract_criteria(docs: list[Document], llm=None) -> tuple[list[Criterion], list[AuditEvent]]:
    tender_text = "\n\n".join(f"### {doc.name}\n{doc.text}" for doc in docs)
    audit = [AuditEvent("load_tender", "tender", {"documents": [doc.name for doc in docs]})]

    if llm:
        prompt = CRITERIA_EXTRACTION_PROMPT.format(tender_text=tender_text[:24000])
        data = llm.generate_json(prompt)
        criteria = _criteria_from_llm(data)
        if criteria:
            audit.append(AuditEvent("extract_criteria", "llm", {"count": len(criteria)}))
            return criteria, audit
        audit.append(AuditEvent("extract_criteria", "llm_fallback", {"reason": "LLM unavailable or invalid JSON"}))

    criteria = _heuristic_criteria(tender_text)
    audit.append(AuditEvent("extract_criteria", "heuristic", {"count": len(criteria)}))
    return criteria, audit


def extract_evidence(
    criteria: list[Criterion],
    bidder_docs: dict[str, list[Document]],
    llm=None,
) -> tuple[dict[str, list[Evidence]], list[AuditEvent]]:
    evidence_by_bidder: dict[str, list[Evidence]] = {}
    audit: list[AuditEvent] = []

    for bidder, docs in bidder_docs.items():
        if llm:
            documents_text = "\n\n".join(f"### {doc.name}\n{doc.text}" for doc in docs)
            prompt = EVIDENCE_EXTRACTION_PROMPT.format(
                criteria_json=json.dumps([criterion.__dict__ for criterion in criteria], indent=2),
                documents_text=documents_text[:24000],
            )
            llm_data = llm.generate_json(prompt)
            evidence = _evidence_from_llm(bidder, llm_data)
            if evidence:
                evidence_by_bidder[bidder] = evidence
                audit.append(AuditEvent("extract_evidence", bidder, {"mode": "llm", "count": len(evidence)}))
                continue
            audit.append(AuditEvent("extract_evidence", bidder, {"mode": "llm_fallback"}))

        evidence_by_bidder[bidder] = _heuristic_evidence(bidder, criteria, docs)
        audit.append(AuditEvent("extract_evidence", bidder, {"mode": "heuristic", "count": len(evidence_by_bidder[bidder])}))

    return evidence_by_bidder, audit


def evaluate_bidders(
    criteria: list[Criterion],
    evidence_by_bidder: dict[str, list[Evidence]],
) -> tuple[EvaluationResult, list[AuditEvent]]:
    bidder_results: list[BidderResult] = []
    audit: list[AuditEvent] = []

    for bidder, evidence_items in evidence_by_bidder.items():
        evidence_by_criterion = defaultdict(list)
        for evidence in evidence_items:
            evidence_by_criterion[evidence.criterion_id].append(evidence)

        verdicts = [_evaluate_criterion(criterion, evidence_by_criterion.get(criterion.id, [])) for criterion in criteria]
        overall = _overall_status(criteria, verdicts)
        bidder_results.append(BidderResult(bidder=bidder, overall_status=overall, verdicts=verdicts))
        audit.append(AuditEvent("evaluate_bidder", bidder, {"overall_status": overall}))

    return EvaluationResult(criteria=criteria, bidders=bidder_results), audit


def _criteria_from_llm(data: object | None) -> list[Criterion]:
    if not isinstance(data, dict) or not isinstance(data.get("criteria"), list):
        return []
    criteria: list[Criterion] = []
    for index, item in enumerate(data["criteria"], start=1):
        if not isinstance(item, dict):
            continue
        criteria.append(
            Criterion(
                id=str(item.get("id") or f"C{index}"),
                category=_category(item.get("category")),
                mandatory=bool(item.get("mandatory", True)),
                description=str(item.get("description", "")),
                threshold=str(item.get("threshold", "")),
                time_period=str(item.get("time_period", "")),
                comparison_rule=str(item.get("comparison_rule", "present")),
                accepted_evidence=list(item.get("accepted_evidence", [])),
            )
        )
    return [criterion for criterion in criteria if criterion.description]


def _heuristic_criteria(text: str) -> list[Criterion]:
    lower = text.lower()
    criteria: list[Criterion] = []

    threshold = "INR 1 crore"
    turnover_lines = [line for line in text.splitlines() if "turnover" in line.lower()]
    for line in turnover_lines:
        money = _first_money_value(line)
        if money:
            threshold = money

    criteria.append(
        Criterion(
            id="C1",
            category="financial",
            mandatory=True,
            description="Average annual turnover must meet the tender threshold.",
            threshold=threshold,
            time_period="last 3 financial years",
            comparison_rule="minimum",
            accepted_evidence=["CA certificate", "audited balance sheet", "turnover certificate"],
        )
    )

    if "gst" in lower:
        criteria.append(
            Criterion(
                id="C2",
                category="compliance",
                mandatory=True,
                description="Bidder must have valid GST registration.",
                comparison_rule="valid",
                accepted_evidence=["GST registration certificate"],
            )
        )

    if "iso" in lower or "iso 9001" in lower:
        criteria.append(
            Criterion(
                id="C3",
                category="compliance",
                mandatory=True,
                description="Bidder must hold valid ISO 9001 certification.",
                comparison_rule="valid",
                accepted_evidence=["ISO 9001 certificate"],
            )
        )

    if "similar" in lower or "experience" in lower or "projects" in lower:
        criteria.append(
            Criterion(
                id="C4",
                category="technical",
                mandatory=True,
                description="Bidder must show at least 3 similar completed projects in the last 5 years.",
                threshold="3 projects",
                time_period="last 5 years",
                comparison_rule="count_at_least",
                accepted_evidence=["work orders", "completion certificates", "experience letters"],
            )
        )

    if "industrial license" in lower:
        criteria.append(
            Criterion(
                id="C5",
                category="compliance",
                mandatory=True,
                description="Bidder must provide applicable industrial license.",
                comparison_rule="present",
                accepted_evidence=["industrial license"],
            )
        )

    return criteria


def _evidence_from_llm(bidder: str, data: object | None) -> list[Evidence]:
    if not isinstance(data, dict) or not isinstance(data.get("evidence"), list):
        return []
    evidence: list[Evidence] = []
    for item in data["evidence"]:
        if not isinstance(item, dict):
            continue
        evidence.append(
            Evidence(
                criterion_id=str(item.get("criterion_id", "")),
                bidder=bidder,
                document=str(item.get("document", "")),
                value=str(item.get("value", "")),
                excerpt=str(item.get("excerpt", "")),
                confidence=float(item.get("confidence", 0) or 0),
                notes=str(item.get("notes", "")),
            )
        )
    return evidence


def _heuristic_evidence(bidder: str, criteria: list[Criterion], docs: list[Document]) -> list[Evidence]:
    evidence: list[Evidence] = []
    for criterion in criteria:
        matches = [_extract_for_criterion(bidder, criterion, doc) for doc in docs]
        matches = [match for match in matches if match is not None]
        if matches:
            evidence.extend(matches)
        else:
            evidence.append(
                Evidence(
                    criterion_id=criterion.id,
                    bidder=bidder,
                    document="",
                    value="",
                    excerpt="",
                    confidence=0.0,
                    notes="Required evidence not found.",
                )
            )
    return evidence


def _extract_for_criterion(bidder: str, criterion: Criterion, doc: Document) -> Evidence | None:
    text = doc.text
    lower = text.lower()
    if criterion.category == "financial" and "turnover" in lower:
        value = _first_money_value(text)
        return Evidence(criterion.id, bidder, doc.name, value, _excerpt(text, "turnover"), doc.confidence)

    if "gst" in criterion.description.lower() and "gst" in lower:
        value = _first_match(text, r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]\b") or "GST registration mentioned"
        return Evidence(criterion.id, bidder, doc.name, value, _excerpt(text, "GST"), doc.confidence)

    if "iso" in criterion.description.lower() and "iso" in lower:
        value = "ISO 9001" if "9001" in lower else "ISO certificate mentioned"
        return Evidence(criterion.id, bidder, doc.name, value, _excerpt(text, "ISO"), doc.confidence)

    if criterion.category == "technical" and any(word in lower for word in ["project", "completion", "work order", "experience"]):
        count = _project_count(text)
        value = f"{count} similar projects"
        return Evidence(criterion.id, bidder, doc.name, value, _excerpt(text, "project"), doc.confidence)

    if "industrial license" in criterion.description.lower() and "industrial license" in lower:
        return Evidence(criterion.id, bidder, doc.name, "Industrial license present", _excerpt(text, "industrial license"), doc.confidence)

    return None


def _evaluate_criterion(criterion: Criterion, evidence_items: list[Evidence]) -> Verdict:
    usable = [item for item in evidence_items if item.value.strip()]
    if not usable:
        return Verdict(
            criterion_id=criterion.id,
            status="REVIEW",
            reason="No usable evidence was found for this criterion.",
            document="",
            value="",
            manual_review_reason="Required document or value missing.",
        )

    best = max(usable, key=lambda item: item.confidence)
    if best.confidence < MIN_CONFIDENCE:
        return Verdict(
            criterion_id=criterion.id,
            status="REVIEW",
            reason="Evidence was found but extraction confidence is below the review threshold.",
            document=best.document,
            value=best.value,
            manual_review_reason="Low OCR or parsing confidence.",
        )

    if criterion.comparison_rule == "minimum":
        found = _money_to_crore(best.value)
        required = _money_to_crore(criterion.threshold)
        if found is None or required is None:
            return Verdict(criterion.id, "REVIEW", "Financial value could not be normalized.", best.document, best.value, "Ambiguous financial value.")
        if found >= required:
            return Verdict(criterion.id, "PASS", f"Found turnover {best.value}, meeting required {criterion.threshold}.", best.document, best.value)
        return Verdict(criterion.id, "FAIL", f"Found turnover {best.value}, below required {criterion.threshold}.", best.document, best.value)

    if criterion.comparison_rule == "count_at_least":
        found_count = _first_number(best.value)
        required_count = _first_number(criterion.threshold) or 1
        if found_count is None:
            return Verdict(criterion.id, "REVIEW", "Project count could not be verified.", best.document, best.value, "Ambiguous project experience evidence.")
        if found_count >= required_count:
            return Verdict(criterion.id, "PASS", f"Found {found_count} matching projects, meeting required {required_count}.", best.document, best.value)
        return Verdict(criterion.id, "FAIL", f"Found {found_count} matching projects, below required {required_count}.", best.document, best.value)

    if any(word in best.value.lower() for word in ["expired", "invalid", "not available"]):
        return Verdict(criterion.id, "FAIL", "Evidence indicates the required document or registration is invalid.", best.document, best.value)

    return Verdict(criterion.id, "PASS", "Required evidence is present with acceptable confidence.", best.document, best.value)


def _overall_status(criteria: list[Criterion], verdicts: list[Verdict]) -> str:
    mandatory_ids = {criterion.id for criterion in criteria if criterion.mandatory}
    mandatory_verdicts = [verdict for verdict in verdicts if verdict.criterion_id in mandatory_ids]
    if any(verdict.status == "REVIEW" for verdict in mandatory_verdicts):
        return "Need Manual Review"
    if any(verdict.status == "FAIL" for verdict in mandatory_verdicts):
        return "Not Eligible"
    return "Eligible"


def _category(value: object) -> str:
    text = str(value)
    return text if text in {"financial", "technical", "compliance", "document"} else "document"


def _first_money_value(text: str) -> str:
    match = re.search(r"(?:INR|Rs\.?|Rupees)?\s*([0-9]+(?:\.[0-9]+)?)\s*(crore|cr|lakh)", text, re.IGNORECASE)
    if not match:
        if "turnover" in text.lower() and re.search(r"(?:INR|Rs\.?|Rupees).*[?]", text, re.IGNORECASE):
            return "Ambiguous turnover value"
        return ""
    return f"INR {match.group(1)} {match.group(2)}"


def _money_to_crore(value: str) -> float | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(crore|cr|lakh)?", value, re.IGNORECASE)
    if not match:
        return None
    amount = float(match.group(1))
    unit = (match.group(2) or "crore").lower()
    if unit == "lakh":
        return amount / 100
    return amount


def _project_count(text: str) -> int:
    explicit = re.search(r"([0-9]+)\s+(?:similar\s+)?(?:completed\s+)?projects?", text, re.IGNORECASE)
    if explicit:
        return int(explicit.group(1))
    return len(re.findall(r"\bProject\s+[A-Z0-9-]+", text, re.IGNORECASE))


def _first_number(value: str) -> int | None:
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else None


def _first_match(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    return match.group(0) if match else ""


def _excerpt(text: str, needle: str, width: int = 180) -> str:
    index = text.lower().find(needle.lower())
    if index < 0:
        return text[:width].replace("\n", " ")
    start = max(0, index - 60)
    end = min(len(text), index + width)
    return text[start:end].replace("\n", " ").strip()
