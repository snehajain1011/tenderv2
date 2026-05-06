import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { marked } from 'marked';
import {
  AlertTriangle,
  BarChart3,
  BookOpen,
  CheckCircle2,
  ClipboardList,
  Clock,
  Database,
  Download,
  FileCheck2,
  FileText,
  FolderUp,
  Gavel,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  Upload,
  Users,
  UserPlus,
  Zap,
} from 'lucide-react';
import './styles.css';

const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';

function App() {
  const [activeView, setActiveView] = useState('pre');
  const [workspace, setWorkspace] = useState('demo');
  const [vendorName, setVendorName] = useState('');
  const [flow, setFlow] = useState(null);
  const [result, setResult] = useState(null);
  const [report, setReport] = useState('');
  const [auditEvents, setAuditEvents] = useState([]);
  const [vendors, setVendors] = useState([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('Ready');

  const metrics = useMemo(() => summarize(result), [result]);
  const award = useMemo(() => awardRecommendation(result), [result]);

  useEffect(() => {
    loadFlow(workspace).catch(() => {});
  }, []);

  async function loadFlow(name = workspace) {
    const data = await request(`${API}/workspaces/${encodeURIComponent(name)}/procurement-flow`);
    setFlow(data);
  }

  async function createDemo() {
    setBusy(true);
    setMessage('Creating sandbox workspace...');
    try {
      await request(`${API}/workspaces/demo`, { method: 'POST' });
      setWorkspace('demo');
      await loadFlow('demo');
      setMessage('Demo workspace created.');
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function createWorkspace() {
    setBusy(true);
    setMessage('Creating workspace...');
    try {
      await request(`${API}/workspaces/${encodeURIComponent(workspace)}`, { method: 'POST' });
      await loadFlow(workspace);
      setMessage(`Workspace ${workspace} is ready.`);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function evaluateWorkspace() {
    setBusy(true);
    setMessage('Running bid review, comparisons, and explainability gates...');
    try {
      const data = await request(`${API}/workspaces/${encodeURIComponent(workspace)}/evaluate`, { method: 'POST' });
      setResult(data);
      await loadFlow(workspace);
      const md = await fetch(`${API}/workspaces/${encodeURIComponent(workspace)}/reports/evaluation_report.md`).then((res) => res.text());
      setReport(md);
      // Load audit trail and vendor directory after evaluation
      try {
        const auditData = await request(`${API}/workspaces/${encodeURIComponent(workspace)}/audit-trail`);
        setAuditEvents(auditData.events || []);
      } catch { /* audit log may not exist yet */ }
      try {
        const vendorData = await request(`${API}/workspaces/${encodeURIComponent(workspace)}/vendor-directory`);
        setVendors(vendorData.vendors || []);
      } catch { /* vendor directory may not exist yet */ }
      setMessage(`Evaluation complete. Final accuracy gate ${data.final_accuracy_gate_passed ? 'passed' : 'failed'}.`);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function uploadTender(files) {
    if (!files?.length) return;
    setBusy(true);
    setMessage('Uploading tender package...');
    try {
      await uploadFiles(`${API}/workspaces/${encodeURIComponent(workspace)}/tender-documents`, files);
      await loadFlow(workspace);
      setMessage(`${files.length} tender document(s) uploaded.`);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function importTenderUrl(url) {
    if (!url.trim()) {
      setMessage('Enter a public tender PDF/document URL first.');
      return;
    }
    setBusy(true);
    setMessage('Importing tender from public URL...');
    try {
      await request(`${API}/workspaces/${encodeURIComponent(workspace)}/tender-url?url=${encodeURIComponent(url)}`, { method: 'POST' });
      await loadFlow(workspace);
      setMessage('Tender URL imported into this workspace.');
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function uploadVendor(files) {
    if (!files?.length || !vendorName.trim()) {
      setMessage('Enter vendor name before uploading bidder documents.');
      return;
    }
    setBusy(true);
    setMessage('Collecting bidder submission...');
    try {
      await uploadFiles(`${API}/workspaces/${encodeURIComponent(workspace)}/vendors/${encodeURIComponent(vendorName)}/documents`, files);
      await loadFlow(workspace);
      setMessage(`${files.length} bidder document(s) uploaded for ${vendorName}.`);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <aside>
        <div className="brand">
          <ShieldCheck size={28} />
          <div>
            <h1>Procurement AI</h1>
            <p>Government tender operations</p>
          </div>
        </div>
        <nav>
          <button className={activeView === 'pre' ? 'active' : ''} onClick={() => setActiveView('pre')}>
            <FileCheck2 size={18} /> Pre-Tender
          </button>
          <button className={activeView === 'vendor' ? 'active' : ''} onClick={() => setActiveView('vendor')}>
            <UserPlus size={18} /> Vendor Submission
          </button>
          <button className={activeView === 'review' ? 'active' : ''} onClick={() => setActiveView('review')}>
            <ClipboardList size={18} /> Bid Review
          </button>
          <button className={activeView === 'award' ? 'active' : ''} onClick={() => setActiveView('award')}>
            <Gavel size={18} /> Award
          </button>
          <button className={activeView === 'reports' ? 'active' : ''} onClick={() => setActiveView('reports')}>
            <FileText size={18} /> Reports
          </button>
          <button className={activeView === 'directory' ? 'active' : ''} onClick={() => setActiveView('directory')}>
            <Database size={18} /> Vendor Directory
          </button>
          <button className={activeView === 'audit' ? 'active' : ''} onClick={() => setActiveView('audit')}>
            <BookOpen size={18} /> Audit Trail
          </button>
        </nav>
      </aside>

      <section className="content">
        <header>
          <div>
            <p className="eyebrow">Workspace</p>
            <div className="workspace-row">
              <input value={workspace} onChange={(event) => setWorkspace(event.target.value)} />
              <button onClick={createWorkspace} disabled={busy}><FolderUp size={17} /> Create</button>
              <button onClick={createDemo} disabled={busy}><FileCheck2 size={17} /> Demo</button>
              <button className="primary" onClick={evaluateWorkspace} disabled={busy}><RefreshCw size={17} /> Evaluate</button>
            </div>
          </div>
          <StatusPill message={message} busy={busy} />
        </header>

        {activeView === 'pre' && <PreTenderView flow={flow} onTenderUpload={uploadTender} onTenderUrl={importTenderUrl} busy={busy} />}
        {activeView === 'vendor' && <VendorView flow={flow} vendorName={vendorName} setVendorName={setVendorName} onUpload={uploadVendor} busy={busy} />}
        {activeView === 'review' && <ReviewView metrics={metrics} result={result} flow={flow} />}
        {activeView === 'award' && <AwardView award={award} result={result} />}
        {activeView === 'reports' && <ReportView report={report} result={result} />}
        {activeView === 'directory' && <VendorDirectoryView vendors={vendors} workspace={workspace} />}
        {activeView === 'audit' && <AuditTrailView events={auditEvents} />}
      </section>
    </main>
  );
}

function PreTenderView({ flow, onTenderUpload, onTenderUrl, busy }) {
  const [url, setUrl] = useState('');
  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Prepare Tender Package</h2>
            <p>Collect technical specs, quantity, budget, delivery terms, eligibility criteria, and contract conditions.</p>
          </div>
          <label className="upload-button">
            <Upload size={17} />
            Upload Tender
            <input type="file" multiple disabled={busy} onChange={(event) => onTenderUpload(event.target.files)} />
          </label>
        </div>
        <StepList steps={flow?.pre_tender || []} />
      </section>
      <section className="panel">
        <h2>Import Public Tender URL</h2>
        <p className="muted">Use this for public CRPF/CPPP/Gem tender PDFs or redacted sandbox documents.</p>
        <div className="url-row">
          <input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://example.gov.in/tender.pdf" />
          <button onClick={() => onTenderUrl(url)} disabled={busy}><Download size={17} /> Import</button>
        </div>
      </section>
      <section className="panel">
        <h2>Publication Readiness</h2>
        <p className="muted">Use this checklist before putting the tender on GeM / e-tender portal and making it available to vendors.</p>
        <Checklist items={[
          'Tender package uploaded and versioned',
          'Technical specifications captured',
          'Quantity, budget, and delivery terms captured',
          'Eligibility criteria captured',
          'Contract terms and conditions captured',
          'Audit trail and source hashes preserved',
        ]} />
      </section>
    </>
  );
}

function VendorView({ flow, vendorName, setVendorName, onUpload, busy }) {
  const submissions = flow?.tender_stage?.[0]?.evidence || [];
  return (
    <>
      <section className="panel vendor-panel">
        <div className="panel-head">
          <div>
            <h2>Vendor Registration And Submission</h2>
            <p>Collect quotations, proposals, certificates, technical bid, and financial bid into the selected workspace.</p>
          </div>
        </div>
        <div className="form-grid">
          <label>
            Vendor name
            <input value={vendorName} onChange={(event) => setVendorName(event.target.value)} placeholder="Example: Alpha Secure Systems" />
          </label>
          <label className="dropzone">
            <Upload size={24} />
            <span>Upload bidder documents</span>
            <input type="file" multiple disabled={busy} onChange={(event) => onUpload(event.target.files)} />
          </label>
        </div>
      </section>
      <section className="panel">
        <h2>Downloaded / Collected Bids</h2>
        <VendorSubmissionList submissions={submissions} />
      </section>
    </>
  );
}

function ReviewView({ metrics, result, flow }) {
  return (
    <>
      <section className="metrics">
        <Metric icon={<Gavel />} label="Bidders" value={metrics.bidders} />
        <Metric icon={<CheckCircle2 />} label="Eligible" value={metrics.eligible} />
        <Metric icon={<AlertTriangle />} label="Manual Review" value={metrics.review} />
        <Metric icon={<BarChart3 />} label="Final Gate" value={metrics.finalGate} />
      </section>

      {result?.bidder_quality && <BidderQualityPanel quality={result.bidder_quality} />}
      {result?.risk_signals?.length > 0 && <RiskIntelligencePanel signals={result.risk_signals} />}

      <section className="panel">
        <h2>Tendering Stage Workflow</h2>
        <StepList steps={flow?.tender_stage || []} />
      </section>
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Bid Review And Comparison</h2>
            <p>Price comparison, technical comparison, vendor qualification check, and review/POC coordination.</p>
          </div>
        </div>
        <BidderTable result={result} />
      </section>
    </>
  );
}

function BidderQualityPanel({ quality }) {
  const gradeColour = { A: '#166534', B: '#15803d', C: '#92400e', D: '#b45309', F: '#991b1b' };
  const gradeBg     = { A: '#dcfce7', B: '#bbf7d0', C: '#fef3c7', D: '#fde68a', F: '#fee2e2' };
  const colour = gradeColour[quality.grade] || '#374151';
  const bg     = gradeBg[quality.grade]     || '#e5e7eb';
  const highRisk = quality.flagged_criteria.filter((c) => c.score >= 60);
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2><ShieldAlert size={17} style={{ verticalAlign: 'middle', marginRight: 6 }} />Bidder Ambiguity Scoring</h2>
          <p className="muted">AI-scored criteria for vague thresholds, subjective language, and unverifiable clauses — surfaces risk in bidder submissions before evaluation.</p>
        </div>
        <div className="tq-grade" style={{ color: colour, background: bg }}>
          {quality.grade}
        </div>
      </div>
      <p className="tq-summary">{quality.summary}</p>
      {highRisk.length > 0 && (
        <div className="tq-list">
          {highRisk.map((c) => (
            <details key={c.id} className="tq-row">
              <summary>
                <strong>{c.id}</strong>
                <span className="tq-score" style={{ background: c.score >= 80 ? '#fee2e2' : '#fef3c7', color: c.score >= 80 ? '#991b1b' : '#92400e' }}>
                  {c.score}/100
                </span>
                <span>{c.description.slice(0, 90)}{c.description.length > 90 ? '…' : ''}</span>
                {c.mandatory && <span className="chip-mandatory">Mandatory</span>}
              </summary>
              <div className="tq-flags">
                {c.flags.map((f) => <span key={f} className="flag-chip">{f.replace(/_/g, ' ')}</span>)}
              </div>
            </details>
          ))}
        </div>
      )}
    </section>
  );
}

function RiskIntelligencePanel({ signals }) {
  const sevColour = { high: ['#991b1b', '#fee2e2'], medium: ['#92400e', '#fef3c7'], low: ['#1e40af', '#dbeafe'] };
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2><Zap size={17} style={{ verticalAlign: 'middle', marginRight: 6 }} />Procurement Risk Intelligence</h2>
          <p className="muted">Fraud and collusion signals detected across all bidder submissions.</p>
        </div>
        <span className={`status ${signals.some((s) => s.severity === 'high') ? 'fail' : 'review'}`}>
          {signals.filter((s) => s.severity === 'high').length} High · {signals.filter((s) => s.severity === 'medium').length} Medium
        </span>
      </div>
      <div className="risk-list">
        {signals.map((signal, idx) => {
          const [fg, bg] = sevColour[signal.severity] || ['#374151', '#e5e7eb'];
          return (
            <details key={idx} className="risk-row">
              <summary>
                <span className="risk-sev-chip" style={{ color: fg, background: bg }}>{signal.severity.toUpperCase()}</span>
                <strong>{signal.title}</strong>
                <span className="muted">{signal.affected_bidders.join(', ')}</span>
              </summary>
              <div className="risk-detail">
                <p>{signal.description}</p>
                <p className="muted" style={{ marginTop: 6 }}>Evidence: {signal.evidence}</p>
              </div>
            </details>
          );
        })}
      </div>
    </section>
  );
}

function AwardView({ award, result }) {
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>Award Contract</h2>
          <p>Select winning bidder, issue purchase order / contract, and preserve rejection reasons.</p>
        </div>
      </div>
      {!result ? (
        <div className="empty">Run bid evaluation before award recommendation.</div>
      ) : (
        <div className="award-grid">
          <article>
            <span className="label">Recommended action</span>
            <strong>{award.action}</strong>
            <p>{award.reason}</p>
          </article>
          <article>
            <span className="label">Winning bidder</span>
            <strong>{award.winner || 'Not ready'}</strong>
            <p>{award.winner ? `Eligible L1 bidder at ${award.price}.` : 'Manual review must be resolved before award.'}</p>
          </article>
        </div>
      )}
      {result && <SelectionReasons result={result} />}
    </section>
  );
}

function ReportView({ report, result }) {
  const [mode, setMode] = useState('rendered');
  const renderedHtml = report ? marked.parse(report) : '';
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>Consolidated Report</h2>
          <p>Every decision includes the criterion, source document, extracted value, and reason.</p>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          {result && (
            <div className="report-links">
              <a href={`${API}/workspaces/${encodeURIComponent(result.tender_id)}/reports/evaluation_report.md`} target="_blank"><Download size={16} /> Markdown</a>
              <a href={`${API}/workspaces/${encodeURIComponent(result.tender_id)}/reports/evaluation_report.json`} target="_blank"><Download size={16} /> JSON</a>
              <a href={`${API}/workspaces/${encodeURIComponent(result.tender_id)}/reports/agent_outputs.json`} target="_blank"><Download size={16} /> Agent Outputs</a>
              <a href={`${API}/workspaces/${encodeURIComponent(result.tender_id)}/reports/audit_log.jsonl`} target="_blank"><Download size={16} /> Audit</a>
            </div>
          )}
          <div className="report-mode-toggle">
            <button className={mode === 'rendered' ? 'active' : ''} onClick={() => setMode('rendered')}>Preview</button>
            <button className={mode === 'raw' ? 'active' : ''} onClick={() => setMode('raw')}>Raw</button>
          </div>
        </div>
      </div>
      {!report && <div className="empty">Run an evaluation to preview the generated consolidated report.</div>}
      {report && mode === 'rendered' && (
        <div
          className="report-rendered"
          dangerouslySetInnerHTML={{ __html: renderedHtml }}
        />
      )}
      {report && mode === 'raw' && (
        <pre className="report-preview">{report}</pre>
      )}
    </section>
  );
}

function VendorDirectoryView({ vendors, workspace }) {
  const [search, setSearch] = useState('');
  const filtered = vendors.filter((v) =>
    v.name.toLowerCase().includes(search.toLowerCase()) ||
    (v.gstin || '').toLowerCase().includes(search.toLowerCase()) ||
    (v.legal_name || '').toLowerCase().includes(search.toLowerCase())
  );
  const gstinColour = { clear: 'pass', invalid: 'fail', flagged: 'fail', not_found: 'review' };
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2><Users size={17} style={{ verticalAlign: 'middle', marginRight: 6 }} />Vendor Directory</h2>
          <p className="muted">Verified supplier profiles with GSTIN status, certifications, and performance records from the latest evaluation.</p>
        </div>
        <input
          className="dir-search"
          placeholder="Search by name or GSTIN…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      {!vendors.length
        ? <div className="empty">Run an evaluation to populate the vendor directory.</div>
        : (
          <div className="vendor-dir-grid">
            {filtered.map((v) => (
              <article key={v.name} className={`vendor-card ${v.flagged ? 'vendor-flagged' : ''}`}>
                <div className="vendor-card-head">
                  <div>
                    <strong>{v.name}</strong>
                    {v.legal_name && v.legal_name !== v.name && (
                      <p className="muted" style={{ fontSize: 12, marginTop: 2 }}>{v.legal_name}</p>
                    )}
                  </div>
                  <span className={`status ${v.overall_status === 'Eligible' ? 'pass' : v.overall_status === 'Not Eligible' ? 'fail' : 'review'}`}>
                    {v.overall_status}
                  </span>
                </div>
                <div className="vendor-meta">
                  <span><strong>GSTIN:</strong> {v.gstin || '—'}</span>
                  <span className={`status ${gstinColour[v.gstin_status] || 'neutral'}`} style={{ fontSize: 10 }}>
                    {v.gstin_status.replace('_', ' ').toUpperCase()}
                  </span>
                </div>
                <div className="vendor-criteria-bar">
                  {v.total_criteria > 0 && (
                    <>
                      <span className="bar-pass" style={{ flex: v.criteria_passed }} title={`${v.criteria_passed} passed`} />
                      <span className="bar-fail" style={{ flex: v.criteria_failed }} title={`${v.criteria_failed} failed`} />
                      <span className="bar-review" style={{ flex: v.criteria_review }} title={`${v.criteria_review} review`} />
                    </>
                  )}
                </div>
                <p style={{ fontSize: 11, color: '#6b7280', marginTop: 6 }}>
                  {v.criteria_passed} passed · {v.criteria_failed} failed · {v.criteria_review} review · {v.review_tasks} task{v.review_tasks !== 1 ? 's' : ''}
                </p>
                {v.flagged && <p className="vendor-flag-reason"><ShieldX size={12} /> {v.flag_reason}</p>}
              </article>
            ))}
          </div>
        )}
    </section>
  );
}

function AuditTrailView({ events }) {
  const [filter, setFilter] = useState('');
  const filtered = events.filter((e) => {
    if (!filter) return true;
    const q = filter.toLowerCase();
    return (
      (e.step || '').toLowerCase().includes(q) ||
      (e.subject || '').toLowerCase().includes(q) ||
      JSON.stringify(e.detail || {}).toLowerCase().includes(q)
    );
  });
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2><BookOpen size={17} style={{ verticalAlign: 'middle', marginRight: 6 }} />Audit Trail</h2>
          <p className="muted">
            Full immutable log of every action — document uploads, GSTIN checks, evidence extraction, verdicts, and persistence.
            Demonstrates fairness, accountability, and compliance to all stakeholders.
          </p>
        </div>
        <input
          className="dir-search"
          placeholder="Filter events…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>
      {!events.length
        ? <div className="empty">Run an evaluation to generate the audit trail.</div>
        : (
          <div className="audit-list">
            {filtered.map((evt, idx) => (
              <details key={idx} className="audit-row">
                <summary>
                  <Clock size={13} className="audit-icon" />
                  <span className="audit-step">{evt.step || '—'}</span>
                  <span className="audit-subject">{evt.subject || ''}</span>
                </summary>
                <pre className="audit-detail">{JSON.stringify(evt.detail || {}, null, 2)}</pre>
              </details>
            ))}
            {filtered.length === 0 && <div className="empty">No events match the filter.</div>}
          </div>
        )}
    </section>
  );
}

function gstinRejected(bidder) {
  const s = bidder.gstin_check?.check_status;
  return s === 'invalid' || s === 'flagged';
}

function BidderTable({ result }) {
  if (!result) return <div className="empty">Collect bidder documents, then run evaluation.</div>;
  return (
    <div className="bidder-list">
      {result.bidders.map((bidder) => {
        const rejected = gstinRejected(bidder);
        return (
          <article className={`bidder-card${rejected ? ' gstin-rejected' : ''}`} key={bidder.bidder}>
            <div className="bidder-head">
              <h3>{bidder.bidder}</h3>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <span className={`status ${statusClass(bidder.overall_status)}`}>{bidder.overall_status}</span>
                <a
                  className="report-dl-btn"
                  href={`${API}/workspaces/${encodeURIComponent(result.tender_id)}/bidders/${encodeURIComponent(bidder.bidder)}/rejection-report`}
                  target="_blank"
                  rel="noreferrer"
                  title="Download adjudication report"
                >
                  <Download size={13} /> Report
                </a>
              </div>
            </div>

            {rejected && (
              <div className="gstin-rejection-banner">
                <ShieldX size={16} />
                <span>
                  {bidder.gstin_check.check_status === 'flagged'
                    ? 'Vendor flagged — not permitted to bid'
                    : 'Invalid GSTIN — bid rejected'}
                  {bidder.gstin_check.gstin && (
                    <> &middot; GSTIN: <strong>{bidder.gstin_check.gstin}</strong></>
                  )}
                </span>
                <p className="gstin-rejection-reason">{bidder.gstin_check.rejection_reason}</p>
              </div>
            )}

            {!rejected && (
              <div className="verdict-table">
                {bidder.verdicts.map((verdict) => (
                  <details className="verdict-row" key={verdict.criterion_id}>
                    <summary>
                      <strong>{verdict.criterion_id}</strong>
                      <span className={`status ${statusClass(verdict.status)}`}>{verdict.status}</span>
                      <span>{verdict.extracted_value || 'No value'}</span>
                      <p>{verdict.reason}</p>
                    </summary>
                    <div className="explanation">
                      <p><b>Criterion:</b> {verdict.criterion}</p>
                      <p><b>Tender source:</b> {citation(verdict.tender_source)}</p>
                      <p><b>Bidder source:</b> {citation(verdict.bidder_source)}</p>
                      <p><b>Rule trace:</b> {verdict.rule_trace}</p>
                      {verdict.manual_review_reason && <p><b>Manual review:</b> {verdict.manual_review_reason}</p>}
                    </div>
                  </details>
                ))}
              </div>
            )}

            {!rejected && bidder.review_tasks?.length > 0 && (
              <div className="review-list">
                {bidder.review_tasks.map((task) => (
                  <p key={`${task.task_id}-${task.reason}`}><AlertTriangle size={15} /> {task.reason}</p>
                ))}
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}

function StepList({ steps }) {
  if (!steps.length) return <div className="empty">Create a workspace or upload documents to populate this workflow.</div>;
  return (
    <div className="step-list">
      {steps.map((step) => (
        <article className="step-card" key={step.step}>
          <div>
            <h3>{step.step}</h3>
            <span className={`status ${step.status === 'ready' ? 'pass' : step.status === 'blocked' ? 'fail' : 'review'}`}>{step.status}</span>
          </div>
          <Checklist items={step.items || []} />
          {step.evidence?.length > 0 && <p className="muted">Evidence/files: {formatEvidence(step.evidence)}</p>}
        </article>
      ))}
    </div>
  );
}

function Checklist({ items }) {
  return (
    <ul className="checklist">
      {items.map((item) => <li key={item}><CheckCircle2 size={15} /> {item}</li>)}
    </ul>
  );
}

function VendorSubmissionList({ submissions }) {
  if (!submissions.length) return <div className="empty">No bidder submissions collected yet.</div>;
  return (
    <div className="submission-list">
      {submissions.map((submission) => (
        <article key={submission.vendor}>
          <h3>{submission.vendor}</h3>
          <p>{submission.documents.length} document(s)</p>
          <span>{submission.documents.join(', ')}</span>
        </article>
      ))}
    </div>
  );
}

function SelectionReasons({ result }) {
  const reasons = selectionReasons(result);
  return (
    <div className="rejection-list">
      <h3>Selection / Rejection Reasons</h3>
      {reasons.map((item) => (
        <p key={item.bidder}>
          <b>{item.bidder}</b> - {item.decision}: {item.reason} {item.source && <>Source: {item.source}</>}
        </p>
      ))}
    </div>
  );
}

function Metric({ icon, label, value }) {
  return (
    <article className="metric">
      {React.cloneElement(icon, { size: 22 })}
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function StatusPill({ message, busy }) {
  return <div className={`status-pill ${busy ? 'busy' : ''}`}>{busy && <RefreshCw size={16} />} {message}</div>;
}

async function uploadFiles(url, files) {
  const body = new FormData();
  Array.from(files).forEach((file) => body.append('files', file));
  return request(url, { method: 'POST', body });
}

async function request(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const data = await response.json();
      detail = data.detail || detail;
    } catch {
      // keep status text
    }
    throw new Error(detail);
  }
  return response.json();
}

function summarize(result) {
  if (!result) return { bidders: 0, eligible: 0, review: 0, finalGate: 'Waiting' };
  return {
    bidders: result.bidders.length,
    eligible: result.bidders.filter((item) => item.overall_status === 'Eligible').length,
    review: result.bidders.filter((item) => item.overall_status === 'Need Manual Review').length,
    finalGate: result.final_accuracy_gate_passed ? 'Passed' : 'Failed',
  };
}

function awardRecommendation(result) {
  if (!result) return { action: 'Evaluation pending', winner: '', reason: 'Run evaluation before award.', price: '' };
  const reviewCount = result.bidders.filter((bidder) => bidder.overall_status === 'Need Manual Review').length;
  if (reviewCount > 0) {
    return { action: 'Hold award', winner: '', reason: `${reviewCount} bidder(s) require manual review before award.`, price: '' };
  }
  const eligible = result.bidders
    .filter((bidder) => bidder.overall_status === 'Eligible')
    .map((bidder) => ({ bidder, price: bidderPrice(bidder) }))
    .filter((item) => item.price !== null)
    .sort((a, b) => a.price - b.price);
  if (!eligible.length) return { action: 'Do not award', winner: '', reason: 'No eligible bidder has a normalized quoted price for L1 comparison.', price: '' };
  const l1 = eligible[0];
  return { action: 'Proceed to award', winner: l1.bidder.bidder, reason: 'Eligible L1 bidder found; issue purchase order after officer approval.', price: formatInr(l1.price) };
}

function selectionReasons(result) {
  const pricedEligible = result.bidders
    .filter((bidder) => bidder.overall_status === 'Eligible')
    .map((bidder) => ({ bidder, price: bidderPrice(bidder) }))
    .filter((item) => item.price !== null)
    .sort((a, b) => a.price - b.price);
  const l1 = pricedEligible[0] || null;
  return result.bidders.map((bidder) => {
    const price = bidderPrice(bidder);
    if (l1 && bidder.bidder === l1.bidder.bidder) {
      return {
        bidder: bidder.bidder,
        decision: 'Selected for award recommendation',
        reason: `eligible and lowest extracted quote (${formatInr(price)})`,
        source: priceSource(bidder),
      };
    }
    if (bidder.overall_status === 'Eligible') {
      return {
        bidder: bidder.bidder,
        decision: 'Not selected',
        reason: `eligible, but quoted price ${formatInr(price)} is higher than L1 ${formatInr(l1?.price)} from ${l1?.bidder.bidder || 'another bidder'}`,
        source: priceSource(bidder),
      };
    }
    const failed = bidder.verdicts.filter((verdict) => verdict.status === 'FAIL');
    if (failed.length) {
      return {
        bidder: bidder.bidder,
        decision: 'Rejected / Not eligible',
        reason: failed.map((verdict) => `${verdict.criterion_id}: ${verdict.reason}`).join('; '),
        source: failed.map((verdict) => citation(verdict.bidder_source)).join('; '),
      };
    }
    const reviews = bidder.verdicts.filter((verdict) => verdict.status === 'NEED_MANUAL_REVIEW');
    return {
      bidder: bidder.bidder,
      decision: 'Hold for manual review',
      reason: reviews.map((verdict) => `${verdict.criterion_id}: ${verdict.manual_review_reason || verdict.reason}`).join('; ') || 'Manual review is required before award.',
      source: reviews.map((verdict) => citation(verdict.bidder_source)).join('; '),
    };
  });
}

function bidderPrice(bidder) {
  const verdict = bidder.verdicts.find((item) => item.criterion_id === 'C7' || item.criterion?.toLowerCase().includes('quoted financial bid'));
  return moneyToRupees(verdict?.extracted_value || '');
}

function priceSource(bidder) {
  const verdict = bidder.verdicts.find((item) => item.criterion_id === 'C7' || item.criterion?.toLowerCase().includes('quoted financial bid'));
  return verdict ? citation(verdict.bidder_source) : 'No price source document';
}

function moneyToRupees(value) {
  const match = String(value).match(/([0-9][0-9,]*(?:\.[0-9]+)?)\s*(crore|cr|lakh)?/i);
  if (!match) return null;
  const amount = Number(match[1].replaceAll(',', ''));
  const unit = (match[2] || '').toLowerCase();
  if (unit === 'crore' || unit === 'cr') return amount * 10000000;
  if (unit === 'lakh') return amount * 100000;
  return amount;
}

function formatInr(value) {
  if (value === null || value === undefined) return 'not extracted';
  return `INR ${Math.round(value).toLocaleString('en-IN')}`;
}

function statusClass(value) {
  const text = String(value).toLowerCase();
  if (text.includes('eligible') && !text.includes('not')) return 'pass';
  if (text.includes('not') || text.includes('fail')) return 'fail';
  if (text.includes('review') || text.includes('pending') || text.includes('blocked')) return 'review';
  if (text.includes('pass') || text.includes('ready')) return 'pass';
  return 'neutral';
}

function citation(source) {
  if (!source?.document) return 'No source document';
  return `${source.document}, page ${source.page}: ${source.excerpt}`;
}

function formatEvidence(evidence) {
  if (!Array.isArray(evidence)) return '';
  if (evidence.length > 4) return `${evidence.length} file(s)`;
  return evidence.map((item) => typeof item === 'string' ? item : `${item.vendor} (${item.documents?.length || 0})`).join(', ');
}

createRoot(document.getElementById('root')).render(<App />);
