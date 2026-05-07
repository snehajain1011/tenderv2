"""
Corrigendum / Amendment Tracker
================================
Detects changes in tender criteria between consecutive evaluation runs.

Flow:
  1. After every evaluation, `save_criteria_snapshot(workspace, criteria)` writes
     outputs/<ws>/criteria_snapshot.json.
  2. On the NEXT evaluation, `load_criteria_snapshot(workspace)` loads the previous
     snapshot before it is overwritten.
  3. `diff_criteria(previous, current)` compares the two lists and returns a
     CorrigendumReport describing what was added, removed, or modified.
  4. The report is included in the audit log and exposed via the API.

Fields compared per criterion: threshold, time_period, comparison_rule,
accepted_evidence, mandatory, description.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from schema import CorrigendumReport, CriterionChange

if TYPE_CHECKING:
    from schema import BidderResult, Criterion

logger = logging.getLogger(__name__)

_COMPARED_FIELDS = ("threshold", "time_period", "comparison_rule", "mandatory", "description")


# ── Snapshot helpers ──────────────────────────────────────────────────────────

def save_criteria_snapshot(outputs_dir: Path, criteria: list[Criterion]) -> None:
    """Persist a lightweight criteria snapshot for the next corrigendum diff."""
    snap = [
        {
            "id": c.id,
            "description": c.description,
            "threshold": c.threshold,
            "time_period": c.time_period,
            "comparison_rule": c.comparison_rule,
            "mandatory": c.mandatory,
            "accepted_evidence": list(c.accepted_evidence),
        }
        for c in criteria
    ]
    path = outputs_dir / "criteria_snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("[Corrigendum] Criteria snapshot saved (%d criteria) → %s", len(criteria), path)


def load_criteria_snapshot(outputs_dir: Path) -> list[dict] | None:
    """Load the previous criteria snapshot, or None if this is the first run."""
    path = outputs_dir / "criteria_snapshot.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[Corrigendum] Could not load snapshot: %s", exc)
        return None


# ── Diff engine ───────────────────────────────────────────────────────────────

def diff_criteria(
    previous: list[dict],
    current: list[Criterion],
    bidder_results: list[BidderResult] | None = None,
) -> CorrigendumReport | None:
    """
    Compare previous snapshot dicts against the current Criterion objects.
    Returns None when no changes are detected.
    """
    prev_by_id: dict[str, dict] = {c["id"]: c for c in previous}
    curr_by_id: dict[str, dict] = {
        c.id: {
            "id": c.id,
            "description": c.description,
            "threshold": c.threshold,
            "time_period": c.time_period,
            "comparison_rule": c.comparison_rule,
            "mandatory": c.mandatory,
            "accepted_evidence": list(c.accepted_evidence),
        }
        for c in current
    }

    added: list[CriterionChange] = []
    removed: list[CriterionChange] = []
    modified: list[CriterionChange] = []

    # Added criteria
    for cid, cdata in curr_by_id.items():
        if cid not in prev_by_id:
            added.append(CriterionChange(
                criterion_id=cid,
                change_type="added",
                description=cdata["description"],
            ))

    # Removed criteria
    for cid, pdata in prev_by_id.items():
        if cid not in curr_by_id:
            removed.append(CriterionChange(
                criterion_id=cid,
                change_type="removed",
                description=pdata["description"],
            ))

    # Modified criteria
    for cid in set(prev_by_id) & set(curr_by_id):
        pdata = prev_by_id[cid]
        cdata = curr_by_id[cid]
        for field in _COMPARED_FIELDS:
            old_val = str(pdata.get(field, ""))
            new_val = str(cdata.get(field, ""))
            if old_val != new_val:
                modified.append(CriterionChange(
                    criterion_id=cid,
                    change_type="modified",
                    description=cdata["description"],
                    field=field,
                    old_value=old_val,
                    new_value=new_val,
                ))

    if not (added or removed or modified):
        logger.info("[Corrigendum] No criteria changes detected — tender unchanged.")
        return None

    # Identify affected bidders (those whose verdicts touched a changed criterion)
    changed_ids = {c.criterion_id for c in [*added, *removed, *modified]}
    affected: list[str] = []
    if bidder_results:
        for br in bidder_results:
            for v in br.verdicts:
                if v.criterion_id in changed_ids:
                    affected.append(br.bidder)
                    break

    requires_reeval = bool(removed or modified)
    total = len(added) + len(removed) + len(modified)
    parts = []
    if added:
        parts.append(f"{len(added)} criterion/criteria added")
    if removed:
        parts.append(f"{len(removed)} removed")
    if modified:
        parts.append(f"{len(modified)} modified")
    summary = (
        f"Corrigendum detected — {total} change(s): {', '.join(parts)}. "
        + (f"{len(affected)} bidder(s) affected." if affected else "No bidders affected.")
        + (" Full re-evaluation recommended." if requires_reeval else "")
    )

    logger.warning("[Corrigendum] %s", summary)

    return CorrigendumReport(
        tender_id="",
        detected_at=datetime.now(timezone.utc).isoformat(),
        added=added,
        removed=removed,
        modified=modified,
        affected_bidders=sorted(set(affected)),
        requires_full_reeval=requires_reeval,
        summary=summary,
    )
