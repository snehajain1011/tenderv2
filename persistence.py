from __future__ import annotations

import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from report import agent_outputs_payload
from schema import AuditEvent, BidderResult, Criterion, Document, EvaluationResult, Evidence, RagChunk, to_dict


class ProcurementRepository:
    def __init__(self, database_url: str | None = None, sqlite_path: Path | None = None) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL")
        self.sqlite_path = sqlite_path or Path(os.getenv("PROCUREMENT_DB_PATH", "outputs/procurement.sqlite"))
        self.is_postgres = bool(self.database_url)
        self.conn = self._connect()
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def persist_run(
        self,
        workspace_name: str,
        workspace_path: Path,
        tender_docs: list[Document],
        bidder_docs: dict[str, list[Document]],
        tender_chunks: list[RagChunk],
        bidder_chunks: dict[str, list[RagChunk]],
        criteria: list[Criterion],
        evidence_by_bidder: dict[str, list[Evidence]],
        result: EvaluationResult,
        audit_events: list[AuditEvent],
    ) -> None:
        tender_pk = self._upsert_tender(workspace_name, workspace_path)
        doc_map: dict[tuple[str, str], str] = {}
        submission_map: dict[str, str] = {}
        criterion_map: dict[str, str] = {}

        self._delete_run_children(tender_pk)

        for doc in tender_docs:
            doc_map[("tender", doc.name)] = self._insert_document("tender_documents", tender_pk, None, doc)

        for bidder, docs in bidder_docs.items():
            vendor_pk = self._upsert_vendor(bidder)
            submission_pk = self._upsert_submission(tender_pk, vendor_pk, bidder)
            submission_map[bidder] = submission_pk
            for doc in docs:
                doc_map[(bidder, doc.name)] = self._insert_document("bid_documents", tender_pk, submission_pk, doc)

        for chunk in tender_chunks:
            self._insert_chunk(tender_pk, doc_map.get(("tender", chunk.document_name)), "tender", chunk)
        for bidder, chunks in bidder_chunks.items():
            for chunk in chunks:
                self._insert_chunk(tender_pk, doc_map.get((bidder, chunk.document_name)), "bid", chunk, submission_map.get(bidder))

        for criterion in criteria:
            criterion_map[criterion.id] = self._insert_criterion(tender_pk, criterion)

        evidence_map: dict[tuple[str, str], str] = {}
        for bidder, evidence_items in evidence_by_bidder.items():
            submission_pk = submission_map[bidder]
            for evidence in evidence_items:
                criterion_pk = criterion_map[evidence.criterion_id]
                evidence_map[(bidder, evidence.criterion_id)] = self._insert_evidence(criterion_pk, submission_pk, evidence)

        for bidder_result in result.bidders:
            submission_pk = submission_map.get(bidder_result.bidder)
            if not submission_pk:
                continue
            self._insert_bidder_result(tender_pk, submission_pk, bidder_result)
            for verdict in bidder_result.verdicts:
                criterion_pk = criterion_map[verdict.criterion_id]
                self._insert_verdict(criterion_pk, submission_pk, evidence_map.get((bidder_result.bidder, verdict.criterion_id)), verdict)
            for task in bidder_result.review_tasks:
                criterion_pk = criterion_map.get(task.criterion_id)
                self._insert_review_task(tender_pk, submission_pk, criterion_pk, task.reason, task.priority, task.source.document)

        self._insert_award(tender_pk, submission_map, result)
        self._insert_agent_outputs(tender_pk, result, audit_events)
        for event in audit_events:
            self._insert_audit_event(tender_pk, event)
        self.conn.commit()

    def workspace_summary(self, workspace_name: str) -> dict[str, int | str]:
        tender = self._fetch_one("SELECT id, status FROM tenders WHERE workspace_name = {p}", [workspace_name])
        if not tender:
            return {"workspace": workspace_name, "persisted": 0}
        tender_pk, status = tender[0], tender[1]
        return {
            "workspace": workspace_name,
            "persisted": 1,
            "status": status,
            "tender_documents": self._count("tender_documents", tender_pk),
            "submissions": self._count("submissions", tender_pk),
            "bid_documents": self._count("bid_documents", tender_pk),
            "document_chunks": self._count("document_chunks", tender_pk),
            "criteria": self._count("criteria", tender_pk),
            "evidence": self._count_join_submission("evidence", tender_pk),
            "verdicts": self._count_join_submission("verdicts", tender_pk),
            "review_tasks": self._count("review_tasks", tender_pk),
            "bidder_results": self._count("bidder_results", tender_pk),
            "awards": self._count("awards", tender_pk),
            "agent_outputs": self._count("agent_outputs", tender_pk),
            "audit_events": self._count("audit_events", tender_pk),
        }

    def _connect(self):
        if self.is_postgres:
            import psycopg

            return psycopg.connect(self.database_url)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.sqlite_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        statements = _postgres_schema() if self.is_postgres else _sqlite_schema()
        with self.conn.cursor() if self.is_postgres else self.conn:
            for statement in statements:
                self._execute(statement)
        self.conn.commit()

    def _delete_run_children(self, tender_pk: str) -> None:
        for table in [
            "audit_events",
            "agent_outputs",
            "contracts",
            "awards",
            "review_tasks",
            "verdicts",
            "evidence",
            "criteria",
            "document_chunks",
            "bidder_results",
            "bid_documents",
            "submissions",
            "tender_documents",
        ]:
            column = "tender_id"
            if table == "contracts":
                self._execute("DELETE FROM contracts WHERE award_id IN (SELECT id FROM awards WHERE tender_id = {p})", [tender_pk])
                continue
            if table == "bid_documents":
                self._execute("DELETE FROM bid_documents WHERE submission_id IN (SELECT id FROM submissions WHERE tender_id = {p})", [tender_pk])
                continue
            if table == "bidder_results":
                self._execute("DELETE FROM bidder_results WHERE submission_id IN (SELECT id FROM submissions WHERE tender_id = {p})", [tender_pk])
                continue
            if table == "evidence":
                self._execute("DELETE FROM evidence WHERE submission_id IN (SELECT id FROM submissions WHERE tender_id = {p})", [tender_pk])
                continue
            if table == "verdicts":
                self._execute("DELETE FROM verdicts WHERE submission_id IN (SELECT id FROM submissions WHERE tender_id = {p})", [tender_pk])
                continue
            self._execute(f"DELETE FROM {table} WHERE {column} = {{p}}", [tender_pk])

    def _upsert_tender(self, workspace_name: str, workspace_path: Path) -> str:
        existing = self._fetch_one("SELECT id FROM tenders WHERE workspace_name = {p}", [workspace_name])
        if existing:
            tender_pk = existing[0]
            self._execute("UPDATE tenders SET storage_uri = {p}, status = {p}, updated_at = CURRENT_TIMESTAMP WHERE id = {p}", [str(workspace_path), "evaluated", tender_pk])
            return tender_pk
        tender_pk = _id()
        self._execute(
            "INSERT INTO tenders (id, workspace_name, title, status, storage_uri) VALUES ({p}, {p}, {p}, {p}, {p})",
            [tender_pk, workspace_name, workspace_name, "evaluated", str(workspace_path)],
        )
        return tender_pk

    def _upsert_vendor(self, bidder: str) -> str:
        existing = self._fetch_one("SELECT id FROM vendors WHERE legal_name = {p}", [bidder])
        if existing:
            return existing[0]
        vendor_pk = _id()
        self._execute("INSERT INTO vendors (id, legal_name) VALUES ({p}, {p})", [vendor_pk, bidder])
        return vendor_pk

    def _upsert_submission(self, tender_pk: str, vendor_pk: str, bidder: str) -> str:
        existing = self._fetch_one("SELECT id FROM submissions WHERE tender_id = {p} AND vendor_id = {p}", [tender_pk, vendor_pk])
        if existing:
            return existing[0]
        submission_pk = _id()
        self._execute(
            "INSERT INTO submissions (id, tender_id, vendor_id, bidder_name, status) VALUES ({p}, {p}, {p}, {p}, {p})",
            [submission_pk, tender_pk, vendor_pk, bidder, "submitted"],
        )
        return submission_pk

    def _insert_document(self, table: str, tender_pk: str, submission_pk: str | None, doc: Document) -> str:
        doc_pk = _id()
        if table == "tender_documents":
            self._execute(
                "INSERT INTO tender_documents (id, tender_id, filename, storage_uri, checksum_sha256, parser, parse_confidence, page_count, parsed_text, source_type) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})",
                [doc_pk, tender_pk, doc.name, doc.path, doc.checksum_sha256, doc.parser, doc.confidence, doc.page_count, doc.text, doc.source_type],
            )
        else:
            self._execute(
                "INSERT INTO bid_documents (id, tender_id, submission_id, filename, storage_uri, checksum_sha256, parser, parse_confidence, page_count, parsed_text, source_type) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})",
                [doc_pk, tender_pk, submission_pk, doc.name, doc.path, doc.checksum_sha256, doc.parser, doc.confidence, doc.page_count, doc.text, doc.source_type],
            )
        return doc_pk

    def _insert_chunk(self, tender_pk: str, doc_pk: str | None, kind: str, chunk: RagChunk, submission_pk: str | None = None) -> None:
        self._execute(
            "INSERT INTO document_chunks (id, tender_id, document_id, submission_id, document_kind, source_file, page, section, start_offset, end_offset, chunk_text) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})",
            [_id(), tender_pk, doc_pk, submission_pk, kind, chunk.document_name, chunk.page, chunk.section, chunk.start, chunk.end, chunk.text],
        )

    def _insert_criterion(self, tender_pk: str, criterion: Criterion) -> str:
        criterion_pk = _id()
        self._execute(
            "INSERT INTO criteria (id, tender_id, criterion_code, category, mandatory, description, rule_type, threshold, time_period, accepted_evidence_json, source_file, source_page, source_excerpt, source_section, source_chunk_id, version) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})",
            [
                criterion_pk,
                tender_pk,
                criterion.id,
                criterion.category,
                criterion.mandatory,
                criterion.description,
                criterion.comparison_rule,
                criterion.threshold,
                criterion.time_period,
                _json(criterion.accepted_evidence),
                criterion.tender_citation.document,
                criterion.tender_citation.page,
                criterion.tender_citation.excerpt,
                criterion.tender_citation.section,
                criterion.tender_citation.chunk_id,
                1,
            ],
        )
        return criterion_pk

    def _insert_evidence(self, criterion_pk: str, submission_pk: str, evidence: Evidence) -> str:
        evidence_pk = _id()
        self._execute(
            "INSERT INTO evidence (id, criterion_id, submission_id, source_file, source_page, source_section, source_chunk_id, extracted_value, normalized_value, confidence, source_excerpt, notes) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})",
            [
                evidence_pk,
                criterion_pk,
                submission_pk,
                evidence.bidder_citation.document,
                evidence.bidder_citation.page,
                evidence.bidder_citation.section,
                evidence.bidder_citation.chunk_id,
                evidence.value,
                evidence.normalized_value,
                evidence.confidence,
                evidence.bidder_citation.excerpt,
                evidence.notes,
            ],
        )
        return evidence_pk

    def _insert_bidder_result(self, tender_pk: str, submission_pk: str, bidder: BidderResult) -> None:
        self._execute(
            "INSERT INTO bidder_results (id, tender_id, submission_id, bidder_name, overall_status, result_json) VALUES ({p}, {p}, {p}, {p}, {p}, {p})",
            [_id(), tender_pk, submission_pk, bidder.bidder, bidder.overall_status, _json(to_dict(bidder))],
        )

    def _insert_verdict(self, criterion_pk: str, submission_pk: str, evidence_pk: str | None, verdict) -> None:
        self._execute(
            "INSERT INTO verdicts (id, criterion_id, submission_id, evidence_id, status, reason, extracted_value, confidence, rule_trace, manual_review_reason, human_reviewer_action, tender_source_json, bidder_source_json, model_version, rule_version) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})",
            [
                _id(),
                criterion_pk,
                submission_pk,
                evidence_pk,
                verdict.status,
                verdict.reason,
                verdict.extracted_value,
                verdict.confidence,
                verdict.rule_trace,
                verdict.manual_review_reason,
                verdict.human_reviewer_action,
                _json(to_dict(verdict.tender_source)),
                _json(to_dict(verdict.bidder_source)),
                "",
                "v1",
            ],
        )

    def _insert_review_task(self, tender_pk: str, submission_pk: str | None, criterion_pk: str | None, reason: str, priority: str, source_file: str) -> None:
        self._execute(
            "INSERT INTO review_tasks (id, tender_id, submission_id, criterion_id, reason, priority, source_file, status) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})",
            [_id(), tender_pk, submission_pk, criterion_pk, reason, priority, source_file, "open"],
        )

    def _insert_award(self, tender_pk: str, submission_map: dict[str, str], result: EvaluationResult) -> None:
        outputs = agent_outputs_payload(result, [])
        award_pack = outputs["post_tender"]["award_pack"]
        winner = award_pack.get("recommended_bidder") or ""
        self._execute(
            "INSERT INTO awards (id, tender_id, winning_submission_id, status, justification, award_json) VALUES ({p}, {p}, {p}, {p}, {p}, {p})",
            [_id(), tender_pk, submission_map.get(winner), award_pack.get("status", "not_ready"), f"Recommended bidder: {winner}" if winner else "No award recommendation.", _json(award_pack)],
        )

    def _insert_agent_outputs(self, tender_pk: str, result: EvaluationResult, audit_events: list[AuditEvent]) -> None:
        payload = agent_outputs_payload(result, audit_events)
        for stage in ["pre_tender", "tender_stage", "post_tender"]:
            self._execute(
                "INSERT INTO agent_outputs (id, tender_id, stage, agent_name, output_key, output_json) VALUES ({p}, {p}, {p}, {p}, {p}, {p})",
                [_id(), tender_pk, stage, "stage_summary", stage, _json(payload[stage])],
            )
        for agent in result.agents:
            self._execute(
                "INSERT INTO agent_outputs (id, tender_id, stage, agent_name, output_key, output_json) VALUES ({p}, {p}, {p}, {p}, {p}, {p})",
                [_id(), tender_pk, agent.stage, agent.name, ",".join(agent.outputs), _json(to_dict(agent))],
            )

    def _insert_audit_event(self, tender_pk: str, event: AuditEvent) -> None:
        self._execute(
            "INSERT INTO audit_events (id, tender_id, actor, event_type, event_json) VALUES ({p}, {p}, {p}, {p}, {p})",
            [_id(), tender_pk, "system", event.step, _json(to_dict(event))],
        )

    def _execute(self, sql: str, params: list[Any] | None = None) -> None:
        params = params or []
        self.conn.execute(_sql(sql, self.is_postgres), params)

    def _fetch_one(self, sql: str, params: list[Any] | None = None):
        cursor = self.conn.execute(_sql(sql, self.is_postgres), params or [])
        return cursor.fetchone()

    def _count(self, table: str, tender_pk: str) -> int:
        return int(self._fetch_one(f"SELECT COUNT(*) FROM {table} WHERE tender_id = {{p}}", [tender_pk])[0])

    def _count_join_submission(self, table: str, tender_pk: str) -> int:
        return int(self._fetch_one(f"SELECT COUNT(*) FROM {table} t JOIN submissions s ON s.id = t.submission_id WHERE s.tender_id = {{p}}", [tender_pk])[0])


def persist_evaluation_run(
    workspace_name: str,
    workspace_path: Path,
    tender_docs: list[Document],
    bidder_docs: dict[str, list[Document]],
    tender_chunks: list[RagChunk],
    bidder_chunks: dict[str, list[RagChunk]],
    criteria: list[Criterion],
    evidence_by_bidder: dict[str, list[Evidence]],
    result: EvaluationResult,
    audit_events: list[AuditEvent],
) -> AuditEvent:
    try:
        repo = ProcurementRepository()
        repo.persist_run(workspace_name, workspace_path, tender_docs, bidder_docs, tender_chunks, bidder_chunks, criteria, evidence_by_bidder, result, audit_events)
        db = os.getenv("DATABASE_URL") or str(repo.sqlite_path)
        repo.close()
        return AuditEvent("database_persistence", workspace_name, {"passed": True, "database": db})
    except Exception as exc:
        return AuditEvent("database_persistence", workspace_name, {"passed": False, "error": str(exc)})


def workspace_persistence_summary(workspace_name: str) -> dict[str, int | str]:
    repo = ProcurementRepository()
    try:
        return repo.workspace_summary(workspace_name)
    finally:
        repo.close()


def _id() -> str:
    return str(uuid.uuid4())


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _sql(sql: str, is_postgres: bool) -> str:
    placeholder = "%s" if is_postgres else "?"
    return sql.replace("{p}", placeholder)


def _postgres_schema() -> list[str]:
    return [
        "CREATE EXTENSION IF NOT EXISTS pgcrypto",
        """
        CREATE TABLE IF NOT EXISTS tenders (
            id UUID PRIMARY KEY,
            workspace_name TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',
            storage_uri TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
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
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS vendors (
            id UUID PRIMARY KEY,
            legal_name TEXT NOT NULL UNIQUE,
            gstin TEXT,
            pan TEXT,
            msme_status TEXT,
            debarment_declaration BOOLEAN,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS submissions (
            id UUID PRIMARY KEY,
            tender_id UUID NOT NULL REFERENCES tenders(id),
            vendor_id UUID NOT NULL REFERENCES vendors(id),
            bidder_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'submitted',
            submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(tender_id, vendor_id)
        )
        """,
        """
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
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        *_shared_postgres_tables(),
    ]


def _shared_postgres_tables() -> list[str]:
    return [
        """
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
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
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
            version INTEGER NOT NULL DEFAULT 1
        )
        """,
        """
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
            notes TEXT NOT NULL DEFAULT ''
        )
        """,
        """
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
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS review_tasks (
            id UUID PRIMARY KEY,
            tender_id UUID NOT NULL REFERENCES tenders(id),
            submission_id UUID,
            criterion_id UUID,
            reason TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'high',
            source_file TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open',
            reviewer_action TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bidder_results (
            id UUID PRIMARY KEY,
            tender_id UUID NOT NULL REFERENCES tenders(id),
            submission_id UUID NOT NULL REFERENCES submissions(id),
            bidder_name TEXT NOT NULL,
            overall_status TEXT NOT NULL,
            result_json TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS awards (
            id UUID PRIMARY KEY,
            tender_id UUID NOT NULL REFERENCES tenders(id),
            winning_submission_id UUID,
            status TEXT NOT NULL DEFAULT 'pending_approval',
            justification TEXT NOT NULL,
            award_json TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS contracts (
            id UUID PRIMARY KEY,
            award_id UUID NOT NULL REFERENCES awards(id),
            contract_number TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',
            delivery_terms TEXT NOT NULL DEFAULT '',
            performance_security_expiry DATE,
            contract_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_outputs (
            id UUID PRIMARY KEY,
            tender_id UUID NOT NULL REFERENCES tenders(id),
            stage TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            output_key TEXT NOT NULL,
            output_json TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            id UUID PRIMARY KEY,
            tender_id UUID,
            actor TEXT NOT NULL DEFAULT 'system',
            event_type TEXT NOT NULL,
            event_json TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    ]


def _sqlite_schema() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS tenders (
            id TEXT PRIMARY KEY,
            workspace_name TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',
            storage_uri TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE TABLE IF NOT EXISTS tender_documents (id TEXT PRIMARY KEY, tender_id TEXT NOT NULL, filename TEXT NOT NULL, storage_uri TEXT NOT NULL, checksum_sha256 TEXT NOT NULL, parser TEXT NOT NULL, parse_confidence REAL NOT NULL, page_count INTEGER NOT NULL, parsed_text TEXT NOT NULL, source_type TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS vendors (id TEXT PRIMARY KEY, legal_name TEXT NOT NULL UNIQUE, gstin TEXT, pan TEXT, msme_status TEXT, debarment_declaration INTEGER, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS submissions (id TEXT PRIMARY KEY, tender_id TEXT NOT NULL, vendor_id TEXT NOT NULL, bidder_name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'submitted', submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(tender_id, vendor_id))",
        "CREATE TABLE IF NOT EXISTS bid_documents (id TEXT PRIMARY KEY, tender_id TEXT NOT NULL, submission_id TEXT NOT NULL, filename TEXT NOT NULL, storage_uri TEXT NOT NULL, checksum_sha256 TEXT NOT NULL, parser TEXT NOT NULL, parse_confidence REAL NOT NULL, page_count INTEGER NOT NULL, parsed_text TEXT NOT NULL, source_type TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS document_chunks (id TEXT PRIMARY KEY, tender_id TEXT NOT NULL, document_id TEXT, submission_id TEXT, document_kind TEXT NOT NULL, source_file TEXT NOT NULL, page INTEGER NOT NULL, section TEXT NOT NULL, start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL, chunk_text TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS criteria (id TEXT PRIMARY KEY, tender_id TEXT NOT NULL, criterion_code TEXT NOT NULL, category TEXT NOT NULL, mandatory INTEGER NOT NULL, description TEXT NOT NULL, rule_type TEXT NOT NULL, threshold TEXT NOT NULL DEFAULT '', time_period TEXT NOT NULL DEFAULT '', accepted_evidence_json TEXT NOT NULL, source_file TEXT NOT NULL, source_page INTEGER NOT NULL, source_excerpt TEXT NOT NULL, source_section TEXT NOT NULL, source_chunk_id TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1)",
        "CREATE TABLE IF NOT EXISTS evidence (id TEXT PRIMARY KEY, criterion_id TEXT NOT NULL, submission_id TEXT NOT NULL, source_file TEXT NOT NULL, source_page INTEGER NOT NULL, source_section TEXT NOT NULL, source_chunk_id TEXT NOT NULL DEFAULT '', extracted_value TEXT NOT NULL, normalized_value TEXT NOT NULL DEFAULT '', confidence REAL NOT NULL, source_excerpt TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '')",
        "CREATE TABLE IF NOT EXISTS verdicts (id TEXT PRIMARY KEY, criterion_id TEXT NOT NULL, submission_id TEXT NOT NULL, evidence_id TEXT, status TEXT NOT NULL, reason TEXT NOT NULL, extracted_value TEXT NOT NULL DEFAULT '', confidence REAL NOT NULL DEFAULT 0, rule_trace TEXT NOT NULL, manual_review_reason TEXT NOT NULL DEFAULT '', human_reviewer_action TEXT NOT NULL DEFAULT '', tender_source_json TEXT NOT NULL, bidder_source_json TEXT NOT NULL, model_version TEXT NOT NULL DEFAULT '', rule_version TEXT NOT NULL DEFAULT 'v1', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS review_tasks (id TEXT PRIMARY KEY, tender_id TEXT NOT NULL, submission_id TEXT, criterion_id TEXT, reason TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'high', source_file TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open', reviewer_action TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS bidder_results (id TEXT PRIMARY KEY, tender_id TEXT NOT NULL, submission_id TEXT NOT NULL, bidder_name TEXT NOT NULL, overall_status TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS awards (id TEXT PRIMARY KEY, tender_id TEXT NOT NULL, winning_submission_id TEXT, status TEXT NOT NULL DEFAULT 'pending_approval', justification TEXT NOT NULL, award_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS contracts (id TEXT PRIMARY KEY, award_id TEXT NOT NULL, contract_number TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'draft', delivery_terms TEXT NOT NULL DEFAULT '', performance_security_expiry TEXT, contract_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS agent_outputs (id TEXT PRIMARY KEY, tender_id TEXT NOT NULL, stage TEXT NOT NULL, agent_name TEXT NOT NULL, output_key TEXT NOT NULL, output_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS audit_events (id TEXT PRIMARY KEY, tender_id TEXT, actor TEXT NOT NULL DEFAULT 'system', event_type TEXT NOT NULL, event_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
    ]
