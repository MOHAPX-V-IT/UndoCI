from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Status = Literal["passed", "regression", "error", "invalid"]


@dataclass
class Event:
    phase: str
    step: str
    status: str
    duration: float
    detail: str = ""


@dataclass
class Trial:
    id: str
    actions: list[str]
    status: Status = "passed"
    signature: str | None = None
    message: str = ""
    duration: float = 0
    events: list[Event] = field(default_factory=list)
    cleanup_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Report:
    name: str
    run_id: str
    created_at: str
    config_path: str
    config_digest: str
    status: str = "error"
    trials: list[Trial] = field(default_factory=list)
    original_actions: list[str] = field(default_factory=list)
    reduced_actions: list[str] = field(default_factory=list)
    boundary_action: str | None = None
    boundary_note: str = "Not analyzed"
    reduction: str = "not-run"
    confirmed: bool = False
    signature: str | None = None
    duration: float = 0
    notes: list[str] = field(default_factory=list)
    schema_version: int = 1

    def to_dict(self):
        return asdict(self)
