from __future__ import annotations

import json
from pathlib import Path

from schema import AuditEvent, EvaluationResult, to_dict


def write_reports(outputs_dir: Path, result: EvaluationResult, audit_events: list[AuditEvent]) -> None:
    outputs_dir.mkdir(parents=True, exist_ok=True)
    (outputs_dir / "evaluation_report.json").write_text(
        json.dumps(to_dict(result), indent=2),
        encoding="utf-8",
    )
    (outputs_dir / "evaluation_report.md").write_text(_markdown_report(result), encoding="utf-8")
    with (outputs_dir / "audit_log.jsonl").open("w", encoding="utf-8") as handle:
        for event in audit_events:
            handle.write(json.dumps(to_dict(event)) + "\n")


def _markdown_report(result: EvaluationResult) -> str:
    lines = [
        "# Tender Eligibility Evaluation Report",
        "",
        "## Criteria",
        "",
        "| ID | Category | Mandatory | Description | Threshold | Evidence Expected |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for criterion in result.criteria:
        lines.append(
            "| {id} | {category} | {mandatory} | {description} | {threshold} | {evidence} |".format(
                id=criterion.id,
                category=criterion.category,
                mandatory="Yes" if criterion.mandatory else "No",
                description=_clean(criterion.description),
                threshold=_clean(criterion.threshold),
                evidence=_clean(", ".join(criterion.accepted_evidence)),
            )
        )

    lines.extend(["", "## Bidder Results", ""])
    for bidder in result.bidders:
        lines.extend(
            [
                f"### {bidder.bidder}",
                "",
                f"Overall status: **{bidder.overall_status}**",
                "",
                "| Criterion | Status | Document | Value | Reason | Manual Review Reason |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for verdict in bidder.verdicts:
            lines.append(
                "| {criterion} | {status} | {document} | {value} | {reason} | {review} |".format(
                    criterion=verdict.criterion_id,
                    status=verdict.status,
                    document=_clean(verdict.document),
                    value=_clean(verdict.value),
                    reason=_clean(verdict.reason),
                    review=_clean(verdict.manual_review_reason),
                )
            )
        lines.append("")

    return "\n".join(lines)


def _clean(value: str) -> str:
    return value.replace("|", "/").replace("\n", " ").strip()

