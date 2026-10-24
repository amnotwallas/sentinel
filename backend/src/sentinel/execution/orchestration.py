"""Fenced, resumable execution orchestration without persistence or HTTP coupling."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sentinel.catalog.definitions import DefinitionValidationError
from sentinel.catalog.environments import EnvironmentValidationError
from sentinel.execution.attempts import ResponseArtifact
from sentinel.execution.domain import (
    AttemptState,
    DispatchCertainty,
    Lease,
    PreparationErrorCode,
    TransportOutcome,
)
from sentinel.execution.ports import (
    NO_CANCELLATION,
    CancellableTransportAdapter,
    CancellationSignal,
    OrchestrationStore,
    PinnedAttempt,
    TraceLifecycle,
    TransportResult,
)
from sentinel.execution.preparation import PreparationError, prepare_request, request_fingerprint
from sentinel.regression.evaluator import (
    EvaluationDefinition,
    EvaluationInputError,
    EvaluationObservation,
    EvaluationResult,
    RedactionPolicy,
    evaluate,
)
from sentinel.regression.policy import ValidatedRegressionPolicy
from sentinel.security.definition_policy import (
    validate_environment_document,
    validate_test_definition,
)
from sentinel.security.secrets import SecretResolver

_SAFE_REPLAY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_TERMINAL_ATTEMPT_STATES = frozenset(
    {
        AttemptState.RESPONSE_RECEIVED,
        AttemptState.TRANSPORT_FAILED,
        AttemptState.FAILED,
        AttemptState.INDETERMINATE,
    }
)


def replay_allowed(method: str, unsafe_replay_acknowledged: bool) -> bool:
    return method.upper() in _SAFE_REPLAY_METHODS or unsafe_replay_acknowledged


class ExecutionOrchestrator:
    """Advance one durable execution to a terminal state under its live job lease."""

    def __init__(
        self,
        store: OrchestrationStore,
        transport: CancellableTransportAdapter,
        secrets_resolver: SecretResolver,
        traces: TraceLifecycle,
        *,
        attempt_ids: Callable[[], UUID] = uuid4,
        evaluation_ids: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] | None = None,
        artifact_retention: timedelta = timedelta(days=7),
    ) -> None:
        self.store = store
        self.transport = transport
        self.secrets_resolver = secrets_resolver
        self.traces = traces
        self.attempt_ids = attempt_ids
        self.evaluation_ids = evaluation_ids
        self.clock = clock or (lambda: datetime.now(UTC))
        self.artifact_retention = artifact_retention

    def run(
        self,
        lease: Lease,
        cancellation: CancellationSignal = NO_CANCELLATION,
    ) -> None:
        while True:
            cancellation.raise_if_cancelled()
            work = self.store.acquire_next(lease, attempt_id=self.attempt_ids())
            cancellation.raise_if_cancelled()
            if work is None:
                self.store.complete_execution(lease)
                return
            state = work.attempt.state
            if state == AttemptState.PREPARED:
                try:
                    environment = validate_environment_document(work.environment_document)
                    definition = validate_test_definition(work.test_definition)
                    fingerprint = request_fingerprint(environment, definition)
                    request = prepare_request(environment, definition, self.secrets_resolver)
                except PreparationError as error:
                    cancellation.raise_if_cancelled()
                    done = self.store.fail_preparation(
                        work.attempt.id, lease, self._preparation_code(error.code)
                    )
                    if done:
                        return
                    continue
                except (DefinitionValidationError, EnvironmentValidationError):
                    cancellation.raise_if_cancelled()
                    done = self.store.fail_preparation(
                        work.attempt.id, lease, PreparationErrorCode.REQUEST_INVALID
                    )
                    if done:
                        return
                    continue

                active_trace = self.traces.start(
                    execution_id=work.execution_id,
                    attempt_id=work.attempt.id,
                    method=request.method,
                    headers=request.headers,
                )
                request = replace(request, headers=active_trace.headers)
                result: TransportResult | None = None
                try:
                    cancellation.raise_if_cancelled()
                    self.store.checkpoint_dispatch(
                        work.attempt.id,
                        lease,
                        fingerprint=fingerprint,
                        trace_id=active_trace.trace_id,
                        span_id=active_trace.span_id,
                    )
                    cancellation.raise_if_cancelled()
                    result = self.transport.dispatch_cancellable(request, cancellation)
                finally:
                    active_trace.end(
                        status_code=result.status_code if result is not None else None,
                        outcome=result.outcome if result is not None else None,
                        certainty=result.certainty if result is not None else None,
                    )
                assert result is not None
                cancellation.raise_if_cancelled()
                done = self._persist_result(work.attempt.id, lease, result)
                cancellation.raise_if_cancelled()
                if done:
                    return
                continue

            if state == AttemptState.DISPATCHING:
                try:
                    definition = validate_test_definition(work.test_definition)
                    request_document = definition.document["request"]
                    method = (
                        request_document["method"]
                        if isinstance(request_document, Mapping)
                        else None
                    )
                except (DefinitionValidationError, KeyError, TypeError):
                    method = None
                if isinstance(method, str) and replay_allowed(
                    method, work.unsafe_replay_acknowledged
                ):
                    cancellation.raise_if_cancelled()
                    self.store.schedule_replay(
                        work.attempt.id, lease, successor_id=self.attempt_ids()
                    )
                    continue
                cancellation.raise_if_cancelled()
                self.store.mark_indeterminate(work.attempt.id, lease)
                return

            if state == AttemptState.RESPONSE_RECEIVED and work.result_contract_version == 1:
                try:
                    evaluation_result = self._evaluate(work)
                except (DefinitionValidationError, EvaluationInputError):
                    self.store.fail_evaluation(work.attempt.id, lease)
                    return
                done = self.store.persist_evaluation(
                    work.attempt.id,
                    lease,
                    evaluation_result,
                    evaluation_ids=tuple(
                        self.evaluation_ids() for _ in evaluation_result.evaluations
                    ),
                )
                cancellation.raise_if_cancelled()
                if done:
                    return
                continue

            if state in _TERMINAL_ATTEMPT_STATES:
                cancellation.raise_if_cancelled()
                if self.store.resume_terminal(work.attempt.id, lease):
                    return
                continue

            if state == AttemptState.REPLAY_SCHEDULED:
                continue
            raise RuntimeError("unsupported_attempt_state")

    @staticmethod
    def _evaluate(work: PinnedAttempt) -> EvaluationResult:
        if work.response_artifact is None or work.snapshot_at is None:
            raise EvaluationInputError("response_snapshot_missing")
        validated = validate_test_definition(work.test_definition)
        document = validated.to_document()
        comparison_policy = document.get("comparison_policy")
        assertions = document.get("assertions")
        redaction = document.get("redaction")
        if not isinstance(comparison_policy, dict) or not isinstance(assertions, list):
            raise EvaluationInputError("malformed_definition")
        if not isinstance(redaction, dict):
            raise EvaluationInputError("malformed_redaction")
        policy = ValidatedRegressionPolicy(
            assertions=assertions,
            comparison_policy=comparison_policy,
            policy_fingerprint=validated.policy_fingerprint,
        )
        redaction_pointers = redaction.get("json_pointers", [])
        redaction_headers = redaction.get("header_names", [])
        if not isinstance(redaction_pointers, list) or not isinstance(redaction_headers, list):
            raise EvaluationInputError("malformed_redaction")
        if any(not isinstance(value, str) for value in redaction_pointers + redaction_headers):
            raise EvaluationInputError("malformed_redaction")
        headers: list[tuple[str, str]] = []
        for name, value in work.response_artifact.headers.items():
            if not isinstance(name, str) or not isinstance(value, str):
                raise EvaluationInputError("malformed_observation")
            headers.append((name, value))
        observation = EvaluationObservation(
            status_code=work.response_artifact.status_code,
            headers=tuple(headers),
            body_kind=work.response_artifact.body_kind,
            body_content=work.response_artifact.body_content,
            truncated=work.response_artifact.truncated,
            redaction_unavailable=work.response_artifact.redaction_unavailable,
            expired=work.snapshot_at >= work.response_artifact.expires_at,
        )
        return evaluate(
            EvaluationDefinition(
                policy=policy,
                redaction=RedactionPolicy(
                    json_pointers=tuple(cast(str, value) for value in redaction_pointers),
                    header_names=frozenset(cast(str, value) for value in redaction_headers),
                ),
            ),
            observation,
            baseline=work.baseline,
            duration_ms=work.attempt.duration_ms,
        )

    def _persist_result(self, attempt_id: UUID, lease: Lease, result: TransportResult) -> bool:
        if result.outcome in {
            TransportOutcome.RESPONSE_RECEIVED,
            TransportOutcome.RESPONSE_LIMIT_EXCEEDED,
        }:
            artifact = self._artifact(attempt_id, result)
            if artifact is None:
                raise RuntimeError("accepted_response_missing_artifact")
            return self.store.record_response(attempt_id, lease, artifact, outcome=result.outcome)
        artifact = (
            self._artifact(attempt_id, result)
            if result.certainty == DispatchCertainty.RESPONSE_RECEIVED
            and result.outcome
            in {
                TransportOutcome.REDIRECT_DENIED,
                TransportOutcome.READ_TIMEOUT,
                TransportOutcome.READ_FAILURE,
            }
            else None
        )
        return self.store.record_transport_failure(
            attempt_id,
            lease,
            outcome=result.outcome,
            certainty=result.certainty,
            not_sent_proof=result.not_sent_proof,
            redirect_code=result.redirect_rejection_code,
            artifact=artifact,
        )

    def _artifact(self, attempt_id: UUID, result: TransportResult) -> ResponseArtifact | None:
        if result.status_code is None:
            return None
        now = self.clock()
        body_kind = result.body_kind
        body_content = result.body_content
        if body_kind is None and result.body is not None:
            try:
                body_content = result.body.decode("utf-8")
                body_kind = "text"
            except UnicodeDecodeError:
                body_content = None
        return ResponseArtifact(
            attempt_id=attempt_id,
            status_code=result.status_code,
            headers=dict(result.headers),
            body_kind=body_kind,
            body_content=body_content,
            source_bytes_captured=result.source_bytes_captured,
            truncated=result.truncated,
            redaction_unavailable=result.redaction_unavailable,
            recorded_at=now,
            expires_at=now + self.artifact_retention,
        )

    @staticmethod
    def _preparation_code(code: str) -> PreparationErrorCode:
        try:
            return PreparationErrorCode(code)
        except ValueError:
            return PreparationErrorCode.REQUEST_INVALID
