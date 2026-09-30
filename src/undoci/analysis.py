"""Budgeted, dependency-aware reduction. Never assume monotonic failures."""

from __future__ import annotations

import math
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from undoci.config import Config, action_dependencies, digest
from undoci.data import Report, Trial
from undoci.runner import Runner


def reduce_actions(
    actions: list[str], dependencies: dict[str, set[str]], reproduces: Callable[[list[str]], bool]
) -> tuple[list[str], bool]:
    """ddmin plus a single-removal sweep; the callback may raise StopIteration on budget."""
    current = actions.copy()

    def prune(keep):
        selected = set(keep)
        while True:
            invalid = {item for item in selected if not dependencies.get(item, set()) <= selected}
            if not invalid:
                return [item for item in current if item in selected]
            selected -= invalid

    try:
        granularity = 2
        while len(current) >= 2:
            chunk = math.ceil(len(current) / granularity)
            changed = False
            for start in range(0, len(current), chunk):
                candidate = prune(current[:start] + current[start + chunk :])
                if reproduces(candidate):
                    current = candidate
                    granularity = max(2, granularity - 1)
                    changed = True
                    break
            if not changed:
                if granularity >= len(current):
                    break
                granularity = min(len(current), granularity * 2)
        # Explicit last sweep covers singleton -> empty and dependency pruning.
        index = 0
        while index < len(current):
            candidate = prune(current[:index] + current[index + 1 :])
            if reproduces(candidate):
                current, index = candidate, 0
            else:
                index += 1
        return current, True
    except StopIteration:
        return current, False


def analyze(
    config: Config,
    path: Path,
    output: Path,
    *,
    minimize: bool = True,
    selected: list[str] | None = None,
    progress=None,
    runner_factory=Runner,
) -> tuple[Report, Path]:
    started = time.monotonic()
    run_id = uuid.uuid4().hex[:12]
    directory = output.resolve() / run_id
    directory.mkdir(parents=True, exist_ok=False)
    all_ids = [req.id for req in config.actions]
    ids = all_ids if selected is None else selected
    if not set(ids) <= set(all_ids) or len(ids) != len(set(ids)):
        raise ValueError("replay contains unknown or duplicate action IDs")
    if ids != [item for item in all_ids if item in ids]:
        raise ValueError("replay action order differs from configuration")
    runner = runner_factory(config, path.parent, directory, run_id, progress)
    report = Report(
        config.name,
        run_id,
        datetime.now(UTC).isoformat(),
        str(path),
        digest(path),
        original_actions=ids.copy(),
    )
    report.reduced_actions = ids.copy()
    dependencies = action_dependencies(config)
    cache: dict[tuple[str, ...], Trial] = {}
    search_errors: list[str] = []

    def trial(actions: list[str], *, fresh=False, reserve=0):
        key = tuple(actions)
        if not fresh and key in cache:
            return cache[key]
        if len(report.trials) >= config.analysis.max_trials - reserve:
            raise StopIteration
        result = runner.run(actions)
        report.trials.append(result)
        cache[key] = result
        return result

    try:
        initial = trial(ids)
        report.status = "error" if initial.status == "invalid" else initial.status
        report.signature = initial.signature
        if initial.status != "regression":
            return report, directory
        # Validate repeatability before spending the budget locating a boundary.
        for _ in range(config.analysis.confirmations - 1):
            repeated = trial(ids, fresh=True)
            if repeated.status != "regression" or repeated.signature != initial.signature:
                report.status = "inconclusive"
                report.notes.append("The original failure did not repeat with the same signature.")
                return report, directory
        report.confirmed = True
        if not minimize:
            report.reduction = "disabled"
            return report, directory
        reserve = config.analysis.confirmations
        # Scan prefixes in order: later actions may repair an earlier incompatibility.
        first = trial([], reserve=reserve)
        if first.status == "regression":
            report.boundary_note = "Rollback already fails without candidate actions."
        elif first.status != "passed":
            report.boundary_note = "Empty-action rehearsal is invalid; boundary is inconclusive."
        else:
            preceding_valid = True
            for length in range(1, len(ids) + 1):
                result = trial(ids[:length], reserve=reserve)
                if result.status == "regression":
                    report.boundary_action = ids[length - 1]
                    report.boundary_note = (
                        "First failing prefix; all earlier prefixes passed."
                        if preceding_valid
                        else "First observed failure; earlier prefixes include unknown results."
                    )
                    break
                if result.status != "passed":
                    preceding_valid = False

        def reproduces(actions):
            result = trial(actions, reserve=reserve)
            if result.status == "error":
                search_errors.append(result.id)
            return result.status == "regression" and result.signature == initial.signature

        reduced, complete = reduce_actions(ids, dependencies, reproduces)
        report.reduced_actions = reduced
        report.reduction = "1-minimal" if complete else "budget-limited"
        if search_errors:
            report.reduction = "incomplete"
            report.notes.append(
                "Execution errors prevented a complete reduction check: " + ", ".join(search_errors)
            )
        for _ in range(config.analysis.confirmations):
            result = trial(reduced, fresh=True)
            if result.status != "regression" or result.signature != initial.signature:
                report.status, report.confirmed = "inconclusive", False
                report.reduction = "unstable"
                report.notes.append(
                    "The reduced scenario did not repeat; do not treat it as proven."
                )
                break
    except StopIteration:
        report.reduction = "budget-limited"
        report.notes.append("Trial budget exhausted. No global minimality claim is made.")
        if not report.confirmed and report.status == "regression":
            report.status = "inconclusive"
            report.notes.append("Not enough budget to confirm the original failure.")
    finally:
        report.duration = time.monotonic() - started
    return report, directory
