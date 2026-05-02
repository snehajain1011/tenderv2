from __future__ import annotations

import shutil
from pathlib import Path

from document_loader import load_bidder_documents, load_tender_documents
from evaluator import evaluate_bidders, extract_criteria, extract_evidence
from model_registry import ModelRegistry
from persistence import persist_evaluation_run
from rag import build_rag_index
from report import write_reports
from schema import AuditEvent, EvaluationResult


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

    criteria, criteria_audit = extract_criteria(tender_docs, tender_index, llm)
    evidence_by_bidder, evidence_audit, evidence_reviews = extract_evidence(criteria, bidder_docs, bidder_indexes, llm)
    result, evaluation_audit = evaluate_bidders(
        tender_id=workspace.name,
        criteria=criteria,
        evidence_by_bidder=evidence_by_bidder,
        existing_reviews=[*tender_reviews, *bidder_reviews, *evidence_reviews],
    )

    audit_events = [
        AuditEvent("workspace_loaded", workspace.name, {"tender_dir": str(tender_dir), "bidders_dir": str(bidders_dir)}),
        *tender_audit,
        *bidder_audit,
        *rag_audit,
        AuditEvent("rag_accuracy_setup", workspace.name, {"chunk_issues": chunk_issues, "passed": not chunk_issues}),
        *criteria_audit,
        *evidence_audit,
        *evaluation_audit,
    ]
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
    return result, audit_events
