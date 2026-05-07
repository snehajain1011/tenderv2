"""
Procurement Risk Engine
=======================
Two independent responsibilities:

  1. score_tender_quality(criteria)
     Analyses tender criteria for ambiguity, vague thresholds, and subjective
     language BEFORE bids arrive.  Produces a TenderQualityReport.

  2. detect_risk_signals(criteria, evidence_by_bidder, bidder_docs, bidder_results)
     Runs post-evaluation fraud / collusion detection across all bidder
     submissions.  Produces a list of RiskSignal objects.
"""
from __future__ import annotations

import re
import statistics
from collections import defaultdict
from typing import TYPE_CHECKING

from schema import BidderQualityReport, RiskSignal

if TYPE_CHECKING:
    from schema import BidderResult, Criterion, Document, Evidence


# ── Ambiguity word lists ───────────────────────────────────────────────────────

_SUBJECTIVE_WORDS = {
    "adequate", "sufficient", "relevant", "reasonable", "satisfactory",
    "appropriate", "reputed", "good", "experienced", "suitable", "necessary",
    "similar nature", "as required", "as applicable", "as needed",
}

_UNVERIFIABLE_PHRASES = [
    "to the satisfaction of",
    "at the discretion of",
    "as deemed fit",
    "as deemed appropriate",
    "in the opinion of",
    "subject to approval",
]

_NUMERIC_EXPECTED_RULES = {"minimum", "count_at_least", "similar_work_value_combo", "emd_present"}


# ── Tender Quality Scoring ─────────────────────────────────────────────────────

def score_bidder_quality(criteria: list[Criterion]) -> BidderQualityReport:
    """
    Score every criterion for ambiguity and return a BidderQualityReport.

    Scoring per criterion (0–100, higher = more ambiguous / riskier):
      +20  each existing criteria_risk_flag
      +20  subjective word found in description
      +25  unverifiable phrase found ("to the satisfaction of…")
      +20  numeric threshold expected but missing
      +15  no accepted_evidence listed
      +10  description shorter than 40 characters
    Capped at 100.
    """
    flagged: list[dict] = []
    scores: list[int] = []

    for criterion in criteria:
        score = 0
        flags_found: list[str] = []
        desc_lower = criterion.description.lower()
        combined = f"{criterion.description} {criterion.threshold} {criterion.time_period}".lower()

        # Existing risk flags from extraction
        for flag in criterion.criteria_risk_flags:
            score += 20
            flags_found.append(flag)

        # Subjective language
        for word in _SUBJECTIVE_WORDS:
            if word in combined:
                score += 20
                flags_found.append(f"subjective_word:'{word}'")
                break  # count once per criterion

        # Unverifiable clauses
        for phrase in _UNVERIFIABLE_PHRASES:
            if phrase in desc_lower:
                score += 25
                flags_found.append(f"unverifiable_phrase:'{phrase}'")
                break

        # Missing numeric threshold
        if criterion.comparison_rule in _NUMERIC_EXPECTED_RULES and not criterion.threshold.strip():
            score += 20
            flags_found.append("missing_numeric_threshold")

        # No accepted evidence guidance
        if not criterion.accepted_evidence:
            score += 15
            flags_found.append("no_evidence_guidance")

        # Very short description
        if len(criterion.description.strip()) < 40:
            score += 10
            flags_found.append("short_description")

        score = min(score, 100)
        scores.append(score)

        if flags_found or score > 0:
            flagged.append({
                "id": criterion.id,
                "description": criterion.description,
                "score": score,
                "flags": sorted(set(flags_found)),
                "mandatory": criterion.mandatory,
            })

    overall = int(statistics.mean(scores)) if scores else 0
    grade = _grade(overall)
    high_risk = sum(1 for item in flagged if item["score"] >= 60)
    summary = (
        f"Tender quality grade {grade} — overall ambiguity score {overall}/100. "
        f"{high_risk} of {len(criteria)} criteria are high-risk (score ≥ 60). "
        + (_quality_advice(grade))
    )

    return BidderQualityReport(
        overall_score=overall,
        grade=grade,
        flagged_criteria=flagged,
        summary=summary,
    )


def _grade(score: int) -> str:
    if score <= 20:
        return "A"
    if score <= 40:
        return "B"
    if score <= 60:
        return "C"
    if score <= 80:
        return "D"
    return "F"


def _quality_advice(grade: str) -> str:
    return {
        "A": "Tender is well-drafted; minimal ambiguity detected.",
        "B": "Minor ambiguities present; recommend officer review of flagged criteria.",
        "C": "Moderate ambiguity — risk of disputes at evaluation stage.",
        "D": "High ambiguity — strongly recommend redrafting flagged criteria before publication.",
        "F": "Critical ambiguity — publication without revision is likely to cause legal challenges.",
    }.get(grade, "")


# ── Risk Signal Detection ──────────────────────────────────────────────────────

def detect_risk_signals(
    criteria: list[Criterion],
    evidence_by_bidder: dict[str, list[Evidence]],
    bidder_docs: dict[str, list[Document]],
    bidder_results: list[BidderResult],
) -> list[RiskSignal]:
    """
    Detect procurement fraud and collusion indicators across all bidder
    submissions.  Returns a list of RiskSignal objects sorted by severity.
    """
    signals: list[RiskSignal] = []
    signals.extend(_detect_similar_bids(criteria, evidence_by_bidder))
    signals.extend(_detect_document_reuse(bidder_docs))
    signals.extend(_detect_low_bid_outlier(criteria, evidence_by_bidder))
    signals.extend(_detect_universal_mandatory_failure(criteria, bidder_results))
    signals.extend(_detect_collusion_cluster(criteria, evidence_by_bidder))
    return sorted(signals, key=lambda s: {"high": 0, "medium": 1, "low": 2}[s.severity])


# ── Individual detectors ───────────────────────────────────────────────────────

def _detect_similar_bids(
    criteria: list[Criterion],
    evidence_by_bidder: dict[str, list[Evidence]],
) -> list[RiskSignal]:
    """Flag pairs of bidders whose quoted price is within 1% of each other."""
    price_ids = {c.id for c in criteria if c.comparison_rule == "price_extracted"}
    if not price_ids:
        return []

    prices: dict[str, float] = {}
    for bidder, items in evidence_by_bidder.items():
        for item in items:
            if item.criterion_id in price_ids:
                val = _to_rupees(item.value)
                if val and val > 0:
                    prices[bidder] = val
                    break

    if len(prices) < 2:
        return []

    signals: list[RiskSignal] = []
    bidders = list(prices.items())
    for i, (b1, p1) in enumerate(bidders):
        for b2, p2 in bidders[i + 1 :]:
            diff_pct = abs(p1 - p2) / max(p1, p2) * 100
            if diff_pct <= 1.0:
                signals.append(RiskSignal(
                    signal_type="similar_bids",
                    severity="high",
                    title="Suspiciously Similar Bid Values",
                    description=(
                        f"'{b1}' quoted ₹{p1:,.0f} and '{b2}' quoted ₹{p2:,.0f} — "
                        f"a difference of only {diff_pct:.2f}%. "
                        "Near-identical quotes from independent bidders are a strong collusion indicator."
                    ),
                    affected_bidders=[b1, b2],
                    evidence=f"{b1}={p1:,.0f}, {b2}={p2:,.0f}, diff={diff_pct:.2f}%",
                ))
    return signals


def _detect_document_reuse(bidder_docs: dict[str, list[Document]]) -> list[RiskSignal]:
    """Flag the same document (by SHA-256) appearing in multiple bidder submissions."""
    hash_to_bidders: dict[str, list[str]] = defaultdict(list)
    hash_to_name: dict[str, str] = {}
    for bidder, docs in bidder_docs.items():
        for doc in docs:
            if doc.checksum_sha256:
                hash_to_bidders[doc.checksum_sha256].append(bidder)
                hash_to_name[doc.checksum_sha256] = doc.name

    signals: list[RiskSignal] = []
    for sha, bidders in hash_to_bidders.items():
        unique_bidders = sorted(set(bidders))
        if len(unique_bidders) >= 2:
            signals.append(RiskSignal(
                signal_type="document_reuse",
                severity="high",
                title="Identical Document Submitted by Multiple Bidders",
                description=(
                    f"File '{hash_to_name[sha]}' (SHA-256: {sha[:16]}…) was submitted "
                    f"by {len(unique_bidders)} bidders: {', '.join(unique_bidders)}. "
                    "Shared source documents suggest coordination or a common drafter."
                ),
                affected_bidders=unique_bidders,
                evidence=f"sha256={sha[:16]}…, file={hash_to_name[sha]}",
            ))
    return signals


def _detect_low_bid_outlier(
    criteria: list[Criterion],
    evidence_by_bidder: dict[str, list[Evidence]],
) -> list[RiskSignal]:
    """Flag bids below 70% of the median as potential predatory/unrealistic quotes."""
    price_ids = {c.id for c in criteria if c.comparison_rule == "price_extracted"}
    if not price_ids:
        return []

    prices: dict[str, float] = {}
    for bidder, items in evidence_by_bidder.items():
        for item in items:
            if item.criterion_id in price_ids:
                val = _to_rupees(item.value)
                if val and val > 0:
                    prices[bidder] = val
                    break

    if len(prices) < 3:
        return []

    median = statistics.median(prices.values())
    threshold = median * 0.70
    signals: list[RiskSignal] = []
    for bidder, price in prices.items():
        if price < threshold:
            pct = price / median * 100
            signals.append(RiskSignal(
                signal_type="low_bid_outlier",
                severity="medium",
                title="Abnormally Low Bid — Possible Predatory Quote",
                description=(
                    f"'{bidder}' quoted ₹{price:,.0f}, which is {pct:.1f}% of the median "
                    f"bid (₹{median:,.0f}). Bids below 70% of the median risk non-delivery "
                    "and should be scrutinised for hidden cost assumptions."
                ),
                affected_bidders=[bidder],
                evidence=f"quote={price:,.0f}, median={median:,.0f}, pct={pct:.1f}%",
            ))
    return signals


def _detect_universal_mandatory_failure(
    criteria: list[Criterion],
    bidder_results: list[BidderResult],
) -> list[RiskSignal]:
    """
    Flag mandatory criteria where EVERY bidder failed.
    This almost always means the tender clause is impossible or mis-drafted.
    """
    mandatory_ids = {c.id: c.description for c in criteria if c.mandatory}
    if not mandatory_ids or not bidder_results:
        return []

    evaluated = [br for br in bidder_results if br.verdicts]
    if not evaluated:
        return []

    signals: list[RiskSignal] = []
    for criterion_id, description in mandatory_ids.items():
        failed_bidders = [
            br.bidder
            for br in evaluated
            if any(v.criterion_id == criterion_id and v.status == "FAIL" for v in br.verdicts)
        ]
        if len(failed_bidders) == len(evaluated) and len(evaluated) >= 2:
            signals.append(RiskSignal(
                signal_type="universal_mandatory_failure",
                severity="medium",
                title="All Bidders Failed the Same Mandatory Criterion",
                description=(
                    f"Criterion {criterion_id} ('{description[:80]}…' if len(description) > 80 else '{description}') "
                    f"was failed by all {len(failed_bidders)} evaluated bidder(s). "
                    "This strongly suggests the criterion is mis-drafted, impossible to meet, "
                    "or the required evidence type is not standard in the industry."
                ),
                affected_bidders=failed_bidders,
                evidence=f"criterion_id={criterion_id}, all_failed={len(failed_bidders)}",
            ))
    return signals


def _detect_collusion_cluster(
    criteria: list[Criterion],
    evidence_by_bidder: dict[str, list[Evidence]],
) -> list[RiskSignal]:
    """
    Flag if 3+ bidders report the same financial turnover value for the
    mandatory financial criterion — a strong indicator of coordinated filings.
    """
    financial_ids = {c.id for c in criteria if c.category == "financial" and c.mandatory}
    if not financial_ids:
        return []

    value_to_bidders: dict[str, list[str]] = defaultdict(list)
    for bidder, items in evidence_by_bidder.items():
        for item in items:
            if item.criterion_id in financial_ids and item.value.strip():
                normalised = re.sub(r"\s+", " ", item.value.strip().lower())
                value_to_bidders[normalised].append(bidder)

    signals: list[RiskSignal] = []
    for value, bidders in value_to_bidders.items():
        unique = sorted(set(bidders))
        if len(unique) >= 3:
            signals.append(RiskSignal(
                signal_type="collusion_indicator",
                severity="high",
                title="Identical Financial Value Reported by 3+ Bidders",
                description=(
                    f"{len(unique)} bidders ({', '.join(unique)}) reported the exact same "
                    f"financial value: '{value}'. Identical financial declarations across "
                    "independent competitors are a strong collusion indicator and warrant "
                    "verification with the issuing CA / bank."
                ),
                affected_bidders=unique,
                evidence=f"value='{value}', bidders={len(unique)}",
            ))
    return signals


# ── Helpers ────────────────────────────────────────────────────────────────────

def _to_rupees(text: str) -> float | None:
    """Convert a money string to rupees (best effort)."""
    if not text:
        return None
    text = text.replace(",", "").strip()
    match = re.search(
        r"([0-9]+(?:\.[0-9]+)?)\s*(crore|cr|lakh|lac|thousand|k)?",
        text, re.IGNORECASE,
    )
    if not match:
        return None
    amount = float(match.group(1))
    unit = (match.group(2) or "").lower()
    if unit in ("crore", "cr"):
        return amount * 1e7
    if unit in ("lakh", "lac"):
        return amount * 1e5
    if unit in ("thousand", "k"):
        return amount * 1e3
    return amount
