"""Per-invocation planning intent without changing the public tool signatures."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal

from audyssey.contracts import SourcePlan

Purpose = Literal["separate", "generate"]


@dataclass(frozen=True)
class PlanningRequest:
    purpose: Purpose = "separate"
    audio_available: bool = True
    accepted: tuple[SourcePlan, ...] = ()


_request: ContextVar[PlanningRequest] = ContextVar(
    "planning_request", default=PlanningRequest()
)


def current_request() -> PlanningRequest:
    return _request.get()


@contextmanager
def planning_scope(
    purpose: Purpose, audio_available: bool, accepted: tuple[SourcePlan, ...] = ()
) -> Iterator[None]:
    token = _request.set(PlanningRequest(purpose, audio_available, accepted))
    try:
        yield
    finally:
        _request.reset(token)
