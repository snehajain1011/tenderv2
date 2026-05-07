# TenderAI — Smart Procurement Evaluation Platform

## What Is This?

TenderAI is an AI-powered platform that automates the most time-consuming and error-prone parts of government and corporate procurement — evaluating bids.

Today, procurement officers spend weeks manually reading through hundreds of pages of bidder documents, checking whether each vendor meets eligibility requirements, spotting fraud, and writing justification reports. This process is slow, inconsistent, and vulnerable to human error or bias.

**TenderAI does all of that automatically.** You upload the tender document and the bidders' submissions, click Evaluate, and get a complete, auditable result in minutes — with every decision explained and backed by the exact text from the documents.

---

## The Problem It Solves

| Old Way | With TenderAI |
|---|---|
| Officers read 100s of pages manually | System reads and analyses documents automatically |
| Decisions made from memory or notes | Every decision backed by exact document quotes |
| No record of why a bidder was rejected | Full audit trail — every step logged and exportable |
| Fraud and collusion hard to detect | Automatic detection of bid rigging, duplicate documents, and suspicious patterns |
| Changes to tender requirements go unnoticed | Automatic alerts when tender requirements change between rounds |
| Takes days to weeks | Takes minutes |

---

## What It Can Do — Feature by Feature

### 1. Automatic Bid Eligibility Checking
The system reads the tender document, identifies all eligibility requirements (financial turnover, years of experience, certifications, etc.), then checks every bidder's submitted documents against each requirement. It gives a clear Pass / Fail / Needs Review verdict for each criterion, with the exact sentence from the document that proves it.

### 2. GSTIN / Tax Registration Verification
Before evaluating any bid, the system checks whether the bidder's GST registration number is valid and active by calling the official GST authority database in real time. If the GSTIN is fake, inactive, or blacklisted, the bidder is rejected immediately — before a single human wastes time reading their documents. Foreign bidders without a GSTIN are flagged for manual review instead of being blocked.

### 3. Fraud & Collusion Detection
The system automatically looks for red flags across all bidders:
- **Bid rigging** — suspiciously similar prices across competing bidders
- **Duplicate documents** — the same file submitted by two different companies
- **Bid rotation patterns** — a group of vendors taking turns winning contracts
- **Shell company signals** — bidders registered at the same address
- **Price cartel behaviour** — all bids clustered abnormally close together

### 4. Explainable Rejection Reports
Every rejected bidder gets a clear, human-readable explanation of exactly why they were rejected, which requirement they failed to meet, what evidence was found (or missing), and what the officer should do. No more vague "does not meet criteria" notices.

### 5. Manual Review Escalation
When the system is not confident about something — a blurry scan, a missing date, an ambiguous clause — it does not silently make a decision. It creates a flagged Review Task for a human officer, describing exactly what needs to be checked and suggesting an action.

### 6. Amendment / Corrigendum Tracking
If the tender requirements change between evaluation rounds (a very common real-world scenario), the system automatically detects what changed — which criteria were added, removed, or modified — and shows a clear before/after comparison. Officers are alerted which bidders are affected and whether a full re-evaluation is needed.

### 7. Full Audit Trail
Every action the system takes is recorded — document uploads, parsing results, who evaluated what, which rules were applied, what the AI extracted, and what the final verdict was. This log can be exported as a file and is legally defensible for RTI (Right to Information) queries or disputes.

### 8. Vendor Directory
The system maintains a database of all vendors who have ever participated, their past evaluation results, current GSTIN status, and any fraud flags. Officers can look up any vendor's history instantly.

### 9. Award Recommendation
After evaluation, the system recommends the winning bidder (lowest qualifying bid — L1) and provides documented reasons for why every other bidder was not selected. This eliminates the most common source of procurement disputes.

### 10. Evaluation Checklist Export
One click exports a complete matrix — every bidder across every criterion — as a spreadsheet (CSV). Procurement committees can review, sign off, and file it as the official evaluation record.

### 11. Scanned Document Support
Bidders often submit scanned PDFs or photographs of documents. The system automatically reads these using OCR (optical character recognition) — it can handle printed text, typed text, and stamped documents. If a scan is too blurry to read reliably, it flags it for human review instead of guessing.

### 12. Multilingual Document Handling
Documents containing Hindi, Arabic, Chinese, and other non-English scripts are ingested and indexed correctly. The system can detect financial figures in any major currency — Rupees, Dollars, Euros, Pounds, Dirhams, and more.

### 13. Risk Intelligence Dashboard
The system scores the overall riskiness of a procurement round — how many review flags were raised, how many fraud signals were detected, and how confident the system is in its results. Officers see a risk summary at a glance.

### 14. Bidder Quality Scoring
Beyond pass/fail, the system scores how complete and clear each bidder's submission was — flagging documents that are vague, missing context, or unusually thin on evidence.

### 15. 21-Agent Governance Model
Behind the scenes, the system uses 21 specialised AI agents across three stages of procurement — pre-tender preparation, bid evaluation, and post-award compliance. Each agent handles one specific job and hands off to the next, exactly like a well-run procurement team.

---

## How to Run It

### Step 1 — Open the project folder

```powershell
cd "C:\Users\Loukik\Desktop\MAANG_Or_Equivalent\AIB\CodeAIB\tenderv2"
```

### Step 2 — Set up Python environment

Using Anaconda:
```powershell
conda create -n procurement-ai python=3.13 -y
conda activate procurement-ai
```

Or using built-in Python:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Step 3 — Install backend dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Step 4 — Install frontend dependencies

```powershell
cd frontend
npm install
cd ..
```

Node version 20.19 or newer is recommended.

### Step 5 — Set up your API key

Copy `.env.example` to `.env` and fill in your RapidAPI key:
```powershell
copy .env.example .env
```
Then open `.env` and replace `your_rapidapi_key_here` with your actual key.

### Step 6 — Start the backend

Open one terminal:
```powershell
uvicorn backend.api:app --reload
```

Check it's running by visiting: `http://127.0.0.1:8000/health` — you should see `{"status":"ok"}`

### Step 7 — Start the frontend

Open a second terminal:
```powershell
cd frontend
npm run dev
```

Open the app at: `http://127.0.0.1:5173`

---

## How to Use the App

### Option A — Try the demo (quickest)

1. Open `http://127.0.0.1:5173`
2. Leave workspace as `demo`
3. Click **Demo**, then click **Evaluate**
4. Explore the tabs:
   - **Bid Review** — see each bidder's pass/fail results per criterion
   - **Award** — see who won and why others were not selected
   - **Reports** — download the full evaluation report and audit log
   - **Amendments** — see if any tender requirements changed

### Option B — Evaluate your own documents

1. Enter a workspace name (e.g. `my_tender`)
2. Click **Create**
3. Go to **Pre-Tender** → upload your tender PDF or Word document
4. Go to **Vendor Submission** → enter a vendor name and upload their bid documents
5. Repeat for every bidder
6. Click **Evaluate**
7. Review results across the Bid Review, Award, and Reports tabs

### Option C — Run from command line

```powershell
# Demo mode
python main.py --demo

# Your own workspace
python main.py --workspace "workspaces\my_tender" --outputs-dir "outputs\my_tender"
```

---

## How to See the Amendments Feature

The Amendments tab detects changes in tender requirements between two evaluation runs.

1. **First run** — evaluate any workspace. A snapshot of the requirements is saved automatically.
2. **Change something** in the tender document — raise a financial threshold, add a new requirement, or remove one.
3. **Run evaluate again** on the same workspace.
4. The system compares the old and new requirements, shows exactly what changed, and highlights which bidders are affected.
5. An orange dot appears on the **Amendments** tab to alert you.

---

## Where Files Are Saved

**Uploaded documents:**
```
workspaces/<workspace-name>/tender_documents/
workspaces/<workspace-name>/bidder_submissions/<vendor-name>/
```

**Evaluation results:**
```
outputs/<workspace-name>/evaluation_report.md    ← Human-readable report
outputs/<workspace-name>/evaluation_report.json  ← Machine-readable data
outputs/<workspace-name>/audit_log.jsonl         ← Full audit trail
outputs/<workspace-name>/corrigendum_report.json ← Amendment changes (if any)
```

---

## Troubleshooting

**PDF not reading?**
```powershell
python -m pip install pymupdf
```

**Image / scanned document not reading?**
```powershell
python -m pip install rapidocr-onnxruntime pillow
```

**Frontend can't connect to backend?**
Make sure the backend is running (`uvicorn backend.api:app --reload`) and refresh the page.

**"Report not generated yet" message?**
Click **Evaluate** in the app, or run `python main.py --workspace ...` from the command line.

---

## Technology Used (for technical reviewers)

- **Backend:** Python, FastAPI
- **Frontend:** React 19, Vite
- **Document parsing:** PyMuPDF (PDF), python-docx (Word), RapidOCR + Tesseract (scanned images)
- **Search & retrieval:** TF-IDF cosine similarity index (no external vector database required)
- **Database:** SQLite (local) / PostgreSQL (production)
- **GSTIN validation:** RapidAPI GST Insights
- **Deployment:** Docker Compose (API + Frontend + PostgreSQL)
- **Fraud detection:** SHA-256 document fingerprinting, statistical bid analysis
- **Audit:** Append-only JSONL event log
