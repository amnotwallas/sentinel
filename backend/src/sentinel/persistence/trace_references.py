"""Transactional trace-reference persistence; no Tempo or target I/O belongs here."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from sentinel.persistence.models import (
    ExecutionItemRow,
    ExecutionRow,
    JobRow,
    TestAttemptRow,
    TraceReferenceRow,
)
from sentinel.telemetry.evidence import MAX_LINKED_MATCHES, build_linked_evidence
from sentinel.telemetry.ports import LinkedTrace
from sentinel.telemetry.references import CorrelationSource, TraceReferenceStatus, TraceRelation

TRACE_WINDOW = timedelta(seconds=60)
MAX_EVIDENCE_BYTES = 65536
_TRACE_ID = re.compile(r"[0-9a-f]{32}")
_SPAN_ID = re.compile(r"[0-9a-f]{16}")
_EVIDENCE_KEYS = frozenset(
    {
        "schema_version",
        "primary_span_found",
        "trace_span_count",
        "error_span_count",
        "services",
        "deployments",
        "linked_match_count",
        "context_continuity",
        "comparison_anchor",
    }
)


def _identity(value: str, pattern: re.Pattern[str]) -> str:
    if pattern.fullmatch(value) is None or set(value) == {"0"}:
        raise ValueError("invalid trace identity")
    return value


def validate_evidence(evidence: dict[str, object] | None) -> dict[str, object] | None:
    if evidence is None:
        return None
    if evidence.get("schema_version") != 1 or set(evidence) - _EVIDENCE_KEYS:
        raise ValueError("invalid trace evidence")
    encoded = json.dumps(
        evidence, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    if len(encoded) > MAX_EVIDENCE_BYTES:
        raise ValueError("trace evidence exceeds bound")
    return evidence


class TraceReferenceRepository:
    """All methods use the caller's transaction and are safe to retry."""

    @staticmethod
    def create_primary(
        session: Session,
        *,
        attempt: TestAttemptRow,
        item: ExecutionItemRow,
        execution: ExecutionRow,
        trace_id: str,
        span_id: str,
        now: datetime,
    ) -> TraceReferenceRow:
        trace_id = _identity(trace_id, _TRACE_ID)
        span_id = _identity(span_id, _SPAN_ID)
        existing = session.scalar(
            select(TraceReferenceRow)
            .where(
                TraceReferenceRow.attempt_id == attempt.id,
                TraceReferenceRow.relation == TraceRelation.PRIMARY,
            )
            .with_for_update()
        )
        if existing is not None:
            if existing.trace_id != trace_id or existing.span_id != span_id:
                raise ValueError("primary trace identity is immutable")
            return existing
        row = TraceReferenceRow(
            id=uuid4(),
            attempt_id=attempt.id,
            execution_item_id=item.id,
            execution_id=execution.id,
            project_id=item.project_id,
            relation=TraceRelation.PRIMARY,
            trace_id=trace_id,
            span_id=span_id,
            correlation_source=CorrelationSource.SENTINEL_CONTEXT,
            status=TraceReferenceStatus.PENDING,
            deadline_at=now + TRACE_WINDOW,
            lookup_attempt_count=0,
            evidence_schema_version=1,
            evidence_json=None,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
        return row

    @staticmethod
    def create_linked(
        session: Session,
        *,
        attempt: TestAttemptRow,
        item: ExecutionItemRow,
        execution: ExecutionRow,
        trace_id: str,
        span_id: str | None,
        deadline_at: datetime,
        now: datetime,
        evidence: dict[str, object] | None = None,
        status: TraceReferenceStatus = TraceReferenceStatus.PENDING,
        checked_at: datetime | None = None,
        lookup_attempt_count: int = 0,
    ) -> TraceReferenceRow:
        trace_id = _identity(trace_id, _TRACE_ID)
        if span_id is not None:
            span_id = _identity(span_id, _SPAN_ID)
        evidence = validate_evidence(evidence)
        existing = session.scalar(
            select(TraceReferenceRow)
            .where(
                TraceReferenceRow.attempt_id == attempt.id,
                TraceReferenceRow.relation == TraceRelation.LINKED,
                TraceReferenceRow.trace_id == trace_id,
            )
            .with_for_update()
        )
        if existing is not None:
            return existing
        row = TraceReferenceRow(
            id=uuid4(),
            attempt_id=attempt.id,
            execution_item_id=item.id,
            execution_id=execution.id,
            project_id=item.project_id,
            relation=TraceRelation.LINKED,
            trace_id=trace_id,
            span_id=span_id,
            correlation_source=CorrelationSource.BAGGAGE_ATTRIBUTE_SEARCH,
            status=status,
            first_checked_at=checked_at,
            last_checked_at=checked_at,
            deadline_at=deadline_at,
            lookup_attempt_count=lookup_attempt_count,
            evidence_schema_version=1,
            evidence_json=evidence,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
        return row

    @staticmethod
    def persist_linked_search(
        session: Session,
        *,
        reference: TraceReferenceRow,
        matches: tuple[LinkedTrace, ...],
        now: datetime,
    ) -> int:
        """Persist at most sixteen exact-search results, idempotently."""
        attempt = session.scalar(
            select(TestAttemptRow)
            .where(TestAttemptRow.id == reference.attempt_id)
            .with_for_update()
        )
        item = session.scalar(
            select(ExecutionItemRow)
            .where(
                ExecutionItemRow.id == reference.execution_item_id,
                ExecutionItemRow.execution_id == reference.execution_id,
                ExecutionItemRow.project_id == reference.project_id,
            )
            .with_for_update()
        )
        execution = session.scalar(
            select(ExecutionRow)
            .where(
                ExecutionRow.id == reference.execution_id,
                ExecutionRow.project_id == reference.project_id,
            )
            .with_for_update()
        )
        if attempt is None or item is None or execution is None:
            raise ValueError("trace reference scope is incomplete")

        existing = list(
            session.scalars(
                select(TraceReferenceRow)
                .where(
                    TraceReferenceRow.attempt_id == reference.attempt_id,
                    TraceReferenceRow.relation == TraceRelation.LINKED,
                )
                .with_for_update()
            )
        )
        by_trace = {row.trace_id: row for row in existing}
        candidates = {
            match.trace_id.lower(): match
            for match in matches
            if _TRACE_ID.fullmatch(match.trace_id.lower()) is not None
            and set(match.trace_id.lower()) != {"0"}
        }
        for trace_id in sorted(candidates):
            if trace_id == reference.trace_id or trace_id in by_trace:
                row = by_trace.get(trace_id)
                if row is not None and row.status == TraceReferenceStatus.PENDING:
                    row.status = TraceReferenceStatus.AVAILABLE
                    row.first_checked_at = row.first_checked_at or now
                    row.last_checked_at = now
                    row.lookup_attempt_count = max(row.lookup_attempt_count, 1)
                continue
            if len(by_trace) >= MAX_LINKED_MATCHES:
                break
            match = candidates[trace_id]
            row = TraceReferenceRepository.create_linked(
                session,
                attempt=attempt,
                item=item,
                execution=execution,
                trace_id=trace_id,
                span_id=None,
                deadline_at=reference.deadline_at,
                now=now,
                evidence=build_linked_evidence(match.services),
                status=TraceReferenceStatus.AVAILABLE,
                checked_at=now,
                lookup_attempt_count=1,
            )
            by_trace[trace_id] = row
        return len(by_trace)

    @staticmethod
    def latest_compatible_primary(
        session: Session, *, reference: TraceReferenceRow
    ) -> TraceReferenceRow | None:
        """Find the latest included primary from the same pinned execution scope."""
        item = session.get(ExecutionItemRow, reference.execution_item_id)
        execution = session.get(ExecutionRow, reference.execution_id)
        if item is None or execution is None:
            return None
        return session.scalar(
            select(TraceReferenceRow)
            .join(TestAttemptRow, TestAttemptRow.id == TraceReferenceRow.attempt_id)
            .join(ExecutionItemRow, ExecutionItemRow.id == TraceReferenceRow.execution_item_id)
            .join(ExecutionRow, ExecutionRow.id == TraceReferenceRow.execution_id)
            .where(
                TraceReferenceRow.id != reference.id,
                TraceReferenceRow.project_id == reference.project_id,
                TraceReferenceRow.relation == TraceRelation.PRIMARY,
                TraceReferenceRow.status == TraceReferenceStatus.AVAILABLE,
                TestAttemptRow.included_in_verdict.is_(True),
                TestAttemptRow.replay_successor_id.is_(None),
                ExecutionItemRow.test_case_id == item.test_case_id,
                ExecutionItemRow.test_case_revision_id == item.test_case_revision_id,
                ExecutionItemRow.test_case_revision_version == item.test_case_revision_version,
                ExecutionRow.project_id == execution.project_id,
                ExecutionRow.environment_id == execution.environment_id,
                ExecutionRow.environment_revision_id == execution.environment_revision_id,
                ExecutionRow.source_type == execution.source_type,
                ExecutionRow.source_id == execution.source_id,
                ExecutionRow.source_revision_id == execution.source_revision_id,
            )
            .order_by(TraceReferenceRow.updated_at.desc(), TraceReferenceRow.id.desc())
            .limit(1)
        )

    @staticmethod
    def finalize_primary(
        session: Session,
        *,
        attempt: TestAttemptRow,
        terminal_at: datetime,
        execution_id: UUID,
    ) -> TraceReferenceRow | None:
        row = session.scalar(
            select(TraceReferenceRow)
            .where(
                TraceReferenceRow.attempt_id == attempt.id,
                TraceReferenceRow.relation == TraceRelation.PRIMARY,
                TraceReferenceRow.execution_id == execution_id,
            )
            .with_for_update()
        )
        if row is None:
            return None
        row.deadline_at = terminal_at + TRACE_WINDOW
        row.updated_at = terminal_at
        existing = session.scalar(
            select(JobRow).where(JobRow.trace_reference_id == row.id).with_for_update()
        )
        if existing is None:
            session.add(
                JobRow(
                    id=uuid4(),
                    kind="correlate_trace",
                    subject_id=row.execution_id,
                    trace_reference_id=row.id,
                    state="pending",
                    available_at=terminal_at,
                    delivery_count=0,
                    max_deliveries=3,
                    created_at=terminal_at,
                )
            )
            session.flush()
        return row
