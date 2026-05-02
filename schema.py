from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


CriterionCategory = Literal["financial", "technical", "compliance", "document", "commercial"]
VerdictStatus = Literal["PASS", "FAIL", "NEED_MANUAL_REVIEW"]
OverallStatus = Literal["Eligible", "Not Eligible", "Need Manual Review"]
ProcurementStage = Literal["pre_tender", "tender", "post_tender"]


@dataclass(frozen=True)
class Citation:
    document: str
    page: int
    section: str
    excerpt: str
    chunk_id: str = ""


@dataclass(frozen=True)
class Document:
    document_id: str
    name: str
    path: str
    checksum_sha256: str
    text: str
    confidence: float = 1.0
    source_type: str = "text"
    page_count: int = 1
    parser: str = "text"


@dataclass(frozen=True)
class RagChunk:
    chunk_id: str
    document_id: str
    document_name: str
    text: str
    page: int
    section: str
    start: int
    end: int


@dataclass(frozen=True)
class RetrievalHit:
    chunk: RagChunk
    score: float


@dataclass(frozen=True)
class Criterion:
    id: str
    category: CriterionCategory
    mandatory: bool
    description: str
    tender_citation: Citation
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
    bidder_citation: Citation
    tender_citation: Citation
    confidence: float
    normalized_value: str = ""
    notes: str = ""


@dataclass(frozen=True)
class Verdict:
    criterion_id: str
    criterion: str
    status: VerdictStatus
    reason: str
    tender_source: Citation
    bidder_source: Citation
    extracted_value: str
    confidence: float
    rule_trace: str
    manual_review_reason: str = ""
    human_reviewer_action: str = ""


@dataclass(frozen=True)
class ReviewTask:
    task_id: str
    bidder: str
    criterion_id: str
    reason: str
    priority: str
    source: Citation


@dataclass(frozen=True)
class BidderResult:
    bidder: str
    overall_status: OverallStatus
    verdicts: list[Verdict]
    review_tasks: list[ReviewTask] = field(default_factory=list)


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    stage: ProcurementStage
    responsibility: str
    inputs: list[str]
    outputs: list[str]
    model_key: str = "reasoning"


@dataclass(frozen=True)
class EvaluationResult:
    tender_id: str
    criteria: list[Criterion]
    bidders: list[BidderResult]
    agents: list[AgentDefinition]
    final_accuracy_gate_passed: bool
    final_accuracy_issues: list[str]


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
