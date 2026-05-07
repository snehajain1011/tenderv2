from __future__ import annotations

import logging
import sys
from pathlib import Path
import urllib.request

# Ensure all sibling modules (schema, workflow, …) are importable by bare name.
sys.path.insert(0, str(Path(__file__).parent))

from workflow import create_demo_workspace, run_workspace

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

try:
    from fastapi import FastAPI, File, HTTPException, UploadFile
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, PlainTextResponse
except ImportError:  # pragma: no cover - lets the core CLI run without web deps.
    FastAPI = None
    HTTPException = Exception


if FastAPI:
    app = FastAPI(title="Procurement AI Platform", version="0.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/agents")
    def agents() -> dict[str, object]:
        from evaluator import agent_catalog
        from schema import to_dict

        return {"agents": to_dict(agent_catalog())}

    @app.get("/workspaces/{workspace_name}/procurement-flow")
    def procurement_flow(workspace_name: str) -> dict[str, object]:
        workspace = _workspace_path(workspace_name)
        if not workspace.exists():
            raise HTTPException(status_code=404, detail="Workspace not found")
        return _procurement_flow_payload(workspace_name, workspace)

    @app.get("/workspaces")
    def list_workspaces() -> dict[str, object]:
        base = Path("workspaces")
        base.mkdir(exist_ok=True)
        return {"workspaces": sorted(path.name for path in base.iterdir() if path.is_dir())}

    @app.post("/workspaces/{workspace_name}")
    def create_workspace(workspace_name: str) -> dict[str, str]:
        workspace = _workspace_path(workspace_name)
        (workspace / "tender_documents").mkdir(parents=True, exist_ok=True)
        (workspace / "bidder_submissions").mkdir(parents=True, exist_ok=True)
        return {"workspace": str(workspace), "status": "created"}

    @app.post("/workspaces/demo")
    def create_demo() -> dict[str, str]:
        workspace = Path("workspaces/demo")
        create_demo_workspace(workspace)
        return {"workspace": str(workspace), "status": "created"}

    @app.post("/workspaces/{workspace_name}/tender-documents")
    async def upload_tender_documents(workspace_name: str, files: list[UploadFile] = File(...)) -> dict[str, object]:
        target = _workspace_path(workspace_name) / "tender_documents"
        target.mkdir(parents=True, exist_ok=True)
        saved = await _save_uploads(target, files)
        return {"stored_in": str(target), "saved": saved}

    @app.post("/workspaces/{workspace_name}/tender-url")
    def import_tender_url(workspace_name: str, url: str) -> dict[str, object]:
        target = _workspace_path(workspace_name) / "tender_documents"
        target.mkdir(parents=True, exist_ok=True)
        filename = _safe_filename(Path(url.split("?")[0]).name or "tender.pdf")
        path = target / filename
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                path.write_bytes(response.read())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Could not import tender URL: {exc}")
        return {"stored_in": str(target), "saved": [filename], "source_url": url}

    @app.post("/workspaces/{workspace_name}/vendors/{vendor_name}/documents")
    async def upload_vendor_documents(workspace_name: str, vendor_name: str, files: list[UploadFile] = File(...)) -> dict[str, object]:
        target = _workspace_path(workspace_name) / "bidder_submissions" / _safe_name(vendor_name)
        target.mkdir(parents=True, exist_ok=True)
        saved = await _save_uploads(target, files)
        return {"vendor": vendor_name, "stored_in": str(target), "saved": saved}

    @app.get("/workspaces/{workspace_name}/documents")
    def workspace_documents(workspace_name: str) -> dict[str, object]:
        workspace = _workspace_path(workspace_name)
        if not workspace.exists():
            raise HTTPException(status_code=404, detail="Workspace not found")
        return {
            "workspace": workspace_name,
            "root": str(workspace),
            "tender_documents": _files_under(workspace / "tender_documents"),
            "bidder_submissions": _bidder_docs(workspace / "bidder_submissions"),
        }

    @app.get("/workspaces/{workspace_name}/dashboard")
    def dashboard(workspace_name: str) -> dict[str, object]:
        workspace = _workspace_path(workspace_name)
        if not workspace.exists():
            raise HTTPException(status_code=404, detail="Workspace not found")
        output = Path("outputs") / _safe_name(workspace_name) / "evaluation_report.json"
        result = None
        if output.exists():
            import json

            result = json.loads(output.read_text(encoding="utf-8"))
        bidder_docs = _bidder_docs(workspace / "bidder_submissions")
        return {
            "workspace": workspace_name,
            "tender_document_count": len(_files_under(workspace / "tender_documents")),
            "bidder_count": len(bidder_docs),
            "bid_document_count": sum(len(item["documents"]) for item in bidder_docs),
            "evaluation_progress": "complete" if result else "not_started",
            "pending_reviews": _count_pending_reviews(result),
            "eligible_bidders": _count_bidders(result, "Eligible"),
            "not_eligible_bidders": _count_bidders(result, "Not Eligible"),
            "manual_review_bidders": _count_bidders(result, "Need Manual Review"),
        }

    @app.get("/workspaces/{workspace_name}/persistence")
    def persistence_summary(workspace_name: str) -> dict[str, object]:
        from persistence import workspace_persistence_summary

        try:
            return workspace_persistence_summary(workspace_name)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Persistence summary unavailable: {exc}")

    @app.post("/workspaces/{workspace_name}/evaluate")
    def evaluate(workspace_name: str, use_llm: bool = False) -> dict[str, object]:
        from schema import to_dict

        workspace = _workspace_path(workspace_name)
        if not workspace.exists():
            raise HTTPException(status_code=404, detail="Workspace not found")
        result, _ = run_workspace(workspace, Path("outputs") / workspace_name, use_llm=use_llm)
        return to_dict(result)

    @app.get("/workspaces/{workspace_name}/corrigendum")
    def corrigendum_report(workspace_name: str) -> dict[str, object]:
        """
        Return the corrigendum (amendment) report for the workspace.
        Only present after a second evaluation run detects criteria changes.
        """
        import json as _json
        path = Path("outputs") / _safe_name(workspace_name) / "corrigendum_report.json"
        if not path.exists():
            return {
                "workspace": workspace_name,
                "has_changes": False,
                "message": "No corrigendum detected — either this is the first evaluation or no criteria changed.",
            }
        report = _json.loads(path.read_text(encoding="utf-8"))
        return {
            "workspace": workspace_name,
            "has_changes": True,
            **report,
        }

    @app.get("/workspaces/{workspace_name}/audit-trail")
    def audit_trail(workspace_name: str) -> dict[str, object]:
        """Return all audit events for a workspace as structured JSON."""
        import json as _json
        path = Path("outputs") / _safe_name(workspace_name) / "audit_log.jsonl"
        if not path.exists():
            raise HTTPException(status_code=404, detail="Audit log not found. Run evaluation first.")
        events = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    events.append(_json.loads(line))
                except Exception:
                    pass
        return {"workspace": workspace_name, "total": len(events), "events": events}

    @app.get("/workspaces/{workspace_name}/vendor-directory")
    def vendor_directory(workspace_name: str) -> dict[str, object]:
        """
        Return a vendor profile directory built from the latest evaluation result.
        Each entry includes GSTIN status, eligibility, criteria summary, and
        any procurement risk flags from the DB.
        """
        import json as _json
        output = Path("outputs") / _safe_name(workspace_name) / "evaluation_report.json"
        if not output.exists():
            raise HTTPException(status_code=404, detail="Run evaluation first.")
        raw = _json.loads(output.read_text(encoding="utf-8"))

        vendors = []
        for bidder in raw.get("bidders", []):
            gstin_check = bidder.get("gstin_check") or {}
            verdicts = bidder.get("verdicts", [])
            passed  = sum(1 for v in verdicts if v.get("status") == "PASS")
            failed  = sum(1 for v in verdicts if v.get("status") == "FAIL")
            review  = sum(1 for v in verdicts if v.get("status") == "NEED_MANUAL_REVIEW")
            vendors.append({
                "name":            bidder.get("bidder", ""),
                "overall_status":  bidder.get("overall_status", ""),
                "gstin":           gstin_check.get("gstin", ""),
                "legal_name":      gstin_check.get("legal_name", ""),
                "gstin_status":    gstin_check.get("check_status", "not_found"),
                "gstin_valid":     gstin_check.get("is_valid", False),
                "gstin_active":    gstin_check.get("is_active", False),
                "flagged":         gstin_check.get("check_status") == "flagged",
                "flag_reason":     gstin_check.get("rejection_reason", "") if gstin_check.get("check_status") == "flagged" else "",
                "criteria_passed": passed,
                "criteria_failed": failed,
                "criteria_review": review,
                "total_criteria":  len(verdicts),
                "review_tasks":    len(bidder.get("review_tasks", [])),
                "tender_id":       raw.get("tender_id", workspace_name),
            })

        return {
            "workspace":    workspace_name,
            "total_vendors": len(vendors),
            "vendors":       vendors,
        }

    @app.get("/workspaces/{workspace_name}/bidders/{bidder_name}/rejection-report")
    def bidder_rejection_report(workspace_name: str, bidder_name: str):
        """Return a self-contained HTML adjudication report for one bidder."""
        import json
        from rejection_report import generate_rejection_html
        from schema import EvaluationResult, to_dict

        output = Path("outputs") / _safe_name(workspace_name) / "evaluation_report.json"
        if not output.exists():
            raise HTTPException(status_code=404, detail="Run evaluation first.")

        raw = json.loads(output.read_text(encoding="utf-8"))

        # Reconstruct enough of EvaluationResult for the report generator
        from schema import (
            AgentDefinition, BidderResult, BidderQualityReport, Citation,
            Criterion, GstinCheck, ReviewTask, RiskSignal, Verdict,
        )

        def _citation(d: dict) -> Citation:
            return Citation(d.get("document",""), d.get("page",0), d.get("section",""), d.get("excerpt",""), d.get("chunk_id",""))

        def _verdict(d: dict) -> Verdict:
            return Verdict(
                d.get("criterion_id",""), d.get("criterion",""), d.get("status",""),
                d.get("reason",""), _citation(d.get("tender_source",{})),
                _citation(d.get("bidder_source",{})),
                d.get("extracted_value",""), d.get("confidence",0.0),
                d.get("rule_trace",""), d.get("manual_review_reason",""),
                d.get("human_reviewer_action",""), d.get("uncertainty_type",""),
                d.get("suggested_action",""),
            )

        def _task(d: dict) -> ReviewTask:
            return ReviewTask(
                d.get("task_id",""), d.get("bidder",""), d.get("criterion_id",""),
                d.get("reason",""), d.get("priority","high"),
                _citation(d.get("source",{})), d.get("issue_type",""),
                d.get("extracted_value",""), d.get("confidence",0.0),
                d.get("suggested_action",""),
            )

        def _gstin(d: dict | None) -> GstinCheck | None:
            if not d:
                return None
            return GstinCheck(
                d.get("gstin",""), d.get("legal_name",""),
                bool(d.get("is_valid")), bool(d.get("is_active")),
                d.get("check_status","clear"), d.get("rejection_reason",""),
            )

        def _criterion(d: dict) -> Criterion:
            tc = _citation(d.get("tender_citation", {}))
            return Criterion(
                d.get("id",""), d.get("category","document"),
                bool(d.get("mandatory")), d.get("description",""), tc,
                d.get("threshold",""), d.get("time_period",""),
                d.get("comparison_rule","present"),
                d.get("accepted_evidence",[]),
                d.get("criteria_risk_flags",[]),
            )

        criteria = [_criterion(c) for c in raw.get("criteria", [])]

        target_name = bidder_name.strip()
        bidder_data = next(
            (b for b in raw.get("bidders", []) if b.get("bidder","").strip() == target_name),
            None,
        )
        if not bidder_data:
            raise HTTPException(status_code=404, detail=f"Bidder '{bidder_name}' not found in evaluation results.")

        br = BidderResult(
            bidder=bidder_data.get("bidder",""),
            overall_status=bidder_data.get("overall_status",""),
            verdicts=[_verdict(v) for v in bidder_data.get("verdicts", [])],
            review_tasks=[_task(t) for t in bidder_data.get("review_tasks", [])],
            gstin_check=_gstin(bidder_data.get("gstin_check")),
        )

        # Minimal EvaluationResult stub — only fields used by report generator
        tq_raw = raw.get("bidder_quality")
        tq = BidderQualityReport(
            overall_score=tq_raw.get("overall_score", 0) if tq_raw else 0,
            grade=tq_raw.get("grade", "—") if tq_raw else "—",
            flagged_criteria=tq_raw.get("flagged_criteria", []) if tq_raw else [],
            summary=tq_raw.get("summary", "") if tq_raw else "",
        ) if tq_raw else None

        evaluation_stub = EvaluationResult(
            tender_id=raw.get("tender_id", workspace_name),
            criteria=criteria,
            bidders=[br],
            agents=[],
            final_accuracy_gate_passed=bool(raw.get("final_accuracy_gate_passed")),
            final_accuracy_issues=raw.get("final_accuracy_issues", []),
            bidder_quality=tq,
            risk_signals=[],
        )

        html_content = generate_rejection_html(br, evaluation_stub)
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=html_content, media_type="text/html; charset=utf-8")

    @app.get("/workspaces/{workspace_name}/checklist.csv")
    def checklist_csv(workspace_name: str):
        """
        Return a CSV evaluation matrix: one row per criterion, one column per bidder verdict.
        Officers can open this in Excel to score bids manually or verify AI results.
        """
        import csv
        import io
        import json as _json
        from fastapi.responses import StreamingResponse

        output = Path("outputs") / _safe_name(workspace_name) / "evaluation_report.json"
        if not output.exists():
            raise HTTPException(status_code=404, detail="Run evaluation first.")
        raw = _json.loads(output.read_text(encoding="utf-8"))

        criteria = raw.get("criteria", [])
        bidders = raw.get("bidders", [])
        bidder_names = [b.get("bidder", "") for b in bidders]

        # Build verdict lookup: {bidder_name: {criterion_id: verdict}}
        verdict_map: dict[str, dict[str, dict]] = {}
        for b in bidders:
            bname = b.get("bidder", "")
            verdict_map[bname] = {v.get("criterion_id", ""): v for v in b.get("verdicts", [])}

        buf = io.StringIO()
        writer = csv.writer(buf)

        # Header row
        header = ["ID", "Category", "Mandatory", "Description", "Threshold",
                  "Time Period", "Rule", "Accepted Evidence"] + bidder_names
        writer.writerow(header)

        for c in criteria:
            cid = c.get("id", "")
            row = [
                cid,
                c.get("category", ""),
                "Yes" if c.get("mandatory") else "No",
                c.get("description", ""),
                c.get("threshold", ""),
                c.get("time_period", ""),
                c.get("comparison_rule", ""),
                "; ".join(c.get("accepted_evidence", [])),
            ]
            for bname in bidder_names:
                v = verdict_map.get(bname, {}).get(cid)
                if v:
                    row.append(f"{v.get('status','')} — {v.get('extracted_value','') or v.get('reason','')[:60]}")
                else:
                    row.append("N/A")
            writer.writerow(row)

        buf.seek(0)
        filename = f"evaluation_checklist_{_safe_name(workspace_name)}.csv"
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/workspaces/{workspace_name}/reports/{report_name}")
    def get_report(workspace_name: str, report_name: str):
        allowed = {
            "evaluation_report.md": "text/markdown",
            "evaluation_report.json": "application/json",
            "agent_outputs.json": "application/json",
            "audit_log.jsonl": "application/jsonl",
        }
        if report_name not in allowed:
            raise HTTPException(status_code=404, detail="Report not found")
        path = Path("outputs") / _safe_name(workspace_name) / report_name
        if not path.exists():
            raise HTTPException(status_code=404, detail="Report not generated yet")
        if report_name.endswith(".md") or report_name.endswith(".jsonl"):
            return PlainTextResponse(path.read_text(encoding="utf-8"), media_type=allowed[report_name])
        return FileResponse(path, media_type=allowed[report_name])
else:
    app = None


def _workspace_path(workspace_name: str) -> Path:
    return Path("workspaces") / _safe_name(workspace_name)


def _safe_name(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value.strip())
    if not safe:
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    return safe


async def _save_uploads(target: Path, files: list) -> list[str]:
    saved: list[str] = []
    for upload in files:
        filename = _safe_filename(Path(upload.filename or "document").name)
        path = target / filename
        path.write_bytes(await upload.read())
        saved.append(filename)
    return saved


def _safe_filename(value: str) -> str:
    original = Path(value.strip() or "document")
    suffix = original.suffix.lower()
    stem = _safe_name(original.stem or "document")
    if not suffix and stem.lower().endswith("_pdf"):
        stem = stem[:-4]
        suffix = ".pdf"
    if suffix and not all(char.isalnum() or char == "." for char in suffix):
        suffix = ""
    return f"{stem}{suffix}"


def _procurement_flow_payload(workspace_name: str, workspace: Path) -> dict[str, object]:
    tender_docs = _files_under(workspace / "tender_documents")
    bidders_dir = workspace / "bidder_submissions"
    bidder_docs = {
        path.name: _files_under(path)
        for path in sorted(bidders_dir.iterdir())
        if path.is_dir()
    } if bidders_dir.exists() else {}
    return {
        "workspace": workspace_name,
        "pre_tender": [
            {
                "step": "Prepare procurement documents / tender package",
                "status": "ready" if tender_docs else "pending",
                "items": [
                    "Collect technical specifications",
                    "Define quantity, budget, delivery terms",
                    "Add vendor eligibility criteria",
                    "Include contract terms and conditions",
                ],
                "evidence": tender_docs,
            },
            {
                "step": "Upload tender document to portal",
                "status": "ready" if tender_docs else "blocked",
                "items": [
                    "Publish on GeM / e-tender portal",
                    "Make tender available for bidders/vendors",
                    "Preserve source document hashes and version history",
                ],
                "evidence": tender_docs,
            },
        ],
        "tender_stage": [
            {
                "step": "Download / collect submitted bids",
                "status": "ready" if bidder_docs else "pending",
                "items": ["Collect quotations/proposals", "Store immutable vendor submissions"],
                "evidence": [{"vendor": vendor, "documents": docs} for vendor, docs in bidder_docs.items()],
            },
            {
                "step": "Review bid details",
                "status": "ready" if bidder_docs else "blocked",
                "items": ["Price comparison", "Technical comparison", "Vendor qualification check"],
            },
            {
                "step": "Generate consolidated report",
                "status": "ready" if bidder_docs else "blocked",
                "items": ["Summarize all bids", "Show rejection/manual-review reasons with source citations"],
            },
            {
                "step": "Coordinate bid evaluation / POC",
                "status": "ready" if bidder_docs else "blocked",
                "items": ["Coordinate with technical teams", "Clarify vendor questions", "Verify documents"],
            },
            {
                "step": "Award contract",
                "status": "ready_after_evaluation",
                "items": ["Select winning bidder", "Issue purchase order / contract"],
            },
        ],
        "non_negotiables": [
            "Every final decision cites criterion, tender source, bidder source, extracted value, and reason.",
            "Ambiguous or uncertain cases become NEED_MANUAL_REVIEW.",
            "Scanned documents/photos are accepted and OCR confidence is reviewed.",
            "Audit log stores file hashes, parsing checkpoints, RAG checkpoints, rule traces, and final reports.",
        ],
    }


def _files_under(folder: Path) -> list[str]:
    if not folder.exists():
        return []
    return [str(path.relative_to(folder)) for path in sorted(folder.rglob("*")) if path.is_file()]


def _bidder_docs(folder: Path) -> list[dict[str, object]]:
    if not folder.exists():
        return []
    return [
        {"vendor": path.name, "documents": _files_under(path)}
        for path in sorted(folder.iterdir())
        if path.is_dir()
    ]


def _count_bidders(result: dict[str, object] | None, status: str) -> int:
    if not result:
        return 0
    return sum(1 for bidder in result.get("bidders", []) if bidder.get("overall_status") == status)


def _count_pending_reviews(result: dict[str, object] | None) -> int:
    if not result:
        return 0
    return sum(len(bidder.get("review_tasks", [])) for bidder in result.get("bidders", []))
