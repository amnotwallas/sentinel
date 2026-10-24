"""Application ports for baseline promotion and activation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from sentinel.catalog.changes import ChangeEvent
from sentinel.regression.baselines import (
    ActivationSummary,
    BaselineScope,
    BaselineSummary,
    ScopeState,
    SourceAssessment,
)


class BaselineRepository(Protocol):
    def get_scope(self, scope: BaselineScope, *, for_update: bool = False) -> ScopeState | None: ...

    def current_policy_fingerprint(self, scope: BaselineScope) -> str: ...

    def current_activation(self, scope: BaselineScope) -> ActivationSummary | None: ...

    def get_by_source_attempt(self, source_attempt_id: UUID) -> BaselineSummary | None: ...

    def get_initial_activation(self, baseline_id: UUID) -> ActivationSummary | None: ...

    def get(self, scope: BaselineScope, baseline_id: UUID) -> BaselineSummary | None: ...

    def get_source_assessment(
        self,
        scope: BaselineScope,
        source_attempt_id: UUID,
        *,
        current_policy_fingerprint: str,
    ) -> SourceAssessment | None: ...

    def list(
        self,
        scope: BaselineScope,
        *,
        after: tuple[int, UUID] | None,
        limit: int,
    ) -> Sequence[BaselineSummary]: ...

    def add_baseline(
        self, value: BaselineSummary, *, selected_values: dict[str, object]
    ) -> None: ...

    def add_activation(self, value: ActivationSummary) -> None: ...

    def close_current_activation(self, activation_id: UUID, *, at: datetime) -> None: ...


class BaselineUnitOfWork(Protocol):
    baselines: BaselineRepository

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def add_change(self, event: ChangeEvent) -> None: ...

    def commit(self) -> None: ...
