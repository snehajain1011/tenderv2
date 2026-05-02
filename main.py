from __future__ import annotations

import argparse
from pathlib import Path

from workflow import create_demo_workspace, run_workspace


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Production-style procurement AI workflow runner.")
    parser.add_argument("--workspace", default="", help="Workspace containing tender_documents/ and bidder_submissions/.")
    parser.add_argument("--outputs-dir", default="outputs", help="Folder where reports are written.")
    parser.add_argument("--models", default="models.yaml", help="Model registry config.")
    parser.add_argument("--use-llm", action="store_true", help="Use configured local LLM where available.")
    parser.add_argument("--demo", action="store_true", help="Create and run the representative sandbox workspace.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace) if args.workspace else Path("workspaces/demo")
    outputs_dir = Path(args.outputs_dir)

    if args.demo:
        create_demo_workspace(workspace)
    elif not args.workspace:
        raise SystemExit("No workspace supplied. Use --demo for sandbox data or --workspace path\\to\\workspace for real documents.")
    elif not workspace.exists():
        raise SystemExit(
            f"Workspace not found: {workspace}\n"
            "Create tender_documents/ and bidder_submissions/ inside it, or run with --demo."
        )

    result, _ = run_workspace(workspace, outputs_dir, Path(args.models), use_llm=args.use_llm)

    print(f"Tender workspace: {workspace}")
    print(f"Evaluated {len(result.bidders)} bidders against {len(result.criteria)} criteria.")
    print(f"Final accuracy gate: {'PASSED' if result.final_accuracy_gate_passed else 'FAILED'}")
    if result.final_accuracy_issues:
        print("Accuracy issues:")
        for issue in result.final_accuracy_issues:
            print(f"- {issue}")
    print(f"Markdown report: {outputs_dir / 'evaluation_report.md'}")
    print(f"JSON report: {outputs_dir / 'evaluation_report.json'}")
    print(f"Audit log: {outputs_dir / 'audit_log.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
