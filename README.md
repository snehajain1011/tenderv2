# Open-Source Tender Evaluation Prototype

Local CLI prototype for AI-assisted tender eligibility evaluation. It parses a tender, reads mock bidder submissions, extracts criterion-level evidence, evaluates each bidder as `PASS`, `FAIL`, or `REVIEW`, and writes auditable reports.

The default path runs without cloud credentials or paid APIs. It uses deterministic extraction for the included mock data and can optionally call a local Ollama-compatible model such as `qwen3:8b`.

## Quick Start

```powershell
python main.py
```

Outputs are written to:

- `outputs/evaluation_report.md`
- `outputs/evaluation_report.json`
- `outputs/audit_log.jsonl`

## Setup And Run

1. Open the project folder:

```powershell
cd "C:\Users\jain4\OneDrive\Documents\New project 2"
```

2. Check Python is available:

```powershell
python --version
```

Python 3.10 or newer is recommended. The prototype was verified with Python 3.13.

3. Optional: create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

4. Install optional dependencies if you want PDF/image parsing support:

```powershell
python -m pip install -r requirements.txt
```

The included mock demo uses text files and runs with the Python standard library only.

5. Run the prototype:

```powershell
python main.py
```

6. View the generated outputs:

```powershell
Get-Content outputs\evaluation_report.md
Get-Content outputs\evaluation_report.json
Get-Content outputs\audit_log.jsonl
```

7. Run tests:

```powershell
python -m pytest -q
```

If `pytest` is not installed:

```powershell
python -m pip install pytest
python -m pytest -q
```

## Project Structure

- `main.py`: CLI entrypoint.
- `document_loader.py`: loads tender and bidder documents.
- `evaluator.py`: extracts criteria/evidence and applies deterministic verdict logic.
- `schema.py`: typed data structures for criteria, evidence, verdicts, reports, and audit events.
- `report.py`: writes Markdown, JSON, and JSONL audit outputs.
- `llm_client.py`: optional Ollama-compatible local LLM client.
- `data/tender/`: sample CRPF-style tender excerpt.
- `data/bidders/`: four mock bidder submissions.
- `outputs/`: generated evaluation reports.

## Optional Local LLM

Install and run Ollama, then pull Qwen:

```powershell
ollama pull qwen3:8b
$env:TENDER_USE_LLM="1"
python main.py --use-llm
```

The prototype still uses deterministic checks for final verdicts. The model is used for structured extraction and explanations, not silent disqualification.

## Design Constraints

- No GCP, Google ADK, or hardcoded claim APIs.
- No silent rejection. Uncertain, missing, low-confidence, or conflicting evidence becomes `REVIEW`.
- Every verdict includes criterion, document, value, and reason.
- Scanned/photo support is represented through OCR confidence. If OCR is unavailable or confidence is low, the bidder is routed to manual review.
