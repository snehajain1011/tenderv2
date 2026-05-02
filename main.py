from __future__ import annotations

import argparse
from pathlib import Path

from document_loader import load_bidder_documents, load_tender_documents
from evaluator import evaluate_bidders, extract_criteria, extract_evidence
from llm_client import OllamaClient
from report import write_reports


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate bidder eligibility against tender criteria.")
    parser.add_argument("--tender-dir", default="data/tender", help="Folder containing tender documents.")
    parser.add_argument("--bidders-dir", default="data/bidders", help="Folder containing bidder subfolders.")
    parser.add_argument("--outputs-dir", default="outputs", help="Folder where reports are written.")
    parser.add_argument("--use-llm", action="store_true", help="Use local Ollama-compatible LLM if available.")
    parser.add_argument("--model", default="qwen3:8b", help="Ollama model name.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tender_dir = Path(args.tender_dir)
    bidders_dir = Path(args.bidders_dir)
    outputs_dir = Path(args.outputs_dir)

    llm = OllamaClient(model=args.model) if args.use_llm else None

    tender_docs = load_tender_documents(tender_dir)
    bidder_docs = load_bidder_documents(bidders_dir)

    criteria, criteria_audit = extract_criteria(tender_docs, llm)
    evidence_by_bidder, evidence_audit = extract_evidence(criteria, bidder_docs, llm)
    result, evaluation_audit = evaluate_bidders(criteria, evidence_by_bidder)

    audit_events = [*criteria_audit, *evidence_audit, *evaluation_audit]
    write_reports(outputs_dir, result, audit_events)

    print(f"Evaluated {len(result.bidders)} bidders against {len(criteria)} criteria.")
    print(f"Markdown report: {outputs_dir / 'evaluation_report.md'}")
    print(f"JSON report: {outputs_dir / 'evaluation_report.json'}")
    print(f"Audit log: {outputs_dir / 'audit_log.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

