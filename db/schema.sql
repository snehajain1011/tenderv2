CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS tenders (
    id UUID PRIMARY KEY,
    workspace_name TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    storage_uri TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tender_documents (
    id UUID PRIMARY KEY,
    tender_id UUID NOT NULL REFERENCES tenders(id),
    filename TEXT NOT NULL,
    storage_uri TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL,
    parser TEXT NOT NULL,
    parse_confidence DOUBLE PRECISION NOT NULL,
    page_count INTEGER NOT NULL,
    parsed_text TEXT NOT NULL,
    source_type TEXT NOT NULL,
    document_quality_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS vendors (
    id UUID PRIMARY KEY,
    legal_name TEXT NOT NULL UNIQUE,
    gstin TEXT,
    pan TEXT,
    msme_status TEXT,
    debarment_declaration BOOLEAN,
    flagged BOOLEAN NOT NULL DEFAULT FALSE,
    flagged_reason TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS submissions (
    id UUID PRIMARY KEY,
    tender_id UUID NOT NULL REFERENCES tenders(id),
    vendor_id UUID NOT NULL REFERENCES vendors(id),
    bidder_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'submitted',
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(tender_id, vendor_id)
);

CREATE TABLE IF NOT EXISTS bid_documents (
    id UUID PRIMARY KEY,
    tender_id UUID NOT NULL REFERENCES tenders(id),
    submission_id UUID NOT NULL REFERENCES submissions(id),
    filename TEXT NOT NULL,
    storage_uri TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL,
    parser TEXT NOT NULL,
    parse_confidence DOUBLE PRECISION NOT NULL,
    page_count INTEGER NOT NULL,
    parsed_text TEXT NOT NULL,
    source_type TEXT NOT NULL,
    document_quality_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY,
    tender_id UUID NOT NULL REFERENCES tenders(id),
    document_id UUID,
    submission_id UUID,
    document_kind TEXT NOT NULL,
    source_file TEXT NOT NULL,
    page INTEGER NOT NULL,
    section TEXT NOT NULL,
    start_offset INTEGER NOT NULL,
    end_offset INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    quality_flags_json TEXT NOT NULL DEFAULT '[]',
    embedding vector(1024),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS criteria (
    id UUID PRIMARY KEY,
    tender_id UUID NOT NULL REFERENCES tenders(id),
    criterion_code TEXT NOT NULL,
    category TEXT NOT NULL,
    mandatory BOOLEAN NOT NULL,
    description TEXT NOT NULL,
    rule_type TEXT NOT NULL,
    threshold TEXT NOT NULL DEFAULT '',
    time_period TEXT NOT NULL DEFAULT '',
    accepted_evidence_json TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_page INTEGER NOT NULL,
    source_excerpt TEXT NOT NULL,
    source_section TEXT NOT NULL,
    source_chunk_id TEXT NOT NULL DEFAULT '',
    criteria_risk_flags_json TEXT NOT NULL DEFAULT '[]',
    version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS evidence (
    id UUID PRIMARY KEY,
    criterion_id UUID NOT NULL REFERENCES criteria(id),
    submission_id UUID NOT NULL REFERENCES submissions(id),
    source_file TEXT NOT NULL,
    source_page INTEGER NOT NULL,
    source_section TEXT NOT NULL,
    source_chunk_id TEXT NOT NULL DEFAULT '',
    extracted_value TEXT NOT NULL,
    normalized_value TEXT NOT NULL DEFAULT '',
    confidence DOUBLE PRECISION NOT NULL,
    source_excerpt TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    uncertainty_type TEXT NOT NULL DEFAULT '',
    candidate_snippets_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS verdicts (
    id UUID PRIMARY KEY,
    criterion_id UUID NOT NULL REFERENCES criteria(id),
    submission_id UUID NOT NULL REFERENCES submissions(id),
    evidence_id UUID,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    extracted_value TEXT NOT NULL DEFAULT '',
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    rule_trace TEXT NOT NULL,
    manual_review_reason TEXT NOT NULL DEFAULT '',
    human_reviewer_action TEXT NOT NULL DEFAULT '',
    tender_source_json TEXT NOT NULL,
    bidder_source_json TEXT NOT NULL,
    model_version TEXT NOT NULL DEFAULT '',
    rule_version TEXT NOT NULL DEFAULT 'v1',
    uncertainty_type TEXT NOT NULL DEFAULT '',
    suggested_action TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS review_tasks (
    id UUID PRIMARY KEY,
    tender_id UUID NOT NULL REFERENCES tenders(id),
    submission_id UUID,
    criterion_id UUID,
    reason TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'high',
    source_file TEXT NOT NULL DEFAULT '',
    issue_type TEXT NOT NULL DEFAULT '',
    extracted_value TEXT NOT NULL DEFAULT '',
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    suggested_action TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    reviewer_action TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bidder_results (
    id UUID PRIMARY KEY,
    tender_id UUID NOT NULL REFERENCES tenders(id),
    submission_id UUID NOT NULL REFERENCES submissions(id),
    bidder_name TEXT NOT NULL,
    overall_status TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS awards (
    id UUID PRIMARY KEY,
    tender_id UUID NOT NULL REFERENCES tenders(id),
    winning_submission_id UUID,
    status TEXT NOT NULL DEFAULT 'pending_approval',
    justification TEXT NOT NULL,
    award_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS contracts (
    id UUID PRIMARY KEY,
    award_id UUID NOT NULL REFERENCES awards(id),
    contract_number TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    delivery_terms TEXT NOT NULL DEFAULT '',
    performance_security_expiry DATE,
    contract_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_outputs (
    id UUID PRIMARY KEY,
    tender_id UUID NOT NULL REFERENCES tenders(id),
    stage TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    output_key TEXT NOT NULL,
    output_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_events (
    id UUID PRIMARY KEY,
    tender_id UUID,
    actor TEXT NOT NULL DEFAULT 'system',
    event_type TEXT NOT NULL,
    event_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
