from __future__ import annotations

import json
import re
from collections import defaultdict

from prompts import CRITERIA_EXTRACTION_PROMPT, EVIDENCE_EXTRACTION_PROMPT
from rag import citation_from_hit, validate_grounded_value, validate_retrieval
from schema import (
    AgentDefinition,
    AuditEvent,
    BidderResult,
    Citation,
    Criterion,
    Document,
    EvaluationResult,
    Evidence,
    ReviewTask,
    Verdict,
)


MIN_CONFIDENCE = 0.65
ACTION_LOW_CONFIDENCE = "Open the cited page/image, verify the extracted value manually, and request a clearer copy if unreadable."
ACTION_MISSING = "Ask the bidder to identify the required document/value or mark the submission incomplete after officer review."
ACTION_AMBIGUOUS = "Escalate to the procurement officer/technical committee because the value or clause cannot be safely interpreted automatically."
ACTION_CONFLICT = "Compare the cited documents manually and record the accepted value before finalizing eligibility."


def agent_catalog() -> list[AgentDefinition]:
    return [
        AgentDefinition("Requirement Structuring Agent", "pre_tender", "Structures department needs into procurement fields.", ["requirements"], ["structured_requirements"]),
        AgentDefinition("Tender Drafting Agent", "pre_tender", "Drafts tender package sections and checklist.", ["structured_requirements"], ["tender_package"]),
        AgentDefinition("Compliance Policy Agent", "pre_tender", "Checks policy, legal, local supplier, MSME/startup, and bid-security clauses.", ["tender_package"], ["compliance_findings"]),
        AgentDefinition("Risk Review Agent", "pre_tender", "Flags vague, restrictive, or unverifiable tender clauses.", ["tender_package"], ["risk_findings"]),
        AgentDefinition("Publication Agent", "pre_tender", "Prepares GeM/CPPP-ready publication metadata.", ["tender_package"], ["publication_pack"]),
        AgentDefinition("Vendor Registration Agent", "tender", "Validates vendor profile and statutory identifiers.", ["vendor_profile"], ["vendor_status"]),
        AgentDefinition("Submission Intake Agent", "tender", "Stores immutable submissions with timestamps and hashes.", ["bid_documents"], ["submission_record"]),
        AgentDefinition("Document Understanding Agent", "tender", "Parses PDFs, scans, photos, tables, and certificates.", ["documents"], ["parsed_documents"], "vision"),
        AgentDefinition("RAG Retrieval Agent", "tender", "Retrieves source-grounded tender clauses and bidder evidence.", ["criteria", "chunks"], ["retrieval_hits"], "embeddings"),
        AgentDefinition("Criteria Extraction Agent", "tender", "Extracts mandatory/optional criteria with tender citations.", ["tender_documents"], ["criteria"]),
        AgentDefinition("Evidence Mapping Agent", "tender", "Maps bidder evidence to criteria with citations and confidence.", ["criteria", "bid_documents"], ["evidence"]),
        AgentDefinition("Responsiveness Agent", "tender", "Checks completeness, EMD, signatures, validity, and prescribed formats.", ["submission_record"], ["responsiveness_verdicts"]),
        AgentDefinition("Technical Evaluation Agent", "tender", "Evaluates technical specs, experience, certifications, licenses, and deviations.", ["evidence"], ["technical_verdicts"]),
        AgentDefinition("Financial Evaluation Agent", "tender", "Normalizes prices, taxes, discounts, arithmetic errors, and L1 ranking.", ["financial_bid"], ["financial_verdicts"]),
        AgentDefinition("Human Review Agent", "tender", "Routes uncertain cases with source snippets and reasons.", ["review_reasons"], ["review_tasks"]),
        AgentDefinition("Consolidated Report Agent", "tender", "Creates bid matrix, comparison reports, rejection reasons, and recommendations.", ["verdicts"], ["reports"]),
        AgentDefinition("Award Recommendation Agent", "post_tender", "Generates award justification and rejected bidder reasons.", ["final_evaluation"], ["award_pack"]),
        AgentDefinition("Contract Generation Agent", "post_tender", "Drafts PO/contract from awarded terms.", ["award_pack"], ["contract_draft"]),
        AgentDefinition("Contract Compliance Agent", "post_tender", "Tracks delivery, warranty, performance security, invoices, and deviations.", ["contract"], ["contract_status"]),
        AgentDefinition("Vendor Performance Agent", "post_tender", "Maintains vendor scorecards.", ["contract_status"], ["vendor_scorecard"]),
        AgentDefinition("Audit & RTI Support Agent", "post_tender", "Exports complete decision trail.", ["audit_log"], ["audit_export"]),
    ]


def extract_criteria(docs: list[Document], tender_index, llm=None) -> tuple[list[Criterion], list[AuditEvent]]:
    tender_text = "\n\n".join(f"### {doc.name}\n{doc.text}" for doc in docs)
    audit = [AuditEvent("criteria_extraction_agent", "tender", {"documents": [doc.name for doc in docs]})]

    if llm:
        prompt = CRITERIA_EXTRACTION_PROMPT.format(tender_text=tender_text[:24000])
        data = llm.generate_json(prompt)
        criteria = _criteria_from_llm(data, tender_index)
        if criteria:
            audit.append(AuditEvent("criteria_extraction_agent", "llm", {"count": len(criteria)}))
            return criteria, audit
        audit.append(AuditEvent("criteria_extraction_agent", "llm_fallback", {"reason": "LLM unavailable or invalid JSON"}))

    criteria = _heuristic_criteria(tender_text, tender_index)
    audit.append(AuditEvent("criteria_extraction_agent", "heuristic", {"count": len(criteria)}))
    return criteria, audit


def extract_evidence(
    criteria: list[Criterion],
    bidder_docs: dict[str, list[Document]],
    bidder_indexes: dict[str, object],
    llm=None,
) -> tuple[dict[str, list[Evidence]], list[AuditEvent], list[ReviewTask]]:
    evidence_by_bidder: dict[str, list[Evidence]] = {}
    audit: list[AuditEvent] = []
    reviews: list[ReviewTask] = []

    for bidder, docs in bidder_docs.items():
        if llm:
            documents_text = "\n\n".join(f"### {doc.name}\n{doc.text}" for doc in docs)
            prompt = EVIDENCE_EXTRACTION_PROMPT.format(
                criteria_json=json.dumps([criterion.__dict__ for criterion in criteria], default=str, indent=2),
                documents_text=documents_text[:24000],
            )
            llm_data = llm.generate_json(prompt)
            evidence = _evidence_from_llm(bidder, criteria, llm_data)
            if evidence:
                evidence_by_bidder[bidder] = evidence
                audit.append(AuditEvent("evidence_mapping_agent", bidder, {"mode": "llm", "count": len(evidence)}))
                continue
            audit.append(AuditEvent("evidence_mapping_agent", bidder, {"mode": "llm_fallback"}))

        evidence = _heuristic_evidence(bidder, criteria, bidder_indexes[bidder], docs)
        evidence_by_bidder[bidder] = evidence
        audit.append(AuditEvent("evidence_mapping_agent", bidder, {"mode": "heuristic", "count": len(evidence)}))
        for item in evidence:
            audit.append(validate_grounded_value(item.value, item.bidder_citation, f"{bidder}:{item.criterion_id}"))
            if item.confidence < MIN_CONFIDENCE and item.document and item.value.strip():
                reviews.append(
                    _review_task(
                        bidder,
                        item.criterion_id,
                        "Low evidence confidence or OCR uncertainty.",
                        item.bidder_citation,
                        "LOW_OCR_CONFIDENCE",
                        item.value,
                        item.confidence,
                        ACTION_LOW_CONFIDENCE,
                    )
                )

    return evidence_by_bidder, audit, reviews


def evaluate_bidders(
    tender_id: str,
    criteria: list[Criterion],
    evidence_by_bidder: dict[str, list[Evidence]],
    existing_reviews: list[ReviewTask] | None = None,
) -> tuple[EvaluationResult, list[AuditEvent]]:
    bidder_results: list[BidderResult] = []
    audit: list[AuditEvent] = []
    existing_reviews = existing_reviews or []
    l1_prices = _l1_prices(criteria, evidence_by_bidder)

    for bidder, evidence_items in evidence_by_bidder.items():
        evidence_by_criterion = defaultdict(list)
        for evidence in evidence_items:
            evidence_by_criterion[evidence.criterion_id].append(evidence)

        verdicts: list[Verdict] = []
        review_tasks = [task for task in existing_reviews if task.bidder == bidder]
        for criterion in criteria:
            verdict = _evaluate_criterion(criterion, evidence_by_criterion.get(criterion.id, []), l1_prices.get(criterion.id), bidder)
            verdicts.append(verdict)
            audit.append(
                AuditEvent(
                    "rule_evaluation_checkpoint",
                    f"{bidder}:{criterion.id}",
                    {"status": verdict.status, "rule_trace": verdict.rule_trace, "passed": bool(verdict.rule_trace)},
                )
            )
            if verdict.status == "NEED_MANUAL_REVIEW":
                review_tasks.append(
                    _review_task(
                        bidder,
                        criterion.id,
                        verdict.manual_review_reason,
                        verdict.bidder_source,
                        verdict.uncertainty_type or "VALUE_NOT_FOUND",
                        verdict.extracted_value,
                        verdict.confidence,
                        verdict.suggested_action,
                    )
                )

        conflicts = _find_conflicts(evidence_items)
        for criterion_id, reason, source in conflicts:
            audit.append(AuditEvent("contradiction_checkpoint", f"{bidder}:{criterion_id}", {"passed": False, "reason": reason}))
            review_tasks.append(_review_task(bidder, criterion_id, reason, source, "CONFLICTING_EVIDENCE", "", 0.0, ACTION_CONFLICT))
            verdicts = [_force_review(verdict, reason) if verdict.criterion_id == criterion_id else verdict for verdict in verdicts]

        review_tasks = _dedupe_review_tasks(review_tasks)
        overall = _overall_status(criteria, verdicts)
        bidder_results.append(BidderResult(bidder=bidder, overall_status=overall, verdicts=verdicts, review_tasks=review_tasks))
        audit.append(AuditEvent("evaluate_bidder", bidder, {"overall_status": overall}))

    result = EvaluationResult(
        tender_id=tender_id,
        criteria=criteria,
        bidders=bidder_results,
        agents=agent_catalog(),
        final_accuracy_gate_passed=False,
        final_accuracy_issues=[],
    )
    issues = final_accuracy_gate(result)
    result = EvaluationResult(tender_id, criteria, bidder_results, agent_catalog(), not issues, issues)
    audit.append(AuditEvent("final_accuracy_gate", tender_id, {"passed": not issues, "issues": issues}))
    return result, audit


def final_accuracy_gate(result: EvaluationResult) -> list[str]:
    issues: list[str] = []
    for bidder in result.bidders:
        for verdict in bidder.verdicts:
            if not verdict.criterion_id or not verdict.criterion or not verdict.reason or not verdict.status:
                issues.append(f"{bidder.bidder}:{verdict.criterion_id}: missing verdict basics")
            if not verdict.tender_source.document or not verdict.tender_source.excerpt:
                issues.append(f"{bidder.bidder}:{verdict.criterion_id}: missing tender source citation")
            if verdict.status in {"PASS", "FAIL"} and (not verdict.bidder_source.document or not verdict.extracted_value):
                issues.append(f"{bidder.bidder}:{verdict.criterion_id}: missing bidder evidence for decisive verdict")
            if verdict.status == "FAIL" and not verdict.rule_trace:
                issues.append(f"{bidder.bidder}:{verdict.criterion_id}: rejection lacks rule trace")
            if verdict.status == "NEED_MANUAL_REVIEW" and not verdict.manual_review_reason:
                issues.append(f"{bidder.bidder}:{verdict.criterion_id}: review lacks reason")
            if verdict.status in {"FAIL", "NEED_MANUAL_REVIEW"} and not verdict.uncertainty_type:
                issues.append(f"{bidder.bidder}:{verdict.criterion_id}: non-pass verdict lacks issue type")
            if verdict.status in {"FAIL", "NEED_MANUAL_REVIEW"} and not verdict.suggested_action:
                issues.append(f"{bidder.bidder}:{verdict.criterion_id}: non-pass verdict lacks suggested action")
    return issues


def _criteria_from_llm(data: object | None, tender_index) -> list[Criterion]:
    if not isinstance(data, dict) or not isinstance(data.get("criteria"), list):
        return []
    criteria: list[Criterion] = []
    for index, item in enumerate(data["criteria"], start=1):
        if not isinstance(item, dict):
            continue
        description = str(item.get("description", ""))
        citation = _best_tender_citation(tender_index, description)
        criteria.append(
            Criterion(
                id=str(item.get("id") or f"C{index}"),
                category=_category(item.get("category")),
                mandatory=bool(item.get("mandatory", True)),
                description=description,
                tender_citation=citation,
                threshold=str(item.get("threshold", "")),
                time_period=str(item.get("time_period", "")),
                comparison_rule=str(item.get("comparison_rule", "present")),
                accepted_evidence=list(item.get("accepted_evidence", [])),
                criteria_risk_flags=list(item.get("criteria_risk_flags", [])) or _criteria_risk_flags(description, str(item.get("threshold", "")), str(item.get("time_period", ""))),
            )
        )
    return [criterion for criterion in criteria if criterion.description]


def _heuristic_criteria(text: str, tender_index) -> list[Criterion]:
    lower = text.lower()
    criteria: list[Criterion] = []
    threshold = ""
    estimated_cost = _estimated_cost_rupees(text)
    turnover_lines = [line for line in text.splitlines() if "turnover" in line.lower()]
    for line in turnover_lines:
        money = _first_money_value(line)
        if money:
            threshold = money
    if not threshold and "50%" in text and "turnover" in lower and estimated_cost:
        threshold = _format_inr(estimated_cost * 0.5)

    if "turnover" in lower:
        criteria.append(
            Criterion(
                "C1",
                "financial",
                True,
                "Average annual turnover must meet the tender threshold.",
                _best_tender_citation(tender_index, "turnover average annual financial years certificate"),
                threshold,
                "last 3 financial years",
                "minimum",
                ["CA certificate", "audited balance sheet", "turnover certificate"],
                _criteria_risk_flags("Average annual turnover must meet the tender threshold.", threshold, "last 3 financial years"),
            )
        )

    if "gst" in lower:
        criteria.append(Criterion("C2", "compliance", True, "Bidder must have valid GST registration.", _best_tender_citation(tender_index, "GST registration valid"), comparison_rule="valid", accepted_evidence=["GST registration certificate"], criteria_risk_flags=_criteria_risk_flags("Bidder must have valid GST registration.", "", "")))
    if re.search(r"(?:bidder|contractor|tenderer)\s+(?:must|shall|should|required).{0,80}iso|iso\s+9001\s+certificat(?:e|ion)\s+(?:must|shall|should|required)", lower):
        criteria.append(Criterion("C3", "compliance", True, "Bidder must hold valid ISO 9001 certification.", _best_tender_citation(tender_index, "ISO 9001 certification"), comparison_rule="valid", accepted_evidence=["ISO 9001 certificate"], criteria_risk_flags=_criteria_risk_flags("Bidder must hold valid ISO 9001 certification.", "", "")))
    if "similar" in lower or "experience" in lower or "projects" in lower:
        if estimated_cost and ("40%" in text or "forty percent" in lower or "estimated cost put to tender" in lower):
            technical_threshold = "3 works >= 40% estimated cost OR 2 works >= 60% OR 1 work >= 80%"
            technical_threshold = (
                f"3 works >= {_format_inr(estimated_cost * 0.4)} OR "
                f"2 works >= {_format_inr(estimated_cost * 0.6)} OR "
                f"1 work >= {_format_inr(estimated_cost * 0.8)}"
            )
            criteria.append(Criterion("C4", "technical", True, "Bidder must satisfy similar completed work value criteria.", _best_tender_citation(tender_index, "similar works completed estimated cost"), technical_threshold, "last 7 years", "similar_work_value_combo", ["work orders", "completion certificates", "experience letters"], _criteria_risk_flags("Bidder must satisfy similar completed work value criteria.", technical_threshold, "last 7 years")))
        else:
            criteria.append(Criterion("C4", "technical", True, "Bidder must show at least 3 similar completed projects.", _best_tender_citation(tender_index, "similar projects completed"), "3 projects", "last 5 years", "count_at_least", ["work orders", "completion certificates", "experience letters"], _criteria_risk_flags("Bidder must show at least 3 similar completed projects.", "3 projects", "last 5 years")))
    if "industrial license" in lower:
        criteria.append(Criterion("C5", "compliance", True, "Bidder must provide applicable industrial license.", _best_tender_citation(tender_index, "industrial license manufacturing"), comparison_rule="present", accepted_evidence=["industrial license"], criteria_risk_flags=_criteria_risk_flags("Bidder must provide applicable industrial license.", "", "")))
    emd_value = _emd_value(text)
    if "earnest money" in lower or re.search(r"\bemd\b", lower):
        criteria.append(Criterion("C6", "document", True, "Bidder must submit Earnest Money Deposit or valid exemption proof.", _best_tender_citation(tender_index, "Earnest Money Deposit EMD"), emd_value, "", "emd_present", ["EMD receipt", "bank guarantee", "FDR", "exemption proof"], _criteria_risk_flags("Bidder must submit Earnest Money Deposit or valid exemption proof.", emd_value, "")))
    if "price bid" in lower or "quoted" in lower or "percentage rate" in lower:
        criteria.append(Criterion("C7", "commercial", False, "Quoted financial bid amount must be extracted for L1 comparison.", _best_tender_citation(tender_index, "price bid quoted amount percentage rate"), "", "", "price_extracted", ["price bid", "BOQ", "quoted percentage", "tendered amount"], _criteria_risk_flags("Quoted financial bid amount must be extracted for L1 comparison.", "", "")))
    if not criteria:
        criteria.append(
            Criterion(
                "C0",
                "document",
                True,
                "Eligibility criteria could not be extracted confidently from the uploaded tender.",
                _best_tender_citation(tender_index, "eligibility criteria qualification terms conditions"),
                comparison_rule="review_only",
                accepted_evidence=["manual procurement officer review"],
                criteria_risk_flags=["AMBIGUOUS_TENDER_LANGUAGE"],
            )
        )
    return criteria


def _heuristic_evidence(bidder: str, criteria: list[Criterion], bidder_index, docs: list[Document]) -> list[Evidence]:
    evidence: list[Evidence] = []
    for criterion in criteria:
        hits = bidder_index.retrieve(_evidence_query(criterion), top_k=4)
        evidence.append(_full_document_evidence(bidder, criterion, docs, hits))
    return evidence


def _evidence_from_hits(bidder: str, criterion: Criterion, hits) -> Evidence:
    audit_event = validate_retrieval(hits, f"{bidder}:{criterion.id}")
    if not audit_event.detail["passed"]:
        empty = Citation("", 0, "Missing evidence", "No source chunk retrieved.")
        return Evidence(
            criterion.id,
            bidder,
            "",
            "",
            empty,
            criterion.tender_citation,
            0.0,
            notes="Retrieval confidence below threshold.",
            uncertainty_type="MISSING_REQUIRED_DOCUMENT" if criterion.mandatory else "VALUE_NOT_FOUND",
        )

    hit = hits[0]
    citation = citation_from_hit(hit, criterion.description)
    text = citation.excerpt
    value = _value_for_criterion(criterion, text)
    confidence = min(1.0, max(hit.score, 0.0) + 0.35)
    if not value:
        confidence = min(confidence, 0.45)
    return Evidence(
        criterion_id=criterion.id,
        bidder=bidder,
        document=citation.document,
        value=value,
        bidder_citation=citation,
        tender_citation=criterion.tender_citation,
        confidence=confidence,
        normalized_value=value,
        notes="" if value else "Evidence retrieved but value could not be extracted.",
        uncertainty_type="" if value else "VALUE_NOT_FOUND",
        candidate_snippets=[citation_from_hit(item, criterion.description) for item in hits[:3]],
    )


def _full_document_evidence(bidder: str, criterion: Criterion, docs: list[Document], hits) -> Evidence:
    full_text = "\n\n".join(f"[document {doc.name}]\n{doc.text}" for doc in docs)
    value = ""
    notes = ""
    citation = None

    if criterion.category == "financial":
        value, citation = _turnover_evidence(full_text, docs)
    elif "GST" in criterion.description:
        value, citation = _regex_evidence(full_text, docs, r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]\b", "GSTIN")
        pan, _ = _regex_evidence(full_text, docs, r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", "PAN")
        if value and pan:
            notes = f"PAN also found: {pan}"
    elif criterion.comparison_rule == "similar_work_value_combo":
        value, citation = _similar_work_evidence(full_text, docs)
    elif criterion.comparison_rule == "count_at_least":
        value, citation = _project_count_evidence(full_text, docs)
    elif criterion.comparison_rule == "emd_present":
        value, citation = _emd_evidence(full_text, docs)
    elif criterion.comparison_rule == "price_extracted":
        value, citation = _price_evidence(full_text, docs)
    elif "iso" in criterion.description.lower():
        value, citation = _text_marker_evidence(full_text, docs, "ISO 9001", "ISO 9001")
    elif "industrial license" in criterion.description.lower():
        value, citation = _text_marker_evidence(full_text, docs, "industrial license", "Industrial license present")

    if value and citation:
        uncertainty = "AMBIGUOUS_VALUE" if "ambiguous" in value.lower() else ""
        confidence = 0.55 if uncertainty else 0.9
        return Evidence(criterion.id, bidder, citation.document, value, citation, criterion.tender_citation, confidence, value, notes, uncertainty)
    return _evidence_from_hits(bidder, criterion, hits)


def _evidence_from_llm(bidder: str, criteria: list[Criterion], data: object | None) -> list[Evidence]:
    if not isinstance(data, dict) or not isinstance(data.get("evidence"), list):
        return []
    criteria_by_id = {criterion.id: criterion for criterion in criteria}
    evidence: list[Evidence] = []
    for item in data["evidence"]:
        if not isinstance(item, dict):
            continue
        criterion = criteria_by_id.get(str(item.get("criterion_id", "")))
        if not criterion:
            continue
        document = str(item.get("document", ""))
        excerpt = str(item.get("excerpt", ""))
        citation = Citation(document, int(item.get("page", 1) or 1), criterion.description, excerpt)
        evidence.append(
            Evidence(
                criterion.id,
                bidder,
                document,
                str(item.get("value", "")),
                citation,
                criterion.tender_citation,
                float(item.get("confidence", 0) or 0),
                str(item.get("normalized_value", "")),
                str(item.get("notes", "")),
                str(item.get("uncertainty_type", "")),
            )
        )
    return evidence


def _evaluate_criterion(criterion: Criterion, evidence_items: list[Evidence], l1_price: float | None = None, bidder: str = "") -> Verdict:
    if criterion.comparison_rule == "review_only":
        source = evidence_items[0].bidder_citation if evidence_items else Citation("", 0, "Manual review", "")
        value = evidence_items[0].value if evidence_items else ""
        confidence = evidence_items[0].confidence if evidence_items else 0.0
        return Verdict(
            criterion.id,
            criterion.description,
            "NEED_MANUAL_REVIEW",
            "Tender criteria require manual review before bidder eligibility can be decided.",
            criterion.tender_citation,
            source,
            value,
            confidence,
            "review_only",
            "Criteria extraction was not confident enough for automated evaluation.",
            "",
            "AMBIGUOUS_TENDER_LANGUAGE",
            ACTION_AMBIGUOUS,
        )

    usable = [item for item in evidence_items if item.value.strip()]
    if not usable:
        source = evidence_items[0].bidder_citation if evidence_items else Citation("", 0, "Missing evidence", "")
        return Verdict(
            criterion.id,
            criterion.description,
            "NEED_MANUAL_REVIEW",
            "No usable bidder evidence was found for this mandatory criterion." if criterion.mandatory else "No usable bidder evidence was found for this criterion.",
            criterion.tender_citation,
            source,
            "",
            0.0,
            "missing_evidence",
            "Required document or value missing, or retrieval confidence below threshold.",
            "",
            evidence_items[0].uncertainty_type if evidence_items and evidence_items[0].uncertainty_type else ("MISSING_REQUIRED_DOCUMENT" if criterion.mandatory else "VALUE_NOT_FOUND"),
            ACTION_MISSING,
        )

    best = max(usable, key=lambda item: item.confidence)
    if best.confidence < MIN_CONFIDENCE:
        return Verdict(criterion.id, criterion.description, "NEED_MANUAL_REVIEW", "Evidence was found but confidence is below threshold.", criterion.tender_citation, best.bidder_citation, best.value, best.confidence, "confidence_check", "Low OCR, parsing, or retrieval confidence.", "", "LOW_OCR_CONFIDENCE", ACTION_LOW_CONFIDENCE)

    if criterion.criteria_risk_flags and best.uncertainty_type:
        return Verdict(criterion.id, criterion.description, "NEED_MANUAL_REVIEW", "Tender criterion has risk flags and extracted evidence is uncertain.", criterion.tender_citation, best.bidder_citation, best.value, best.confidence, f"criteria_risk_flags={','.join(criterion.criteria_risk_flags)}; evidence_uncertainty={best.uncertainty_type}", "Ambiguous tender language or uncertain evidence requires officer interpretation.", "", "AMBIGUOUS_TENDER_LANGUAGE", ACTION_AMBIGUOUS)

    if criterion.comparison_rule == "minimum":
        found = _money_to_crore(best.value)
        required = _money_to_crore(criterion.threshold)
        trace = f"found={best.value}; required={criterion.threshold}; comparison=found >= required; source={best.document}"
        if found is None or required is None:
            return Verdict(criterion.id, criterion.description, "NEED_MANUAL_REVIEW", "Financial value could not be normalized.", criterion.tender_citation, best.bidder_citation, best.value, best.confidence, trace, "Ambiguous financial value.", "", "AMBIGUOUS_VALUE", ACTION_AMBIGUOUS)
        if found >= required:
            return Verdict(criterion.id, criterion.description, "PASS", f"Found {best.value}, meeting required {criterion.threshold}.", criterion.tender_citation, best.bidder_citation, best.value, best.confidence, trace)
        return Verdict(criterion.id, criterion.description, "FAIL", f"Found {best.value}, below required {criterion.threshold}.", criterion.tender_citation, best.bidder_citation, best.value, best.confidence, trace, "", "", "RULE_FAILURE", "Record the source-backed threshold failure in the rejection note after officer sign-off.")

    if criterion.comparison_rule == "similar_work_value_combo":
        values = _all_money_to_rupees(best.value)
        trace = f"found={best.value}; required={criterion.threshold}; comparison=3x40% OR 2x60% OR 1x80%; source={best.document}"
        required_values = _all_money_to_rupees(criterion.threshold)
        if len(required_values) < 3 or not values:
            return Verdict(criterion.id, criterion.description, "NEED_MANUAL_REVIEW", "Similar-work values could not be normalized.", criterion.tender_citation, best.bidder_citation, best.value, best.confidence, trace, "Ambiguous project value evidence.", "", "AMBIGUOUS_VALUE", ACTION_AMBIGUOUS)
        r40, r60, r80 = required_values[0], required_values[1], required_values[2]
        pass_combo = sum(1 for value in values if value >= r40) >= 3 or sum(1 for value in values if value >= r60) >= 2 or any(value >= r80 for value in values)
        if pass_combo:
            return Verdict(criterion.id, criterion.description, "PASS", "Similar completed work values satisfy the tender combination rule.", criterion.tender_citation, best.bidder_citation, best.value, best.confidence, trace)
        return Verdict(criterion.id, criterion.description, "FAIL", "Similar completed work values do not satisfy 3x40%, 2x60%, or 1x80% of estimated cost.", criterion.tender_citation, best.bidder_citation, best.value, best.confidence, trace, "", "", "RULE_FAILURE", "Record the cited similar-work shortfall in the technical evaluation note after officer sign-off.")

    if criterion.comparison_rule == "emd_present":
        trace = f"found={best.value}; required={criterion.threshold or 'EMD/exemption proof'}; source={best.document}"
        lower_value = best.value.lower()
        if any(term in lower_value for term in ["missing", "not enclosed", "pending", "not attached"]):
            return Verdict(criterion.id, criterion.description, "FAIL", "EMD evidence indicates proof is missing or pending.", criterion.tender_citation, best.bidder_citation, best.value, best.confidence, trace, "", "", "MISSING_REQUIRED_DOCUMENT", "Verify the EMD/exemption proof manually before recording the non-responsive reason.")
        return Verdict(criterion.id, criterion.description, "PASS", "EMD or tender fee evidence is present with acceptable confidence.", criterion.tender_citation, best.bidder_citation, best.value, best.confidence, trace)

    if criterion.comparison_rule == "price_extracted":
        price = _money_to_rupees(best.value)
        trace = f"found={best.value}; l1={_format_inr(l1_price) if l1_price else 'unknown'}; source={best.document}"
        if price is None:
            return Verdict(criterion.id, criterion.description, "NEED_MANUAL_REVIEW", "Quoted price could not be normalized.", criterion.tender_citation, best.bidder_citation, best.value, best.confidence, trace, "Ambiguous price bid evidence.", "", "AMBIGUOUS_VALUE", ACTION_AMBIGUOUS)
        if l1_price is not None and abs(price - l1_price) < 1:
            return Verdict(criterion.id, criterion.description, "PASS", f"Quoted price extracted and currently L1 at {_format_inr(price)}.", criterion.tender_citation, best.bidder_citation, best.value, best.confidence, trace)
        return Verdict(criterion.id, criterion.description, "PASS", f"Quoted price extracted for comparison; L1 is {_format_inr(l1_price) if l1_price else 'not determined'}.", criterion.tender_citation, best.bidder_citation, best.value, best.confidence, trace)

    if criterion.comparison_rule == "count_at_least":
        found_count = _first_number(best.value)
        required_count = _first_number(criterion.threshold) or 1
        trace = f"found={best.value}; required={criterion.threshold}; comparison=found_count >= required_count; source={best.document}"
        if found_count is None:
            return Verdict(criterion.id, criterion.description, "NEED_MANUAL_REVIEW", "Project count could not be verified.", criterion.tender_citation, best.bidder_citation, best.value, best.confidence, trace, "Ambiguous project experience evidence.", "", "AMBIGUOUS_VALUE", ACTION_AMBIGUOUS)
        if found_count >= required_count:
            return Verdict(criterion.id, criterion.description, "PASS", f"Found {found_count} matching projects, meeting required {required_count}.", criterion.tender_citation, best.bidder_citation, best.value, best.confidence, trace)
        return Verdict(criterion.id, criterion.description, "FAIL", f"Found {found_count} matching projects, below required {required_count}.", criterion.tender_citation, best.bidder_citation, best.value, best.confidence, trace, "", "", "RULE_FAILURE", "Record the cited experience shortfall in the technical evaluation note after officer sign-off.")

    trace = f"found={best.value}; required=present/valid; source={best.document}"
    if any(word in best.value.lower() for word in ["expired", "invalid", "not available"]):
        return Verdict(criterion.id, criterion.description, "FAIL", "Evidence indicates the required document or registration is invalid.", criterion.tender_citation, best.bidder_citation, best.value, best.confidence, trace, "", "", "RULE_FAILURE", "Verify the cited invalid/expired document before recording the rejection reason.")
    return Verdict(criterion.id, criterion.description, "PASS", "Required evidence is present with acceptable confidence.", criterion.tender_citation, best.bidder_citation, best.value, best.confidence, trace)


def _overall_status(criteria: list[Criterion], verdicts: list[Verdict]) -> str:
    mandatory_ids = {criterion.id for criterion in criteria if criterion.mandatory}
    mandatory_verdicts = [verdict for verdict in verdicts if verdict.criterion_id in mandatory_ids]
    if any(verdict.status == "NEED_MANUAL_REVIEW" for verdict in mandatory_verdicts):
        return "Need Manual Review"
    if any(verdict.status == "FAIL" for verdict in mandatory_verdicts):
        return "Not Eligible"
    return "Eligible"


def _best_tender_citation(tender_index, query: str) -> Citation:
    hits = tender_index.retrieve(query, top_k=1)
    if hits:
        return citation_from_hit(hits[0], "Tender criterion source")
    return Citation("tender", 1, "Tender criterion source", "Tender source could not be retrieved.")


def _value_for_criterion(criterion: Criterion, text: str) -> str:
    description = criterion.description.lower()
    if criterion.category == "financial":
        return _first_money_value(text)
    if "gst" in description:
        return _first_match(text, r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]\b") or ("GST registration mentioned" if "gst" in text.lower() else "")
    if "iso" in description:
        return "ISO 9001" if "iso" in text.lower() and "9001" in text.lower() else ""
    if criterion.category == "technical":
        count = _project_count(text)
        return f"{count} similar projects" if count else ""
    if "industrial license" in description:
        return "Industrial license present" if "industrial license" in text.lower() else ""
    return "Evidence present" if text else ""


def _evidence_query(criterion: Criterion) -> str:
    return " ".join([criterion.description, criterion.threshold, " ".join(criterion.accepted_evidence)])


def _find_conflicts(evidence_items: list[Evidence]) -> list[tuple[str, str, Citation]]:
    conflicts: list[tuple[str, str, Citation]] = []
    grouped: dict[str, list[Evidence]] = defaultdict(list)
    for item in evidence_items:
        if item.value:
            grouped[item.criterion_id].append(item)
    for criterion_id, items in grouped.items():
        money_values = {_money_to_crore(item.value) for item in items if _money_to_crore(item.value) is not None}
        if len(money_values) > 1:
            conflicts.append((criterion_id, "Conflicting financial values found across bidder documents.", items[0].bidder_citation))
    return conflicts


def _l1_prices(criteria: list[Criterion], evidence_by_bidder: dict[str, list[Evidence]]) -> dict[str, float]:
    price_criteria = {criterion.id for criterion in criteria if criterion.comparison_rule == "price_extracted"}
    l1: dict[str, float] = {}
    for criterion_id in price_criteria:
        prices = [
            price
            for evidence_items in evidence_by_bidder.values()
            for item in evidence_items
            if item.criterion_id == criterion_id
            for price in [_money_to_rupees(item.value)]
            if price is not None
        ]
        if prices:
            l1[criterion_id] = min(prices)
    return l1


def _force_review(verdict: Verdict, reason: str) -> Verdict:
    return Verdict(verdict.criterion_id, verdict.criterion, "NEED_MANUAL_REVIEW", reason, verdict.tender_source, verdict.bidder_source, verdict.extracted_value, verdict.confidence, verdict.rule_trace, reason, verdict.human_reviewer_action, "CONFLICTING_EVIDENCE", ACTION_CONFLICT)


def _review_task(
    bidder: str,
    criterion_id: str,
    reason: str,
    source: Citation,
    issue_type: str = "VALUE_NOT_FOUND",
    extracted_value: str = "",
    confidence: float = 0.0,
    suggested_action: str = ACTION_MISSING,
) -> ReviewTask:
    return ReviewTask(f"REV-{bidder}-{criterion_id}".replace(" ", "-"), bidder, criterion_id, reason, "high", source, issue_type, extracted_value, confidence, suggested_action)


def _dedupe_review_tasks(tasks: list[ReviewTask]) -> list[ReviewTask]:
    deduped: list[ReviewTask] = []
    seen: set[tuple[str, str, str]] = set()
    for task in tasks:
        normalized_reason = task.reason
        if normalized_reason == "Low OCR, parsing, or retrieval confidence.":
            normalized_reason = "Low evidence confidence or OCR uncertainty."
        key = (task.bidder, task.criterion_id, normalized_reason, task.issue_type)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(task)
    return deduped


def _category(value: object) -> str:
    text = str(value)
    return text if text in {"financial", "technical", "compliance", "document", "commercial"} else "document"


def _criteria_risk_flags(description: str, threshold: str, time_period: str) -> list[str]:
    text = f"{description} {threshold} {time_period}".lower()
    flags: list[str] = []
    if any(term in text for term in ["satisfactory", "adequate", "as deemed fit", "reputed", "similar nature"]):
        flags.append("subjective_requirement")
    if any(term in text for term in ["similar", "experience", "project"]) and "similar works" not in text and "construction" not in text:
        flags.append("unverifiable_claim")
    if not threshold and any(term in text for term in ["minimum", "at least", "turnover", "emd", "price"]):
        flags.append("vague_threshold")
    if not time_period and any(term in text for term in ["valid", "turnover", "experience", "completed"]):
        flags.append("missing_time_period")
    if "corrigendum" in text or "amended" in text:
        flags.append("corrigendum_sensitive")
    return sorted(set(flags))


def _first_money_value(text: str) -> str:
    match = re.search(r"(?:INR|Rs\.?|Rupees)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(crore|cr|lakh)?(?:/-)?|([0-9][0-9,]*(?:\.[0-9]+)?)\s*(crore|cr|lakh)", text, re.IGNORECASE)
    if not match:
        if "turnover" in text.lower() and re.search(r"(?:INR|Rs\.?|Rupees).*[?]", text, re.IGNORECASE):
            return "Ambiguous turnover value"
        return ""
    amount = match.group(1) or match.group(3)
    unit = match.group(2) or match.group(4) or ""
    unit_text = f" {unit}" if unit else ""
    return f"INR {amount}{unit_text}"


def _money_to_crore(value: str) -> float | None:
    rupees = _money_to_rupees(value)
    return rupees / 10_000_000 if rupees is not None else None


def _money_to_rupees(value: str) -> float | None:
    match = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(crore|cr|lakh)?", value, re.IGNORECASE)
    if not match:
        return None
    amount = float(match.group(1).replace(",", ""))
    unit = (match.group(2) or "").lower()
    if unit in {"crore", "cr"}:
        return amount * 10_000_000
    if unit == "lakh":
        return amount * 100_000
    return amount


def _all_money_to_rupees(value: str) -> list[float]:
    return [
        money
        for raw in re.findall(r"INR\s+[0-9][0-9,]*(?:\.[0-9]+)?(?:\s*(?:crore|cr|lakh))?|Rs\.?\s*[0-9][0-9,]*(?:\.[0-9]+)?(?:\s*(?:crore|cr|lakh))?(?:/-)?", value, re.IGNORECASE)
        for money in [_money_to_rupees(raw)]
        if money is not None
    ]


def _estimated_cost_rupees(text: str) -> float | None:
    candidates: list[float] = []
    for match in re.finditer(r"Estimated\s+Cost|Tentative\s+Estimated\s+Cost", text, re.IGNORECASE):
        window = text[match.start(): match.start() + 450]
        for money in re.findall(r"(?:Rs\.?|INR)\s*[0-9][0-9,]*(?:\.[0-9]+)?\s*(?:crore|cr|lakh)?(?:/-)?", window, re.IGNORECASE):
            value = _money_to_rupees(money)
            if value:
                candidates.append(value)
    return max(candidates) if candidates else None


def _emd_value(text: str) -> str:
    match = re.search(r"(?:Earnest Money Deposit|EMD).{0,120}?(?:Rs\.?|INR)\s*([0-9][0-9,]*(?:\.[0-9]+)?)(?:/-)?", text, re.IGNORECASE | re.DOTALL)
    return f"INR {match.group(1)}" if match else ""


def _format_inr(value: float | None) -> str:
    if value is None:
        return ""
    return f"INR {value:,.0f}"


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


def _turnover_evidence(full_text: str, docs: list[Document]) -> tuple[str, Citation | None]:
    match = re.search(r"Average annual turnover.{0,120}?(?:is|:)\s*(?:Rs\.?|INR)\s*[0-9][0-9,]*(?:\.[0-9]+)?\s*(?:crore|cr|lakh)?(?:/-)?", full_text, re.IGNORECASE | re.DOTALL)
    if not match:
        match = re.search(r"Turnover.{0,600}?Average annual turnover.{0,160}", full_text, re.IGNORECASE | re.DOTALL)
    if not match:
        return "", None
    excerpt = _window(full_text, match.start(), 700)
    if "?" in excerpt:
        value = "Ambiguous turnover value"
    else:
        value = _first_money_value(match.group(0)) or _first_money_value(excerpt)
    udin = _first_match(full_text, r"\b\d{8}[A-Z]{2}[A-Z0-9]{5,}\b")
    if udin:
        value = f"{value}; UDIN {udin}" if value else f"UDIN {udin}"
    return value, _citation_for_offset(full_text, docs, match.start(), "Turnover evidence")


def _regex_evidence(full_text: str, docs: list[Document], pattern: str, section: str) -> tuple[str, Citation | None]:
    match = re.search(pattern, full_text)
    if not match:
        return "", None
    return match.group(0), _citation_for_offset(full_text, docs, match.start(), section)


def _similar_work_evidence(full_text: str, docs: list[Document]) -> tuple[str, Citation | None]:
    start = full_text.lower().find("similar works executed for pq criteria")
    if start < 0:
        start = full_text.lower().find("list of works executed")
    if start < 0:
        return "", None
    end_candidates = [index for token in ["works under execution", "manpower available", "[page 7]"] for index in [full_text.lower().find(token, start + 50)] if index > start]
    end = min(end_candidates) if end_candidates else start + 1800
    segment = full_text[start:end]
    values = []
    seen = set()
    for raw in re.findall(r"Rs\.?\s*[0-9][0-9,]*(?:\.[0-9]+)?(?:/-)?", segment, re.IGNORECASE):
        amount = re.search(r"[0-9][0-9,]*(?:\.[0-9]+)?", raw).group(0)
        if amount not in seen:
            seen.add(amount)
            values.append(raw)
    if not values:
        return "", None
    formatted = []
    for item in values:
        amount = re.search(r"[0-9][0-9,]*(?:\.[0-9]+)?", item).group(0)
        formatted.append(f"INR {amount}")
    return f"{len(values)} similar work value(s): " + ", ".join(formatted), _citation_for_offset(full_text, docs, start, "Similar work evidence")


def _project_count_evidence(full_text: str, docs: list[Document]) -> tuple[str, Citation | None]:
    match = re.search(r"completed\s+([0-9]+)\s+similar projects?", full_text, re.IGNORECASE)
    if not match:
        match = re.search(r"([0-9]+)\s+similar\s+(?:completed\s+)?projects?", full_text, re.IGNORECASE)
    if match:
        return f"{match.group(1)} similar projects", _citation_for_offset(full_text, docs, match.start(), "Similar project count evidence")
    project_refs = re.findall(r"\bProject\s+[A-Z0-9-]+", full_text, re.IGNORECASE)
    if project_refs:
        first = re.search(r"\bProject\s+[A-Z0-9-]+", full_text, re.IGNORECASE)
        return f"{len(set(project_refs))} similar projects", _citation_for_offset(full_text, docs, first.start(), "Similar project count evidence")
    return "", None


def _emd_evidence(full_text: str, docs: list[Document]) -> tuple[str, Citation | None]:
    missing = re.search(r"(?:Earnest Money Deposit|EMD).{0,220}?(?:missing|not enclosed|pending|not attached).{0,120}", full_text, re.IGNORECASE | re.DOTALL)
    if missing:
        excerpt = missing.group(0)
        value = _emd_value(excerpt) or _first_money_value(excerpt) or "EMD proof missing/pending"
        if "missing" not in value.lower() and "pending" not in value.lower():
            value = f"{value}; proof missing/pending"
        return value, _citation_for_offset(full_text, docs, missing.start(), "EMD evidence")

    amount_match = None
    for candidate in re.finditer(r"(?:Earnest Money Deposit|EMD).{0,260}", full_text, re.IGNORECASE | re.DOTALL):
        if _emd_value(candidate.group(0)) or _first_money_value(candidate.group(0)):
            amount_match = candidate
            break

    match = amount_match or re.search(r"(?:Earnest Money Deposit|EMD).{0,220}", full_text, re.IGNORECASE | re.DOTALL)
    if not match:
        return "", None
    excerpt = match.group(0)
    value = _emd_value(excerpt) or _first_money_value(excerpt) or "EMD mentioned"
    if re.search(r"missing|not enclosed|pending|not attached", excerpt, re.IGNORECASE):
        value = f"{value}; proof missing/pending"
    return value, _citation_for_offset(full_text, docs, match.start(), "EMD evidence")


def _price_evidence(full_text: str, docs: list[Document]) -> tuple[str, Citation | None]:
    match = re.search(r"Indicative Tendered Amount\s*(?:Rs\.?|INR)\s*[0-9][0-9,]*(?:\.[0-9]+)?(?:/-)?", full_text, re.IGNORECASE)
    if not match:
        match = re.search(r"Quoted Percentage.{0,120}?(?:Rs\.?|INR)\s*[0-9][0-9,]*(?:\.[0-9]+)?(?:/-)?", full_text, re.IGNORECASE | re.DOTALL)
    if not match:
        return "", None
    return _first_money_value(match.group(0)), _citation_for_offset(full_text, docs, match.start(), "Price bid evidence")


def _text_marker_evidence(full_text: str, docs: list[Document], marker: str, value: str) -> tuple[str, Citation | None]:
    index = full_text.lower().find(marker.lower())
    if index < 0:
        return "", None
    return value, _citation_for_offset(full_text, docs, index, marker)


def _citation_for_offset(full_text: str, docs: list[Document], offset: int, section: str) -> Citation:
    cursor = 0
    for doc in docs:
        header = f"[document {doc.name}]\n"
        start = cursor + len(header)
        end = start + len(doc.text)
        if start <= offset <= end:
            local_offset = max(0, offset - start)
            excerpt = _window(doc.text, local_offset, 650)
            page = _page_near(doc.text, local_offset)
            return Citation(doc.name, page, section, excerpt)
        cursor = end + 2
    doc = docs[0]
    return Citation(doc.name, 1, section, _window(doc.text, 0, 650))


def _page_near(text: str, offset: int) -> int:
    page = 1
    for match in re.finditer(r"\[page\s+(\d+)\]", text[:offset], re.IGNORECASE):
        page = int(match.group(1))
    return page


def _window(text: str, offset: int, width: int) -> str:
    start = max(0, offset - width // 4)
    end = min(len(text), offset + width)
    return text[start:end].replace("\n", " ").strip()
