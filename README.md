# Procurement AI Platform Prototype

Production-shaped, local-first procurement workflow prototype for tender lifecycle automation. It supports explicit tender workspaces, multi-stage procurement agents, RAG accuracy checkpoints, model switching, explainable bidder verdicts, manual-review escalation, and audit-ready reports.

The system does **not** silently evaluate bundled sample data. Use `--demo` for representative sandbox data, or pass a real workspace with tender and bidder documents.

## Quick Start

Use these steps from PowerShell on Windows.

### 1. Open the project

```powershell
cd "C:\Users\jain4\OneDrive\Documents\New project 2"
```

### 2. Create and activate a Python environment

Using Anaconda:

```powershell
conda create -n procurement-ai python=3.13 -y
conda activate procurement-ai
```

Or using built-in Python venv:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install backend dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

This installs:

- FastAPI backend dependencies
- PDF parser support through PyMuPDF
- image OCR through RapidOCR
- SQLite local persistence support
- optional PostgreSQL driver through `psycopg`

### 4. Install frontend dependencies

```powershell
cd frontend
npm install
cd ..
```

Node `20.19+` or `22.12+` is recommended. The app may still build on Node `20.18`, but Vite prints a warning.

### 5. Run backend API

Open one PowerShell terminal:

```powershell
cd "C:\Users\jain4\OneDrive\Documents\New project 2"
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Check:

```text
http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok"}
```

### 6. Run React portal

Open a second PowerShell terminal:

```powershell
cd "C:\Users\jain4\OneDrive\Documents\New project 2\frontend"
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

## Manual UI Flow

### Option A: Run sandbox demo

1. Open the portal at `http://127.0.0.1:5173`.
2. Keep workspace as `demo`.
3. Click **Demo**.
4. Click **Evaluate**.
5. Open these tabs:
   - **Bid Review** for criterion-level verdicts
   - **Award** for L1 recommendation and rejection/non-selection reasons
   - **Reports** for Markdown, JSON, agent outputs, and audit exports

### Option B: Run your own tender workspace

1. Enter a workspace name, for example `new`.
2. Click **Create**.
3. Go to **Pre-Tender**.
4. Upload tender PDF/DOCX/image files.
5. Go to **Vendor Submission**.
6. Enter vendor name.
7. Upload that vendor's bid documents.
8. Repeat vendor upload for all bidders.
9. Click **Evaluate**.
10. Review:
    - **Bid Review**: technical, financial, compliance, document verdicts
    - **Award**: selected bidder and reasons for every other bidder
    - **Reports**: generated report and audit files

## CLI Flow

Create demo data and evaluate:

```powershell
python main.py --demo
```

Evaluate a workspace:

```powershell
python main.py --workspace "workspaces\new" --outputs-dir "outputs\new"
```

Run with local LLM extraction if Ollama is installed and the model is available:

```powershell
ollama pull qwen3:8b
python main.py --workspace "workspaces\new" --outputs-dir "outputs\new" --use-llm
```

The deterministic rule engine still makes final verdicts. LLM output cannot silently reject a bidder.

## Non-Negotiables Implemented

- Every verdict includes criterion text, tender source, bidder source, extracted value, confidence, rule trace, and reason.
- Ambiguous, missing, conflicting, or low-confidence evidence becomes `NEED_MANUAL_REVIEW`.
- Scanned/photo support is represented through parser/OCR confidence and review tasks; optional OCR dependencies can be installed.
- Audit logs record ingestion checkpoints, chunking/indexing checks, RAG retrieval checks, grounded extraction checks, rule evaluation, and the final accuracy gate.
- Round 1 runs on public/representative data only; real bid data is not required.

## Edge-Case Handling

The backend records typed diagnostics for difficult procurement documents:

- scanned PDFs with no embedded text are rendered page-by-page and passed through OCR
- photographs/images use RapidOCR first, with optional Tesseract fallback
- each parsed document stores `document_quality_json` with OCR confidence, text density, resolution, empty pages, table hints, and quality flags
- missing evidence, ambiguous values, conflicting evidence, unsupported formats, and low OCR confidence are separated into explicit issue types
- criteria can carry `criteria_risk_flags` for vague thresholds, missing time periods, subjective clauses, unverifiable claims, corrigendum sensitivity, and ambiguous tender language
- review tasks include issue type, source, extracted value if any, confidence, reason, and suggested officer action
- reports show issue type and suggested action for every `FAIL` or `NEED_MANUAL_REVIEW` verdict

## Workspace Layout

```text
my_workspace/
  tender_documents/
    tender.pdf
    corrigendum.pdf
    technical_specs.docx
  bidder_submissions/
    bidder_a/
      turnover_certificate.pdf
      gst_certificate.jpg
      technical_bid.pdf
    bidder_b/
      bid_documents.pdf
```

All files under `tender_documents/` are treated as one tender package. Each folder under `bidder_submissions/` is treated as one bidder.

Uploaded files are stored on disk during local development:

```text
workspaces/<workspace-name>/tender_documents/
workspaces/<workspace-name>/bidder_submissions/<vendor-name>/
```

Do not use the `demo` workspace for real testing unless you intentionally want the sample sandbox data mixed in. Use a new workspace name for real tender uploads.

## Run The Demo

```powershell
cd "C:\Users\jain4\OneDrive\Documents\New project 2"
python main.py --demo
```

Outputs:

- `outputs/evaluation_report.md`
- `outputs/evaluation_report.json`
- `outputs/agent_outputs.json`
- `outputs/audit_log.jsonl`

## Run With Your Documents

```powershell
python main.py --workspace "path\to\my_workspace"
```

The command fails if the workspace is missing or does not contain `tender_documents/` and `bidder_submissions/`. This prevents accidental mock output.

## Model Switching

Models are configured in `models.yaml`:

```yaml
models:
  reasoning:
    provider: ollama
    model: qwen3:8b
    endpoint: http://localhost:11434
  vision:
    provider: ollama
    model: qwen2.5vl:7b
    endpoint: http://localhost:11434
  embeddings:
    provider: local
    model: term-frequency
```

Run with the configured local LLM:

```powershell
ollama pull qwen3:8b
python main.py --demo --use-llm
```

The final verdict engine remains deterministic. The model helps extraction and explanation; it cannot silently reject a bidder.

## Optional API

Install optional API dependencies:

```powershell
python -m pip install fastapi uvicorn
```

Run:

```powershell
python -m uvicorn api:app --reload
```

Useful endpoints:

- `GET /health`
- `GET /agents`
- `GET /workspaces`
- `GET /workspaces/{workspace_name}/documents`
- `GET /workspaces/{workspace_name}/dashboard`
- `GET /workspaces/{workspace_name}/persistence`
- `POST /workspaces/demo`
- `POST /workspaces/{workspace_name}`
- `POST /workspaces/{workspace_name}/tender-documents`
- `POST /workspaces/{workspace_name}/vendors/{vendor_name}/documents`
- `POST /workspaces/{workspace_name}/evaluate`

## React Vendor/Officer Portal

Install frontend dependencies:

```powershell
cd frontend
npm install
```

Start the backend in one terminal:

```powershell
cd "C:\Users\jain4\OneDrive\Documents\New project 2"
python -m uvicorn api:app --host 127.0.0.1 --port 8000 --reload
```

Start the React portal in another terminal:

```powershell
cd "C:\Users\jain4\OneDrive\Documents\New project 2\frontend"
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

Portal capabilities:

- Officer portal: create workspace, create demo workspace, upload tender documents, run evaluation, view KPIs, verdict matrix, review tasks, and final accuracy gate.
- Vendor portal: enter vendor name and upload bidder submission documents into the selected workspace.
- Pre-tender workflow: prepare tender package, import public tender URLs, upload documents, and track publication readiness.
- Bid review workflow: collect bids, compare technical/financial/vendor qualification status, coordinate review/POC, and prepare award.
- Reports: preview generated Markdown report and open JSON/audit exports.

## Where Data Is Stored

Local development uses the filesystem, not a database, for uploaded documents:

```text
workspaces/<workspace-name>/tender_documents/
workspaces/<workspace-name>/bidder_submissions/<vendor-name>/
```

For example, if the workspace is `new`, the uploaded tender is stored under:

```text
workspaces/new/tender_documents/
```

Bidder files are stored under:

```text
workspaces/new/bidder_submissions/<vendor-name>/
```

Evaluation outputs are generated only after pressing **Evaluate** or running the CLI:

```text
outputs/<workspace-name>/evaluation_report.md
outputs/<workspace-name>/evaluation_report.json
outputs/<workspace-name>/agent_outputs.json
outputs/<workspace-name>/audit_log.jsonl
```

The same evaluation run is also persisted into a database. By default, local development uses SQLite:

```text
outputs/procurement.sqlite
```

For PostgreSQL, set `DATABASE_URL` before running the API or CLI:

```powershell
$env:DATABASE_URL="postgresql://procurement:procurement@localhost:5432/procurement"
python main.py --workspace "workspaces\new" --outputs-dir "outputs\new"
```

Persisted tables include:

- `tenders`
- `tender_documents`
- `vendors`
- `submissions`
- `bid_documents`
- `document_chunks`
- `criteria`
- `evidence`
- `verdicts`
- `review_tasks`
- `bidder_results`
- `awards`
- `contracts`
- `agent_outputs`
- `audit_events`

Check persistence for a workspace through the API:

```text
GET /workspaces/{workspace-name}/persistence
```

The pre-tender checklist shown in the UI is currently derived from the workspace files through `GET /workspaces/{workspace}/procurement-flow`. It is not manually stored as a separate record in local mode. In the production scaffold, these fields map to the PostgreSQL entities in `db/schema.sql`.

`agent_outputs.json` is the local prototype's consolidated trace of stage outputs:

- pre-tender package readiness and extracted criteria summary
- tender-stage criteria, bidder matrix, review tasks, and selection reasons
- post-tender award recommendation pack and audit export summary
- audit events emitted by parsing, RAG, extraction, and rule evaluation checkpoints

Per-agent outputs are also written after each evaluation:

```text
outputs/<workspace-name>/agent_outputs/manifest.json
outputs/<workspace-name>/agent_outputs/pre_tender__requirement_structuring_agent.json
outputs/<workspace-name>/agent_outputs/pre_tender__tender_drafting_agent.json
outputs/<workspace-name>/agent_outputs/pre_tender__compliance_policy_agent.json
outputs/<workspace-name>/agent_outputs/pre_tender__risk_review_agent.json
outputs/<workspace-name>/agent_outputs/pre_tender__publication_agent.json
outputs/<workspace-name>/agent_outputs/tender__vendor_registration_agent.json
outputs/<workspace-name>/agent_outputs/tender__submission_intake_agent.json
outputs/<workspace-name>/agent_outputs/tender__document_understanding_agent.json
outputs/<workspace-name>/agent_outputs/tender__rag_retrieval_agent.json
outputs/<workspace-name>/agent_outputs/tender__criteria_extraction_agent.json
outputs/<workspace-name>/agent_outputs/tender__evidence_mapping_agent.json
outputs/<workspace-name>/agent_outputs/tender__responsiveness_agent.json
outputs/<workspace-name>/agent_outputs/tender__technical_evaluation_agent.json
outputs/<workspace-name>/agent_outputs/tender__financial_evaluation_agent.json
outputs/<workspace-name>/agent_outputs/tender__human_review_agent.json
outputs/<workspace-name>/agent_outputs/tender__consolidated_report_agent.json
outputs/<workspace-name>/agent_outputs/post_tender__award_recommendation_agent.json
outputs/<workspace-name>/agent_outputs/post_tender__contract_generation_agent.json
outputs/<workspace-name>/agent_outputs/post_tender__contract_compliance_agent.json
outputs/<workspace-name>/agent_outputs/post_tender__vendor_performance_agent.json
outputs/<workspace-name>/agent_outputs/post_tender__audit___rti_support_agent.json
```

`manifest.json` is the index. Open it first to see every agent, its stage, and its output file.

## Current App Workflow

1. Create a workspace.
2. Upload tender documents or import a public tender URL.
3. Review the pre-tender readiness checklist.
4. Register/upload each vendor's bid documents in the Vendor Submission tab.
5. Run **Evaluate**.
6. Review criterion-level verdicts, manual-review tasks, and price comparison.
7. Open the Award tab for L1 recommendation and source-backed reasons for every non-selected bidder.
8. Open Reports for Markdown, JSON, agent outputs, and audit log exports.

Build the frontend:

```powershell
cd frontend
npm run build
```

## Optional OCR/PDF Parsing

```powershell
python -m pip install pymupdf pillow rapidocr-onnxruntime
```

Image OCR uses RapidOCR by default, which is installed from Python packages and does not require the external Tesseract executable.

Optional Tesseract fallback:

```powershell
python -m pip install pytesseract
```

If you want Tesseract fallback to work, install the Tesseract executable separately and make sure it is available on `PATH`.

Optional Docling parser:

```powershell
python -m pip install docling
```

## Persistence Setup

The project always keeps original uploaded files on disk, and after evaluation it also persists structured data into a database.

Default local persistence:

```text
outputs/procurement.sqlite
```

This SQLite database is created automatically. No setup is required.

To inspect it from Python:

```powershell
python - <<'PY'
import sqlite3
conn = sqlite3.connect("outputs/procurement.sqlite")
for table in ["tenders", "submissions", "criteria", "evidence", "verdicts", "review_tasks", "agent_outputs", "audit_events"]:
    print(table, conn.execute(f"select count(*) from {table}").fetchone()[0])
conn.close()
PY
```

PowerShell does not support bash-style heredocs. If the command above fails in PowerShell, use:

```powershell
@'
import sqlite3
conn = sqlite3.connect("outputs/procurement.sqlite")
for table in ["tenders", "submissions", "criteria", "evidence", "verdicts", "review_tasks", "agent_outputs", "audit_events"]:
    print(table, conn.execute(f"select count(*) from {table}").fetchone()[0])
conn.close()
'@ | python -
```

Check persistence through API:

```text
http://127.0.0.1:8000/workspaces/new/persistence
```

### PostgreSQL Mode

Start PostgreSQL manually or through Docker Compose, then set:

```powershell
$env:DATABASE_URL="postgresql://procurement:procurement@localhost:5432/procurement"
```

Run evaluation again:

```powershell
python main.py --workspace "workspaces\new" --outputs-dir "outputs\new"
```

When `DATABASE_URL` is set, the app writes to PostgreSQL instead of SQLite.

The PostgreSQL schema is in:

```text
db/schema.sql
```

## Docker Compose

The repository includes a production-style local stack:

```powershell
docker compose up --build
```

Services:

- API
- frontend
- PostgreSQL with pgvector
- Redis
- MinIO
- worker placeholder

The Python/React local flow works without Docker. Docker is mainly for showing the production architecture shape.

## Output Files

After evaluation, workspace outputs are written to:

```text
outputs/<workspace-name>/
```

Important files:

```text
evaluation_report.md
evaluation_report.json
agent_outputs.json
audit_log.jsonl
agent_outputs/manifest.json
agent_outputs/<stage>__<agent_name>.json
```

Use:

```text
outputs/<workspace-name>/agent_outputs/manifest.json
```

to find every per-agent output file.

## Troubleshooting

### `PDF parser failed: No module named 'fitz'`

Install PyMuPDF:

```powershell
python -m pip install pymupdf
```

### Image OCR gives low confidence

Install RapidOCR:

```powershell
python -m pip install rapidocr-onnxruntime pillow
```

Then rerun evaluation. If OCR succeeds but verdicts still show manual review, the image likely does not contain all required evidence for that criterion.

### Frontend cannot reach backend

Make sure backend is running:

```powershell
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Then refresh:

```text
http://127.0.0.1:5173
```

### `Report not generated yet`

Click **Evaluate** in the UI, or run:

```powershell
python main.py --workspace "workspaces\new" --outputs-dir "outputs\new"
```

### Node/Vite warning

If Vite warns about Node version, install Node `20.19+` or `22.12+`.

### Postgres not used

Check whether `DATABASE_URL` is set in the same terminal where you run the API/CLI:

```powershell
echo $env:DATABASE_URL
```

If it is empty, the app uses SQLite at:

```text
outputs/procurement.sqlite
```

## Agent Workflow

Pre-tender:
- Requirement Structuring Agent
- Tender Drafting Agent
- Compliance Policy Agent
- Risk Review Agent
- Publication Agent

Tender:
- Vendor Registration Agent
- Submission Intake Agent
- Document Understanding Agent
- RAG Retrieval Agent
- Criteria Extraction Agent
- Evidence Mapping Agent
- Responsiveness Agent
- Technical Evaluation Agent
- Financial Evaluation Agent
- Human Review Agent
- Consolidated Report Agent

Post-tender:
- Award Recommendation Agent
- Contract Generation Agent
- Contract Compliance Agent
- Vendor Performance Agent
- Audit & RTI Support Agent

## Tests

```powershell
python -m pip install pytest
python -m pytest -q
```

The tests verify demo verdicts, source-backed explanations, final accuracy gate behavior, and report/audit generation.

## Production Architecture Scaffold

The repo includes production deployment scaffolding:

- `docker-compose.yml`: API, frontend, PostgreSQL/pgvector, Redis, MinIO, and worker services.
- `db/schema.sql`: procurement domain schema for tenders, vendors, submissions, documents, chunks, criteria, evidence, verdicts, review tasks, awards, contracts, and audit events.
- `storage.py`: local storage adapter and MinIO/S3 extension point.
- `worker.py`: background job entry point for parser/evaluation queue wiring.

Run the production-like stack:

```powershell
docker compose up --build
```

The local Python/React flow still works without Docker. Docker is for the production-style architecture with Postgres, Redis, and MinIO.

## Render Backend Deployment

The repo includes `render.yaml` for deploying the FastAPI backend as a Render web service.

Render settings:

```text
Service name: tenderv2-api
Runtime: Python
Plan: free
Build command: pip install -r requirements.txt
Start command: uvicorn api:app --host 0.0.0.0 --port $PORT
Health check: /health
```

The free/basic setup uses Render's ephemeral filesystem. Uploaded tender/bid files and generated reports can disappear on restart or redeploy, which is acceptable for demo use. Structured data falls back to SQLite at `outputs/procurement.sqlite` unless `DATABASE_URL` is provided.

After Render creates the backend, set the Vercel frontend environment variable:

```text
VITE_API_URL=https://<your-render-service>.onrender.com
```

Then redeploy the Vercel frontend so the portal calls the hosted Render API instead of local `127.0.0.1`.
