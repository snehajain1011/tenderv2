from pathlib import Path

from document_loader import load_bidder_documents, load_tender_documents
from evaluator import evaluate_bidders, extract_criteria
from rag import build_rag_index
from schema import Citation, Criterion, Evidence
from workflow import create_demo_workspace, run_workspace


ROOT = Path(__file__).resolve().parents[1]


def test_demo_workspace_evaluation_statuses(tmp_path):
    workspace = tmp_path / "demo_workspace"
    outputs = tmp_path / "outputs"
    create_demo_workspace(workspace)

    result, _ = run_workspace(workspace, outputs)
    statuses = {bidder.bidder: bidder.overall_status for bidder in result.bidders}

    assert statuses["bidder_a_eligible"] == "Eligible"
    assert statuses["bidder_b_low_turnover"] == "Not Eligible"
    assert statuses["bidder_c_missing_iso"] == "Need Manual Review"
    assert statuses["bidder_d_scanned_uncertain"] == "Need Manual Review"
    assert result.final_accuracy_gate_passed


def test_every_decisive_verdict_has_sources_and_rule_trace(tmp_path):
    workspace = tmp_path / "demo_workspace"
    outputs = tmp_path / "outputs"
    create_demo_workspace(workspace)

    result, _ = run_workspace(workspace, outputs)

    for bidder in result.bidders:
        for verdict in bidder.verdicts:
            assert verdict.criterion
            assert verdict.reason
            assert verdict.tender_source.document
            assert verdict.tender_source.excerpt
            if verdict.status in {"PASS", "FAIL"}:
                assert verdict.bidder_source.document
                assert verdict.extracted_value
                assert verdict.rule_trace
            if verdict.status == "NEED_MANUAL_REVIEW":
                assert verdict.manual_review_reason


def test_outputs_include_audit_and_reports(tmp_path):
    workspace = tmp_path / "demo_workspace"
    outputs = tmp_path / "outputs"
    create_demo_workspace(workspace)

    run_workspace(workspace, outputs)

    assert (outputs / "evaluation_report.md").exists()
    assert (outputs / "evaluation_report.json").exists()
    assert (outputs / "audit_log.jsonl").exists()
    assert "final_accuracy_gate" in (outputs / "audit_log.jsonl").read_text(encoding="utf-8")
    assert "database_persistence" in (outputs / "audit_log.jsonl").read_text(encoding="utf-8")


def test_unrecognized_real_tender_does_not_use_demo_criteria(tmp_path):
    workspace = tmp_path / "real_workspace"
    outputs = tmp_path / "outputs"
    tender_dir = workspace / "tender_documents"
    bidder_dir = workspace / "bidder_submissions" / "bidder_one"
    tender_dir.mkdir(parents=True)
    bidder_dir.mkdir(parents=True)
    (tender_dir / "uploaded_tender.txt").write_text(
        "Tender for supply of winter jackets. Delivery shall be completed within 45 days. "
        "Contract includes warranty and penalty clauses.",
        encoding="utf-8",
    )
    (bidder_dir / "proposal.txt").write_text("We propose to supply jackets within 45 days.", encoding="utf-8")

    result, _ = run_workspace(workspace, outputs)

    assert [criterion.id for criterion in result.criteria] == ["C0"]
    assert result.bidders[0].overall_status == "Need Manual Review"
    assert result.bidders[0].verdicts[0].status == "NEED_MANUAL_REVIEW"
    assert "Criteria extraction was not confident" in result.bidders[0].verdicts[0].manual_review_reason


def test_image_bidder_document_uses_local_ocr(tmp_path):
    try:
        from PIL import Image, ImageDraw, ImageFont
        import rapidocr_onnxruntime  # noqa: F401
    except Exception:
        return

    bidder_dir = tmp_path / "bidder_submissions" / "image_vendor"
    bidder_dir.mkdir(parents=True)
    image = Image.new("RGB", (1400, 420), "white")
    draw = ImageDraw.Draw(image)
    font_path = Path("C:/Windows/Fonts/arial.ttf")
    font = ImageFont.truetype(str(font_path), 34) if font_path.exists() else ImageFont.load_default()
    draw.multiline_text(
        (40, 40),
        "Kalinga Infratech Private Limited\n"
        "GST 21AAECK4821L1Z7\n"
        "Indicative Tendered Amount Rs. 5,189,268/-\n"
        "EMD of Rs. 109,076 enclosed",
        fill="black",
        font=font,
        spacing=16,
    )
    image.save(bidder_dir / "bid_image.png")

    bidders, audit, reviews = load_bidder_documents(tmp_path / "bidder_submissions")

    doc = bidders["image_vendor"][0]
    assert doc.parser == "rapidocr"
    assert doc.confidence >= 0.65
    assert "21AAECK4821L1Z7" in doc.text
    assert "5,189,268" in doc.text
    assert audit[0].detail["passed"]
    assert not reviews


def test_evaluation_persists_all_core_entities(tmp_path, monkeypatch):
    db_path = tmp_path / "procurement.sqlite"
    monkeypatch.setenv("PROCUREMENT_DB_PATH", str(db_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    workspace = tmp_path / "demo_workspace"
    outputs = tmp_path / "outputs"
    create_demo_workspace(workspace)

    result, audit = run_workspace(workspace, outputs)

    import sqlite3

    conn = sqlite3.connect(db_path)
    counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in [
            "tenders",
            "tender_documents",
            "vendors",
            "submissions",
            "bid_documents",
            "document_chunks",
            "criteria",
            "evidence",
            "verdicts",
            "review_tasks",
            "bidder_results",
            "awards",
            "agent_outputs",
            "audit_events",
        ]
    }
    conn.close()

    assert result.final_accuracy_gate_passed
    assert any(event.step == "database_persistence" and event.detail["passed"] for event in audit)
    assert counts["tenders"] == 1
    assert counts["criteria"] == len(result.criteria)
    assert counts["submissions"] == len(result.bidders)
    assert counts["verdicts"] == sum(len(bidder.verdicts) for bidder in result.bidders)
    assert counts["agent_outputs"] >= len(result.agents)
    assert counts["audit_events"] >= 1


def test_scanned_pdf_runs_page_ocr_and_records_quality(tmp_path):
    try:
        from PIL import Image, ImageDraw, ImageFont
        import rapidocr_onnxruntime  # noqa: F401
    except Exception:
        return

    tender_dir = tmp_path / "tender_documents"
    tender_dir.mkdir()
    image = Image.new("RGB", (1400, 520), "white")
    draw = ImageDraw.Draw(image)
    font_path = Path("C:/Windows/Fonts/arial.ttf")
    font = ImageFont.truetype(str(font_path), 36) if font_path.exists() else ImageFont.load_default()
    draw.multiline_text(
        (50, 50),
        "Tender eligibility criteria\n"
        "Average annual turnover must be at least Rs. 50 lakh.\n"
        "Bidder must submit valid GST registration.\n"
        "EMD of Rs. 10000 is required.",
        fill="black",
        font=font,
        spacing=18,
    )
    image.save(tender_dir / "scanned_tender.pdf", "PDF")

    docs, audit, reviews = load_tender_documents(tender_dir)

    assert "turnover" in docs[0].text.lower()
    assert docs[0].quality.ocr_confidence >= 0.65
    assert docs[0].quality.text_density > 5
    assert audit[0].detail["document_quality"]["ocr_engine"]
    assert not reviews


def test_partial_image_submission_uses_missing_required_evidence_not_ocr_failure(tmp_path):
    try:
        from PIL import Image, ImageDraw, ImageFont
        import rapidocr_onnxruntime  # noqa: F401
    except Exception:
        return

    workspace = tmp_path / "partial_workspace"
    outputs = tmp_path / "outputs"
    tender_dir = workspace / "tender_documents"
    bidder_dir = workspace / "bidder_submissions" / "image_only"
    tender_dir.mkdir(parents=True)
    bidder_dir.mkdir(parents=True)
    (tender_dir / "tender.txt").write_text(
        "Average annual turnover must be at least Rs. 50 lakh. "
        "Bidder must have valid GST registration. EMD of Rs. 10000 required.",
        encoding="utf-8",
    )
    image = Image.new("RGB", (1200, 360), "white")
    draw = ImageDraw.Draw(image)
    font_path = Path("C:/Windows/Fonts/arial.ttf")
    font = ImageFont.truetype(str(font_path), 34) if font_path.exists() else ImageFont.load_default()
    draw.multiline_text((40, 40), "Bidder Alpha\nGST 21AAECK4821L1Z7\nTechnical cover only", fill="black", font=font, spacing=16)
    image.save(bidder_dir / "gst_only.png")

    result, _ = run_workspace(workspace, outputs)
    tasks = result.bidders[0].review_tasks

    assert any(task.issue_type == "MISSING_REQUIRED_DOCUMENT" for task in tasks)
    assert all(task.issue_type != "LOW_OCR_CONFIDENCE" for task in tasks if "turnover" in task.reason.lower() or task.criterion_id == "C1")


def test_ambiguous_tender_clause_gets_risk_flag_and_review():
    criterion = Criterion(
        "C1",
        "financial",
        True,
        "Bidder must show adequate turnover.",
        Citation("tender.txt", 1, "eligibility", "Bidder must show adequate turnover."),
        "",
        "",
        "minimum",
        ["turnover certificate"],
        ["vague_threshold", "subjective_requirement"],
    )
    evidence = Evidence("C1", "alpha", "bid.txt", "Ambiguous turnover value", Citation("bid.txt", 1, "turnover", "Turnover Rs ?"), criterion.tender_citation, 0.8, "Ambiguous turnover value", "", "AMBIGUOUS_VALUE")

    result, _ = evaluate_bidders("ambiguous", [criterion], {"alpha": [evidence]})
    verdict = result.bidders[0].verdicts[0]

    assert verdict.status == "NEED_MANUAL_REVIEW"
    assert verdict.uncertainty_type == "AMBIGUOUS_TENDER_LANGUAGE"
    assert verdict.suggested_action


def test_conflicting_evidence_becomes_review_not_fail():
    criterion = Criterion(
        "C1",
        "financial",
        True,
        "Average annual turnover must meet the tender threshold.",
        Citation("tender.txt", 1, "eligibility", "Turnover at least Rs. 50 lakh"),
        "INR 50 lakh",
        "last 3 years",
        "minimum",
        ["turnover certificate"],
    )
    evidence_a = Evidence("C1", "alpha", "ca.pdf", "INR 80 lakh", Citation("ca.pdf", 1, "turnover", "Average turnover INR 80 lakh"), criterion.tender_citation, 0.95, "INR 80 lakh")
    evidence_b = Evidence("C1", "alpha", "balance.pdf", "INR 45 lakh", Citation("balance.pdf", 1, "turnover", "Average turnover INR 45 lakh"), criterion.tender_citation, 0.95, "INR 45 lakh")

    result, _ = evaluate_bidders("conflict", [criterion], {"alpha": [evidence_a, evidence_b]})
    verdict = result.bidders[0].verdicts[0]

    assert verdict.status == "NEED_MANUAL_REVIEW"
    assert verdict.uncertainty_type == "CONFLICTING_EVIDENCE"
    assert result.bidders[0].overall_status == "Need Manual Review"


def test_final_gate_requires_issue_type_and_suggested_action(tmp_path):
    workspace = tmp_path / "demo_workspace"
    outputs = tmp_path / "outputs"
    create_demo_workspace(workspace)

    result, _ = run_workspace(workspace, outputs)

    for bidder in result.bidders:
        for verdict in bidder.verdicts:
            if verdict.status in {"FAIL", "NEED_MANUAL_REVIEW"}:
                assert verdict.uncertainty_type
                assert verdict.suggested_action
