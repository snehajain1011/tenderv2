CRITERIA_EXTRACTION_PROMPT = """
Extract tender eligibility criteria as strict JSON.

Return:
{
  "criteria": [
    {
      "id": "C1",
      "category": "financial|technical|compliance|document",
      "mandatory": true,
      "description": "...",
      "threshold": "...",
      "time_period": "...",
      "comparison_rule": "minimum|present|valid|count_at_least",
      "accepted_evidence": ["..."]
    }
  ]
}

Rules:
- Use only the tender text.
- Mark uncertain requirements as mandatory only if the text clearly makes them required.
- Do not invent criteria.

Tender text:
{tender_text}
"""


EVIDENCE_EXTRACTION_PROMPT = """
Extract bidder evidence for the given criteria as strict JSON.

Return:
{
  "evidence": [
    {
      "criterion_id": "C1",
      "document": "filename",
      "value": "exact extracted value",
      "excerpt": "short source excerpt",
      "confidence": 0.0,
      "notes": ""
    }
  ]
}

Rules:
- Use only bidder documents.
- If evidence is missing, return an empty value with confidence 0.
- Do not decide eligibility here.

Criteria:
{criteria_json}

Bidder documents:
{documents_text}
"""

