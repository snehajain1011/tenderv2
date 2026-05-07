from __future__ import annotations

import os
from pathlib import Path
import urllib.request

from workflow import create_demo_workspace, run_workspace

try:
    from fastapi import FastAPI, File, HTTPException, UploadFile
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, PlainTextResponse
except ImportError:  # pragma: no cover - lets the core CLI run without web deps.
    FastAPI = None
    HTTPException = Exception


def _cors_origins() -> list[str]:
    configured = os.getenv("CORS_ORIGINS", "")
    origins = [item.strip() for item in configured.split(",") if item.strip()]
    return origins or [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://frontend-dusky-two-75.vercel.app",
        "https://frontend-hw1a5wztu-snehajain1011s-projects.vercel.app",
    ]


if FastAPI:
    app = FastAPI(title="Procurement AI Platform", version="0.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
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
