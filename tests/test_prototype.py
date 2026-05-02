from pathlib import Path

from document_loader import load_bidder_documents, load_tender_documents
from evaluator import evaluate_bidders, extract_criteria, extract_evidence


ROOT = Path(__file__).resolve().parents[1]


def test_sample_evaluation_statuses():
    criteria, _ = extract_criteria(load_tender_documents(ROOT / "data" / "tender"))
    evidence, _ = extract_evidence(criteria, load_bidder_documents(ROOT / "data" / "bidders"))
    result, _ = evaluate_bidders(criteria, evidence)

    statuses = {bidder.bidder: bidder.overall_status for bidder in result.bidders}

    assert statuses["bidder_a_eligible"] == "Eligible"
    assert statuses["bidder_b_low_turnover"] == "Not Eligible"
    assert statuses["bidder_c_missing_iso"] == "Need Manual Review"
    assert statuses["bidder_d_scanned_uncertain"] == "Need Manual Review"


def test_every_verdict_is_explainable():
    criteria, _ = extract_criteria(load_tender_documents(ROOT / "data" / "tender"))
    evidence, _ = extract_evidence(criteria, load_bidder_documents(ROOT / "data" / "bidders"))
    result, _ = evaluate_bidders(criteria, evidence)

    criterion_ids = {criterion.id for criterion in criteria}
    for bidder in result.bidders:
        assert {verdict.criterion_id for verdict in bidder.verdicts} == criterion_ids
        for verdict in bidder.verdicts:
            assert verdict.reason
            if verdict.status == "REVIEW":
                assert verdict.manual_review_reason
            else:
                assert verdict.document
                assert verdict.value

