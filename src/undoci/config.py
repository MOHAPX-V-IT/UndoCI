"""Strict, versioned configuration. Loading a file never executes its commands."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

CAPTURE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Command(Model):
    run: list[str] = Field(min_length=1)
    timeout: float = Field(default=60, gt=0, le=3600)
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reserved_environment(self):
        if any(key.upper().startswith("UNDOCI_") for key in self.env):
            raise ValueError("UNDOCI_* environment variables are reserved")
        if not self.run[0].strip():
            raise ValueError("command executable cannot be empty")
        return self


class Service(Command):
    ready_path: str = "/health"
    ready_status: int = Field(default=200, ge=100, le=599)


class ProcessTarget(Model):
    kind: Literal["process"] = "process"
    old: Service
    new: Service


class ComposeTarget(Model):
    kind: Literal["compose"]
    file: str
    service: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
    old_image: str
    new_image: str
    container_port: int = Field(default=8000, ge=1, le=65535)
    ready_path: str = "/health"
    ready_status: int = Field(default=200, ge=100, le=599)
    timeout: float = Field(default=120, gt=0, le=3600)


class Assertion(Model):
    pointer: str = ""
    op: Literal["eq", "ne", "contains", "exists", "length", "gte", "lte"] = "eq"
    value: Any = None


class Expect(Model):
    status: int = Field(default=200, ge=100, le=599)
    assertions: list[Assertion] = Field(default_factory=list)


class Request(Model):
    id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]*$")
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] = "GET"
    path: str
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = None
    expect: Expect = Field(default_factory=Expect)
    capture: dict[str, str] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    timeout: float = Field(default=10, gt=0, le=300)

    @model_validator(mode="after")
    def local_path(self):
        if not self.path.startswith("/") or self.path.startswith("//"):
            raise ValueError("request paths must be relative to the test service, starting with /")
        for name in self.capture:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise ValueError(f"invalid capture name: {name}")
        for pointer in [*self.capture.values(), *(a.pointer for a in self.expect.assertions)]:
            if pointer and not pointer.startswith("/"):
                raise ValueError("JSON pointers must be empty or start with /")
        return self


class Lifecycle(Model):
    prepare: list[Command] = Field(default_factory=list)
    upgrade: list[Command] = Field(default_factory=list)
    rollback: list[Command] = Field(default_factory=list)
    cleanup: list[Command] = Field(default_factory=list)


class Analysis(Model):
    max_trials: int = Field(default=40, ge=1, le=1000)
    confirmations: int = Field(default=2, ge=1, le=10)


class Config(Model):
    version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=160)
    target: Annotated[ProcessTarget | ComposeTarget, Field(discriminator="kind")]
    env: dict[str, str] = Field(default_factory=dict)
    redact_env: list[str] = Field(default_factory=list)
    lifecycle: Lifecycle = Field(default_factory=Lifecycle)
    setup: list[Request] = Field(default_factory=list)
    baseline: list[Request] = Field(min_length=1)
    actions: list[Request] = Field(min_length=1)
    candidate: list[Request] = Field(min_length=1)
    verify: list[Request] = Field(min_length=1)
    analysis: Analysis = Field(default_factory=Analysis)

    @model_validator(mode="after")
    def dependencies(self):
        if any(k.upper().startswith("UNDOCI_") for k in self.env):
            raise ValueError("UNDOCI_* environment variables are reserved")
        ids: set[str] = set()
        captures: set[str] = set()
        for phase in (self.setup, self.baseline, self.actions, self.candidate, self.verify):
            for req in phase:
                if req.id in ids:
                    raise ValueError(f"duplicate step id: {req.id}")
                unknown = set(req.depends_on) - ids
                if unknown:
                    raise ValueError(f"{req.id}: dependencies must precede the step: {unknown}")
                refs = set(CAPTURE.findall(req.model_dump_json(exclude={"capture"})))
                if refs - captures:
                    raise ValueError(f"{req.id}: unknown captures {refs - captures}")
                for name in req.capture:
                    if name in captures:
                        raise ValueError(f"capture names must be unique: {name}")
                    captures.add(name)
                ids.add(req.id)
        # Analysis removes actions. Its oracles must remain meaningful without them.
        action_captures = {key for step in self.actions for key in step.capture}
        for req in [*self.candidate, *self.verify]:
            refs = set(CAPTURE.findall(req.model_dump_json()))
            if refs & action_captures or req.depends_on:
                raise ValueError("candidate/verify checks must not depend on removable actions")
        return self


class UniqueLoader(yaml.SafeLoader):
    """Reject duplicate keys rather than silently discarding checks."""


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def load_config(path: Path) -> Config:
    content = path.read_text(encoding="utf-8")
    if len(content) > 2_000_000:
        raise ValueError("configuration exceeds 2 MB")
    return Config.model_validate(yaml.load(content, Loader=UniqueLoader))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def action_dependencies(config: Config) -> dict[str, set[str]]:
    owners = {key: step.id for step in config.actions for key in step.capture}
    action_ids = {step.id for step in config.actions}
    return {
        step.id: (set(step.depends_on) & action_ids)
        | {owners[key] for key in CAPTURE.findall(step.model_dump_json()) if key in owners}
        for step in config.actions
    }
