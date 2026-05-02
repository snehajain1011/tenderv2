from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


CriterionCategory = Literal["financial", "technical", "compliance", "document"]
VerdictStatus = Literal["PASS", "FAIL", "REVIEW"]
OverallStatus = Literal["Eligible", "Not Eligible", "Need Manual Review"]


@dataclass(frozen=True)
class Document:
    name: str
    path: str
    text: str
    confidence: float = 1.0
    source_type: str = "text"


@dataclass(frozen=True)
class Criterion:
    id: str
    category: CriterionCategory
    mandatory: bool
    description: str
    threshold: str = ""
    time_period: str = ""
    comparison_rule: str = "present"
    accepted_evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Evidence:
    criterion_id: str
    bidder: str
    document: str
    value: str
    excerpt: str
    confidence: float
    notes: str = ""


@dataclass(frozen=True)
class Verdict:
    criterion_id: str
    status: VerdictStatus
    reason: str
    document: str
    value: str
    manual_review_reason: str = ""


@dataclass(frozen=True)
class BidderResult:
    bidder: str
    overall_status: OverallStatus
    verdicts: list[Verdict]


@dataclass(frozen=True)
class EvaluationResult:
    criteria: list[Criterion]
    bidders: list[BidderResult]


@dataclass(frozen=True)
class AuditEvent:
    step: str
    subject: str
    detail: dict[str, Any]


def to_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: to_dict(item) for key, item in value.items()}
    return value

