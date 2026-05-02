from __future__ import annotations

import json
from pathlib import Path

from schema import AuditEvent, Citation, EvaluationResult, to_dict


def write_reports(outputs_dir: Path, result: EvaluationResult, audit_events: list[AuditEvent]) -> None:
    outputs_dir.mkdir(parents=True, exist_ok=True)
    (outputs_dir / "evaluation_report.json").write_text(json.dumps(to_dict(result), indent=2), encoding="utf-8")
    (outputs_dir / "evaluation_report.md").write_text(_markdown_report(result), encoding="utf-8")
    (outputs_dir / "agent_outputs.json").write_text(json.dumps(agent_outputs_payload(result, audit_events), indent=2), encoding="utf-8")
    _write_agent_files(outputs_dir, result, audit_events)
    with (outputs_dir / "audit_log.jsonl").open("w", encoding="utf-8") as handle:
        for event in audit_events:
            handle.write(json.dumps(to_dict(event)) + "\n")


def _markdown_report(result: EvaluationResult) -> str:
    lines = [
        "# Tender Eligibility Evaluation Report",
        "",
        f"Tender workspace: `{result.tender_id}`",
        f"Final accuracy gate: **{'PASSED' if result.final_accuracy_gate_passed else 'FAILED'}**",
        "",
    ]
    if result.final_accuracy_issues:
        lines.extend(["## Final Accuracy Issues", ""])
        lines.extend(f"- {_clean(issue)}" for issue in result.final_accuracy_issues)
        lines.append("")

    lines.extend(
        [
            "## Agent Workflow",
            "",
            "| Stage | Agent | Responsibility | Output |",
            "| --- | --- | --- | --- |",
        ]
    )
    for agent in result.agents:
        lines.append(f"| {agent.stage} | {_clean(agent.name)} | {_clean(agent.responsibility)} | {_clean(', '.join(agent.outputs))} |")

    lines.extend(
        [
            "",
            "## Criteria",
            "",
            "| ID | Category | Mandatory | Description | Threshold | Tender Source |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for criterion in result.criteria:
        lines.append(
            "| {id} | {category} | {mandatory} | {description} | {threshold} | {source} |".format(
                id=criterion.id,
                category=criterion.category,
                mandatory="Yes" if criterion.mandatory else "No",
                description=_clean(criterion.description),
                threshold=_clean(criterion.threshold),
                source=_citation(criterion.tender_citation),
            )
        )

    lines.extend(["", "## Award / Selection Reasoning", ""])
    selected = _selection_reasons(result)
    for item in selected:
        lines.append(f"- **{_clean(item['bidder'])}**: {_clean(item['decision'])}. {_clean(item['reason'])}")
        if item.get("source"):
            lines.append(f"  Source: {_clean(item['source'])}")

    lines.extend(["", "## Bidder Results", ""])
    for bidder in result.bidders:
        lines.extend(
            [
                f"### {bidder.bidder}",
                "",
                f"Overall status: **{bidder.overall_status}**",
                "",
                "| Criterion | Status | Extracted Value | Reason | Tender Source | Bidder Source | Rule Trace | Manual Review |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for verdict in bidder.verdicts:
            lines.append(
                "| {criterion} | {status} | {value} | {reason} | {tender} | {bidder_source} | {trace} | {review} |".format(
                    criterion=verdict.criterion_id,
                    status=verdict.status,
                    value=_clean(verdict.extracted_value),
                    reason=_clean(verdict.reason),
                    tender=_citation(verdict.tender_source),
                    bidder_source=_citation(verdict.bidder_source),
                    trace=_clean(verdict.rule_trace),
                    review=_clean(verdict.manual_review_reason),
                )
            )
        if bidder.review_tasks:
            lines.extend(["", "Review tasks:"])
            for task in bidder.review_tasks:
                lines.append(f"- `{task.task_id}`: {_clean(task.reason)} Source: {_citation(task.source)}")
        lines.append("")

    return "\n".join(lines)


def agent_outputs_payload(result: EvaluationResult, audit_events: list[AuditEvent]) -> dict[str, object]:
    return {
        "workspace": result.tender_id,
        "final_accuracy_gate": {
            "passed": result.final_accuracy_gate_passed,
            "issues": result.final_accuracy_issues,
        },
        "pre_tender": {
            "structured_requirements": "Derived from uploaded tender text and criteria extraction.",
            "tender_package": {
                "criteria_count": len(result.criteria),
                "mandatory_criteria": sum(1 for criterion in result.criteria if criterion.mandatory),
                "categories": sorted({criterion.category for criterion in result.criteria}),
            },
            "publication_pack": {
                "status": "ready_for_officer_review" if result.criteria and result.criteria[0].id != "C0" else "manual_review_required",
                "source_documents": sorted({criterion.tender_citation.document for criterion in result.criteria if criterion.tender_citation.document}),
            },
        },
        "tender_stage": {
            "criteria": [to_dict(criterion) for criterion in result.criteria],
            "bidder_count": len(result.bidders),
            "evaluation_matrix": [to_dict(bidder) for bidder in result.bidders],
            "review_tasks": [to_dict(task) for bidder in result.bidders for task in bidder.review_tasks],
            "selection_reasons": _selection_reasons(result),
        },
        "post_tender": {
            "award_pack": _award_pack(result),
            "contract_draft": "Not generated in local prototype; award recommendation is produced for officer approval.",
            "audit_export": {
                "audit_event_count": len(audit_events),
                "stored_files": ["evaluation_report.md", "evaluation_report.json", "agent_outputs.json", "audit_log.jsonl"],
            },
        },
        "agent_events": [to_dict(event) for event in audit_events],
    }


def _write_agent_files(outputs_dir: Path, result: EvaluationResult, audit_events: list[AuditEvent]) -> None:
    folder = outputs_dir / "agent_outputs"
    folder.mkdir(parents=True, exist_ok=True)
    manifest = []
    for agent in result.agents:
        filename = f"{agent.stage}__{_slug(agent.name)}.json"
        payload = _agent_file_payload(agent.name, result, audit_events)
        (folder / filename).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        manifest.append(
            {
                "stage": agent.stage,
                "agent": agent.name,
                "file": f"agent_outputs/{filename}",
                "outputs": agent.outputs,
            }
        )
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _agent_file_payload(agent_name: str, result: EvaluationResult, audit_events: list[AuditEvent]) -> dict[str, object]:
    by_name = {
        "Requirement Structuring Agent": {
            "structured_requirements": "Extracted from uploaded tender package.",
            "fields": _requirement_fields(result),
        },
        "Tender Drafting Agent": {
            "tender_package": {
                "criteria": [to_dict(criterion) for criterion in result.criteria],
                "required_documents": sorted({evidence for criterion in result.criteria for evidence in criterion.accepted_evidence}),
            }
        },
        "Compliance Policy Agent": {
            "compliance_findings": _criteria_by_category(result, {"compliance", "document"}),
        },
        "Risk Review Agent": {
            "risk_findings": result.final_accuracy_issues or _manual_review_summary(result),
        },
        "Publication Agent": {
            "publication_pack": {
                "status": "ready_for_officer_review" if result.final_accuracy_gate_passed else "blocked_by_accuracy_gate",
                "criteria_count": len(result.criteria),
                "source_documents": sorted({criterion.tender_citation.document for criterion in result.criteria if criterion.tender_citation.document}),
            }
        },
        "Vendor Registration Agent": {
            "vendor_status": [{"vendor": bidder.bidder, "status": bidder.overall_status} for bidder in result.bidders],
        },
        "Submission Intake Agent": {
            "submission_record": _submission_sources(result),
        },
        "Document Understanding Agent": {
            "parsed_documents": _document_sources(result),
            "parser_events": _events_containing(audit_events, ["document", "ingestion", "parser", "ocr"]),
        },
        "RAG Retrieval Agent": {
            "retrieval_hits": _events_containing(audit_events, ["retrieval", "rag", "chunking"]),
        },
        "Criteria Extraction Agent": {
            "criteria": [to_dict(criterion) for criterion in result.criteria],
            "events": _events_containing(audit_events, ["criteria_extraction"]),
        },
        "Evidence Mapping Agent": {
            "evidence": _evidence_from_verdicts(result),
            "events": _events_containing(audit_events, ["evidence_mapping", "grounded_extraction"]),
        },
        "Responsiveness Agent": {
            "responsiveness_verdicts": _verdicts_by_category(result, {"document", "compliance"}),
        },
        "Technical Evaluation Agent": {
            "technical_verdicts": _verdicts_by_category(result, {"technical"}),
        },
        "Financial Evaluation Agent": {
            "financial_verdicts": _verdicts_by_category(result, {"financial", "commercial"}),
            "selection_reasons": _selection_reasons(result),
        },
        "Human Review Agent": {
            "review_tasks": [to_dict(task) for bidder in result.bidders for task in bidder.review_tasks],
        },
        "Consolidated Report Agent": {
            "reports": ["evaluation_report.md", "evaluation_report.json", "agent_outputs.json", "audit_log.jsonl"],
            "final_accuracy_gate": {"passed": result.final_accuracy_gate_passed, "issues": result.final_accuracy_issues},
        },
        "Award Recommendation Agent": {
            "award_pack": _award_pack(result),
        },
        "Contract Generation Agent": {
            "contract_draft": "Not generated in local prototype; award recommendation is ready for officer approval.",
        },
        "Contract Compliance Agent": {
            "contract_status": "Not started. Contract tracking begins after human award approval.",
        },
        "Vendor Performance Agent": {
            "vendor_scorecard": "Not started. Vendor scorecards are updated during contract execution.",
        },
        "Audit & RTI Support Agent": {
            "audit_export": {
                "audit_event_count": len(audit_events),
                "events": [to_dict(event) for event in audit_events],
            },
        },
    }
    agent = next((item for item in result.agents if item.name == agent_name), None)
    return {
        "workspace": result.tender_id,
        "stage": agent.stage if agent else "",
        "agent": agent_name,
        "responsibility": agent.responsibility if agent else "",
        "inputs": agent.inputs if agent else [],
        "outputs": by_name.get(agent_name, {}),
    }


def _requirement_fields(result: EvaluationResult) -> dict[str, object]:
    return {
        "technical_specs": [to_dict(criterion) for criterion in result.criteria if criterion.category == "technical"],
        "eligibility_criteria": [to_dict(criterion) for criterion in result.criteria if criterion.mandatory],
        "financial_terms": [to_dict(criterion) for criterion in result.criteria if criterion.category in {"financial", "commercial"}],
        "compliance_terms": [to_dict(criterion) for criterion in result.criteria if criterion.category in {"compliance", "document"}],
    }


def _criteria_by_category(result: EvaluationResult, categories: set[str]) -> list[dict[str, object]]:
    return [to_dict(criterion) for criterion in result.criteria if criterion.category in categories]


def _verdicts_by_category(result: EvaluationResult, categories: set[str]) -> list[dict[str, object]]:
    criterion_categories = {criterion.id: criterion.category for criterion in result.criteria}
    return [
        {"bidder": bidder.bidder, "verdict": to_dict(verdict)}
        for bidder in result.bidders
        for verdict in bidder.verdicts
        if criterion_categories.get(verdict.criterion_id) in categories
    ]


def _manual_review_summary(result: EvaluationResult) -> list[dict[str, object]]:
    return [to_dict(task) for bidder in result.bidders for task in bidder.review_tasks]


def _submission_sources(result: EvaluationResult) -> list[dict[str, object]]:
    return [
        {
            "bidder": bidder.bidder,
            "documents": sorted({verdict.bidder_source.document for verdict in bidder.verdicts if verdict.bidder_source.document}),
        }
        for bidder in result.bidders
    ]


def _document_sources(result: EvaluationResult) -> dict[str, object]:
    return {
        "tender_documents": sorted({criterion.tender_citation.document for criterion in result.criteria if criterion.tender_citation.document}),
        "bidder_documents": _submission_sources(result),
    }


def _evidence_from_verdicts(result: EvaluationResult) -> list[dict[str, object]]:
    return [
        {
            "bidder": bidder.bidder,
            "criterion_id": verdict.criterion_id,
            "criterion": verdict.criterion,
            "document": verdict.bidder_source.document,
            "page": verdict.bidder_source.page,
            "extracted_value": verdict.extracted_value,
            "confidence": verdict.confidence,
            "source_excerpt": verdict.bidder_source.excerpt,
        }
        for bidder in result.bidders
        for verdict in bidder.verdicts
    ]


def _events_containing(audit_events: list[AuditEvent], tokens: list[str]) -> list[dict[str, object]]:
    return [
        to_dict(event)
        for event in audit_events
        if any(token in event.step.lower() for token in tokens)
    ]


def _award_pack(result: EvaluationResult) -> dict[str, object]:
    reasons = _selection_reasons(result)
    winner = next((item for item in reasons if item["decision"] == "Selected for award recommendation"), None)
    return {
        "recommended_bidder": winner["bidder"] if winner else "",
        "status": "ready_for_officer_approval" if winner else "not_ready",
        "reasons": reasons,
    }


def _selection_reasons(result: EvaluationResult) -> list[dict[str, str]]:
    prices = {bidder.bidder: _bidder_price(bidder) for bidder in result.bidders}
    eligible_prices = {bidder: price for bidder, price in prices.items() if price is not None and _bidder_status(result, bidder) == "Eligible"}
    l1_bidder = min(eligible_prices, key=eligible_prices.get) if eligible_prices else ""
    l1_price = eligible_prices.get(l1_bidder)

    reasons: list[dict[str, str]] = []
    for bidder in result.bidders:
        price = prices.get(bidder.bidder)
        price_text = _format_inr(price) if price is not None else "price not extracted"
        if bidder.bidder == l1_bidder:
            reasons.append(
                {
                    "bidder": bidder.bidder,
                    "decision": "Selected for award recommendation",
                    "reason": f"Bidder is eligible and has the lowest extracted evaluated quote ({price_text}).",
                    "source": _price_source(bidder),
                }
            )
            continue

        if bidder.overall_status == "Eligible":
            l1_text = _format_inr(l1_price) if l1_price is not None else "not determined"
            reasons.append(
                {
                    "bidder": bidder.bidder,
                    "decision": "Not selected",
                    "reason": f"Bidder is eligible, but its extracted quote ({price_text}) is higher than the L1 quote ({l1_text}) from {l1_bidder or 'another bidder'}.",
                    "source": _price_source(bidder),
                }
            )
            continue

        failed = [verdict for verdict in bidder.verdicts if verdict.status == "FAIL"]
        reviews = [verdict for verdict in bidder.verdicts if verdict.status == "NEED_MANUAL_REVIEW"]
        if failed:
            detail = "; ".join(f"{verdict.criterion_id}: {verdict.reason}" for verdict in failed)
            source = "; ".join(_citation(verdict.bidder_source) for verdict in failed)
            reasons.append({"bidder": bidder.bidder, "decision": "Rejected / Not eligible", "reason": detail, "source": source})
        elif reviews:
            detail = "; ".join(f"{verdict.criterion_id}: {verdict.manual_review_reason or verdict.reason}" for verdict in reviews)
            source = "; ".join(_citation(verdict.bidder_source) for verdict in reviews)
            reasons.append({"bidder": bidder.bidder, "decision": "Hold for manual review", "reason": detail, "source": source})
        else:
            reasons.append({"bidder": bidder.bidder, "decision": "Not selected", "reason": "No awardable decision could be derived from current verdicts.", "source": ""})
    return reasons


def _bidder_status(result: EvaluationResult, bidder_name: str) -> str:
    for bidder in result.bidders:
        if bidder.bidder == bidder_name:
            return bidder.overall_status
    return ""


def _bidder_price(bidder) -> float | None:
    for verdict in bidder.verdicts:
        if verdict.criterion_id == "C7" or "quoted financial bid" in verdict.criterion.lower():
            return _money_to_rupees(verdict.extracted_value)
    return None


def _price_source(bidder) -> str:
    for verdict in bidder.verdicts:
        if verdict.criterion_id == "C7" or "quoted financial bid" in verdict.criterion.lower():
            return _citation(verdict.bidder_source)
    return "No price source document"


def _money_to_rupees(value: str) -> float | None:
    import re

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


def _format_inr(value: float | None) -> str:
    if value is None:
        return "not extracted"
    return f"INR {value:,.0f}"


def _citation(citation: Citation) -> str:
    if not citation.document:
        return "No source document"
    excerpt = _clean(citation.excerpt[:180])
    return f"{citation.document}, page {citation.page}: {excerpt}"


def _clean(value: str) -> str:
    return value.replace("|", "/").replace("\n", " ").strip()


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_")
