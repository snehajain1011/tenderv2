"""
Explainable Rejection Report Generator
=======================================
Generates a self-contained, print-ready HTML report for a single bidder.
Includes GSTIN pre-check result, failed / review criteria with full evidence
citations, missing documents, and review tasks.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from schema import BidderResult, Criterion, EvaluationResult


_STATUS_COLOUR = {
    "PASS": ("#166534", "#dcfce7", "✔ PASS"),
    "FAIL": ("#991b1b", "#fee2e2", "✗ FAIL"),
    "NEED_MANUAL_REVIEW": ("#92400e", "#fef3c7", "⚠ REVIEW"),
    "Not Eligible": ("#991b1b", "#fee2e2", "✗ Not Eligible"),
    "Eligible": ("#166534", "#dcfce7", "✔ Eligible"),
    "Need Manual Review": ("#92400e", "#fef3c7", "⚠ Manual Review"),
}

_GSTIN_STATUS_COLOUR = {
    "clear":     ("#166534", "#dcfce7"),
    "not_found": ("#92400e", "#fef3c7"),
    "invalid":   ("#991b1b", "#fee2e2"),
    "flagged":   ("#7f1d1d", "#fee2e2"),
}


def generate_rejection_html(
    bidder_result: BidderResult,
    evaluation: EvaluationResult,
) -> str:
    """Return a standalone UTF-8 HTML string for the bidder's adjudication report."""
    criteria_by_id = {c.id: c for c in evaluation.criteria}
    now = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    bidder = bidder_result.bidder
    overall = bidder_result.overall_status

    colour, bg, label = _STATUS_COLOUR.get(overall, ("#374151", "#e5e7eb", overall))

    gstin_check = bidder_result.gstin_check
    gstin_section = _gstin_section(gstin_check)

    verdict_rows = _verdict_rows(bidder_result, criteria_by_id)
    review_rows  = _review_rows(bidder_result)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Adjudication Report — {html.escape(bidder)}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px;
         color: #1f2937; background: #f9fafb; padding: 32px; }}
  .page {{ max-width: 960px; margin: 0 auto; background: #fff;
           border: 1px solid #e5e7eb; border-radius: 8px; padding: 40px; }}
  .header {{ border-bottom: 2px solid #1e3a5f; padding-bottom: 18px; margin-bottom: 28px; }}
  .header h1 {{ font-size: 22px; color: #1e3a5f; }}
  .header p {{ color: #6b7280; margin-top: 4px; font-size: 12px; }}
  .badge {{ display: inline-block; padding: 4px 14px; border-radius: 999px;
            font-weight: 700; font-size: 13px; }}
  .summary-grid {{ display: grid; grid-template-columns: repeat(3, 1fr);
                   gap: 14px; margin-bottom: 28px; }}
  .summary-card {{ border: 1px solid #e5e7eb; border-radius: 6px; padding: 14px; }}
  .summary-card .label {{ font-size: 11px; font-weight: 700; text-transform: uppercase;
                          color: #6b7280; }}
  .summary-card .value {{ font-size: 20px; font-weight: 700; margin-top: 4px; }}
  section {{ margin-bottom: 28px; }}
  section h2 {{ font-size: 15px; font-weight: 700; color: #1e3a5f;
               border-left: 4px solid #1e3a5f; padding-left: 10px; margin-bottom: 14px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  th {{ background: #1e3a5f; color: #fff; text-align: left; padding: 8px 10px;
        font-size: 11px; font-weight: 700; text-transform: uppercase; }}
  td {{ padding: 8px 10px; vertical-align: top; border-bottom: 1px solid #f3f4f6; }}
  tr:nth-child(even) td {{ background: #f9fafb; }}
  .gstin-box {{ border-radius: 6px; padding: 14px 18px; margin-bottom: 28px;
               border: 1px solid; }}
  .gstin-box .title {{ font-weight: 700; font-size: 14px; margin-bottom: 4px; }}
  .gstin-box .reason {{ font-size: 12px; margin-top: 6px; }}
  .chip {{ display: inline-block; padding: 2px 8px; border-radius: 4px;
           font-size: 11px; font-weight: 700; }}
  .footer {{ margin-top: 36px; border-top: 1px solid #e5e7eb; padding-top: 16px;
             color: #9ca3af; font-size: 11px; }}
  @media print {{
    body {{ background: #fff; padding: 0; }}
    .page {{ border: none; box-shadow: none; padding: 20px; }}
    .no-print {{ display: none; }}
  }}
</style>
</head>
<body>
<div class="page">

  <div class="header">
    <h1>Procurement Adjudication Report</h1>
    <p>Tender: <strong>{html.escape(evaluation.tender_id)}</strong>
       &nbsp;·&nbsp; Bidder: <strong>{html.escape(bidder)}</strong>
       &nbsp;·&nbsp; Generated: {now}</p>
  </div>

  <div class="summary-grid">
    <div class="summary-card">
      <div class="label">Overall Decision</div>
      <div class="value">
        <span class="badge" style="color:{colour};background:{bg}">{label}</span>
      </div>
    </div>
    <div class="summary-card">
      <div class="label">Criteria Evaluated</div>
      <div class="value">{len(bidder_result.verdicts)}</div>
    </div>
    <div class="summary-card">
      <div class="label">Failed / Review</div>
      <div class="value" style="color:#991b1b">
        {sum(1 for v in bidder_result.verdicts if v.status in ("FAIL","NEED_MANUAL_REVIEW"))}
      </div>
    </div>
  </div>

  {gstin_section}

  <section>
    <h2>Criteria Evaluation Detail</h2>
    {verdict_rows}
  </section>

  {review_rows}

  <div class="footer">
    <p>This report was generated automatically by Procurement AI and contains
       source-grounded evidence citations for every decision. All verdicts are
       deterministic and traceable. For disputes or RTI requests, refer to the
       full audit log and agent outputs in the workspace reports.</p>
    <p style="margin-top:6px">Tender ID: {html.escape(evaluation.tender_id)}
       &nbsp;·&nbsp; Bidder: {html.escape(bidder)}
       &nbsp;·&nbsp; {now}</p>
  </div>

</div>
</body>
</html>"""


def _gstin_section(gstin_check) -> str:
    if gstin_check is None:
        return ""

    status = gstin_check.check_status
    fg, bg = _GSTIN_STATUS_COLOUR.get(status, ("#374151", "#e5e7eb"))

    label_map = {
        "clear":     "✔ GSTIN Valid and Active",
        "not_found": "⚠ No GSTIN Found in Documents",
        "invalid":   "✗ GSTIN Invalid or Inactive — Bid Blocked",
        "flagged":   "✗ Vendor Flagged in Procurement Records — Bid Blocked",
    }
    label = label_map.get(status, status.upper())

    gstin_display = (
        f"<strong>GSTIN:</strong> {html.escape(gstin_check.gstin)}&nbsp;&nbsp;"
        if gstin_check.gstin else ""
    )
    legal_display = (
        f"<strong>Legal Name:</strong> {html.escape(gstin_check.legal_name)}"
        if gstin_check.legal_name else ""
    )
    reason_block = ""
    if gstin_check.rejection_reason:
        reason_block = f'<div class="reason">{html.escape(gstin_check.rejection_reason)}</div>'

    return f"""
<div class="gstin-box" style="color:{fg};background:{bg};border-color:{fg}40">
  <div class="title">{label}</div>
  <div style="font-size:12px;margin-top:4px">{gstin_display}{legal_display}</div>
  {reason_block}
</div>"""


def _verdict_rows(bidder_result: BidderResult, criteria_by_id: dict) -> str:
    if not bidder_result.verdicts:
        return "<p style='color:#6b7280'>No criteria were evaluated for this bidder.</p>"

    rows = []
    for verdict in bidder_result.verdicts:
        colour, bg, label = _STATUS_COLOUR.get(verdict.status, ("#374151", "#e5e7eb", verdict.status))
        criterion = criteria_by_id.get(verdict.criterion_id)
        mandatory = "Mandatory" if (criterion and criterion.mandatory) else "Optional"
        tender_src = (
            f"{html.escape(verdict.tender_source.document or '—')}"
            f"{f', p.{verdict.tender_source.page}' if verdict.tender_source.page else ''}"
        )
        bidder_src = (
            f"{html.escape(verdict.bidder_source.document or '—')}"
            f"{f', p.{verdict.bidder_source.page}' if verdict.bidder_source.page else ''}"
        )
        rows.append(f"""
<tr>
  <td><strong>{html.escape(verdict.criterion_id)}</strong><br>
      <span style="color:#6b7280;font-size:11px">{mandatory}</span></td>
  <td style="max-width:220px">{html.escape(verdict.criterion[:120])}</td>
  <td><span class="chip" style="color:{colour};background:{bg}">{label}</span></td>
  <td style="color:#374151">{html.escape(verdict.extracted_value or '—')}</td>
  <td style="color:#6b7280">{tender_src}</td>
  <td style="color:#6b7280">{bidder_src}</td>
  <td style="max-width:260px;color:#374151">{html.escape(verdict.reason)}</td>
</tr>""")
        if verdict.rule_trace and verdict.status != "PASS":
            rows.append(f"""
<tr style="background:#fafbfc">
  <td colspan="2" style="color:#6b7280;font-size:11px;padding-left:20px">Rule trace</td>
  <td colspan="5" style="color:#374151;font-size:11px">{html.escape(verdict.rule_trace)}</td>
</tr>""")
        if verdict.suggested_action and verdict.status != "PASS":
            rows.append(f"""
<tr style="background:#fffbf0">
  <td colspan="2" style="color:#92400e;font-size:11px;padding-left:20px">Suggested action</td>
  <td colspan="5" style="color:#92400e;font-size:11px">{html.escape(verdict.suggested_action)}</td>
</tr>""")

    return f"""<table>
<thead><tr>
  <th>ID</th><th>Criterion</th><th>Status</th>
  <th>Extracted Value</th><th>Tender Source</th>
  <th>Bidder Source</th><th>Reason</th>
</tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>"""


def _review_rows(bidder_result: BidderResult) -> str:
    tasks = bidder_result.review_tasks
    if not tasks:
        return ""

    rows = []
    for task in tasks:
        rows.append(f"""
<tr>
  <td>{html.escape(task.criterion_id)}</td>
  <td>{html.escape(task.issue_type.replace("_", " ").title())}</td>
  <td>{html.escape(task.reason)}</td>
  <td style="color:#d97706">{html.escape(task.suggested_action)}</td>
</tr>""")

    return f"""<section>
  <h2>Manual Review Tasks ({len(tasks)})</h2>
  <table>
    <thead><tr>
      <th>Criterion</th><th>Issue Type</th>
      <th>Reason</th><th>Suggested Action</th>
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</section>"""
