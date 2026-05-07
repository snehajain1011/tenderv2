from __future__ import annotations

import shutil
from pathlib import Path

from corrigendum_tracker import diff_criteria, load_criteria_snapshot, save_criteria_snapshot
from document_loader import load_bidder_documents, load_tender_documents
from evaluator import evaluate_bidders, extract_criteria, extract_evidence
from gstin_validator import run_gstin_checks
from model_registry import ModelRegistry
from persistence import ProcurementRepository, persist_evaluation_run
from rag import build_rag_index
from report import write_reports
from risk_engine import detect_risk_signals, score_bidder_quality
from schema import AuditEvent, BidderResult, EvaluationResult


DEMO_TENDER_DIR = Path("data/tender")
DEMO_BIDDERS_DIR = Path("data/bidders")


def create_demo_workspace(workspace: Path) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    (workspace / "tender_documents").mkdir(parents=True)
    (workspace / "bidder_submissions").mkdir(parents=True)
    shutil.copytree(DEMO_TENDER_DIR, workspace / "tender_documents", dirs_exist_ok=True)
    shutil.copytree(DEMO_BIDDERS_DIR, workspace / "bidder_submissions", dirs_exist_ok=True)


def run_workspace(
    workspace: Path,
    outputs_dir: Path,
    models_path: Path = Path("models.yaml"),
    use_llm: bool = False,
) -> tuple[EvaluationResult, list[AuditEvent]]:
    tender_dir = workspace / "tender_documents"
    bidders_dir = workspace / "bidder_submissions"
    if not tender_dir.exists() or not bidders_dir.exists():
        raise FileNotFoundError(
            "Workspace must contain tender_documents/ and bidder_submissions/. "
            "Use --demo to create a representative sandbox workspace."
        )

    registry = ModelRegistry.from_file(models_path)
    llm = registry.client("reasoning") if use_llm else None

    tender_docs, tender_audit, tender_reviews = load_tender_documents(tender_dir)
    bidder_docs, bidder_audit, bidder_reviews = load_bidder_documents(bidders_dir)

    # ── GSTIN pre-check ──────────────────────────────────────────────────────
    # Validate each bidder's GSTIN before touching eligibility criteria.
    # Scenario 1: invalid/inactive GSTIN → immediate rejection (red card).
    # Scenario 2: valid GSTIN but DB-flagged → immediate rejection (red card).
    # Scenario 3: valid and not flagged → proceed to criteria evaluation.
    repo = ProcurementRepository()
    try:
        gstin_checks = run_gstin_checks(bidder_docs, repo)
    finally:
        repo.close()

    # "no_gstin" bidders (possible foreign/international) proceed to criteria evaluation
    # but their check status remains visible in the output for manual review.
    gstin_rejected_bidders = {b for b, c in gstin_checks.items() if c.check_status in ("invalid", "flagged")}
    valid_bidder_docs = {b: docs for b, docs in bidder_docs.items() if b not in gstin_rejected_bidders}
    # ─────────────────────────────────────────────────────────────────────────

    tender_index, tender_rag_audit, tender_chunk_issues = build_rag_index(tender_docs)
    bidder_indexes = {}
    bidder_chunks = {}
    rag_audit = [*tender_rag_audit]
    chunk_issues = [*tender_chunk_issues]
    for bidder, docs in bidder_docs.items():
        bidder_index, bidder_rag_audit, bidder_chunk_issues = build_rag_index(docs)
        bidder_indexes[bidder] = bidder_index
        bidder_chunks[bidder] = bidder_index.chunks
        rag_audit.extend(bidder_rag_audit)
        chunk_issues.extend([f"{bidder}: {issue}" for issue in bidder_chunk_issues])

    # ── Corrigendum check ────────────────────────────────────────────────────
    # Load previous snapshot BEFORE extracting new criteria so we can diff them.
    previous_snapshot = load_criteria_snapshot(outputs_dir)
    # ─────────────────────────────────────────────────────────────────────────

    criteria, criteria_audit = extract_criteria(tender_docs, tender_index, llm)

    # Only run evidence extraction and evaluation for GSTIN-valid bidders
    valid_bidder_indexes = {b: idx for b, idx in bidder_indexes.items() if b not in gstin_rejected_bidders}
    evidence_by_bidder, evidence_audit, evidence_reviews = extract_evidence(
        criteria, valid_bidder_docs, valid_bidder_indexes, llm
    )
    result, evaluation_audit = evaluate_bidders(
        tender_id=workspace.name,
        criteria=criteria,
        evidence_by_bidder=evidence_by_bidder,
        existing_reviews=[*tender_reviews, *bidder_reviews, *evidence_reviews],
    )

    # Attach gstin_check to every evaluated bidder result
    evaluated_bidders = [
        BidderResult(
            bidder=br.bidder,
            overall_status=br.overall_status,
            verdicts=br.verdicts,
            review_tasks=br.review_tasks,
            gstin_check=gstin_checks.get(br.bidder),
        )
        for br in result.bidders
    ]

    # Add immediately-rejected bidders (no criteria evaluated)
    rejected_bidder_results = [
        BidderResult(
            bidder=bidder,
            overall_status="Not Eligible",
            verdicts=[],
            review_tasks=[],
            gstin_check=gstin_checks[bidder],
        )
        for bidder in gstin_rejected_bidders
    ]

    # ── Feature 1: Bidder Ambiguity Scoring ──────────────────────────────────
    bidder_quality = score_bidder_quality(criteria)

    # ── Feature 2: Procurement Risk Intelligence ──────────────────────────────
    all_bidder_results = [*evaluated_bidders, *rejected_bidder_results]
    risk_signals = detect_risk_signals(
        criteria,
        evidence_by_bidder,
        bidder_docs,
        all_bidder_results,
    )

    result = EvaluationResult(
        tender_id=result.tender_id,
        criteria=result.criteria,
        bidders=all_bidder_results,
        agents=result.agents,
        final_accuracy_gate_passed=result.final_accuracy_gate_passed,
        final_accuracy_issues=result.final_accuracy_issues,
        bidder_quality=bidder_quality,
        risk_signals=risk_signals,
    )

    # ── Corrigendum diff + snapshot save ─────────────────────────────────────
    corrigendum = None
    if previous_snapshot is not None:
        corrigendum = diff_criteria(previous_snapshot, criteria, all_bidder_results)
    save_criteria_snapshot(outputs_dir, criteria)
    # ─────────────────────────────────────────────────────────────────────────

    audit_events = [
        AuditEvent("workspace_loaded", workspace.name, {"tender_dir": str(tender_dir), "bidders_dir": str(bidders_dir)}),
        AuditEvent("gstin_precheck", workspace.name, {
            "checks": {b: c.check_status for b, c in gstin_checks.items()},
            "rejected": sorted(gstin_rejected_bidders),
        }),
        *tender_audit,
        *bidder_audit,
        *rag_audit,
        AuditEvent("rag_accuracy_setup", workspace.name, {"chunk_issues": chunk_issues, "passed": not chunk_issues}),
        *criteria_audit,
        *evidence_audit,
        *evaluation_audit,
    ]
    if corrigendum:
        from schema import to_dict
        audit_events.append(AuditEvent("corrigendum_detected", workspace.name, to_dict(corrigendum)))

    persistence_audit = persist_evaluation_run(
        workspace.name,
        workspace,
        tender_docs,
        bidder_docs,
        tender_index.chunks,
        bidder_chunks,
        criteria,
        evidence_by_bidder,
        result,
        audit_events,
    )
    audit_events.append(persistence_audit)
    write_reports(outputs_dir, result, audit_events)

    # Persist corrigendum report for API access
    if corrigendum:
        import json
        from schema import to_dict
        corrigendum_path = outputs_dir / "corrigendum_report.json"
        corrigendum_path.write_text(
            json.dumps(to_dict(corrigendum), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return result, audit_events
