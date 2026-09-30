"""One fresh rehearsal, from baseline through rollback, without resetting state midway."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from undoci.config import Config
from undoci.data import Event, Trial
from undoci.requests import StepFailure, perform
from undoci.runtime import Runtime


class Runner:
    def __init__(
        self,
        config: Config,
        root: Path,
        directory: Path,
        run_id: str,
        progress: Callable[[str], None] | None = None,
    ):
        self.config, self.root, self.directory, self.run_id = config, root, directory, run_id
        self.progress = progress or (lambda _: None)
        self.count = 0

    def run(self, actions: list[str]) -> Trial:
        self.count += 1
        trial = Trial(f"trial-{self.count:03}", actions.copy())
        started = time.monotonic()
        phase, step = "prepare", "runtime"
        runtime = None
        captures = {}
        self.progress(f"{trial.id}  {len(actions)} action(s)")

        def event(current_phase, current_step, function):
            nonlocal phase, step
            phase, step = current_phase, current_step
            before = time.monotonic()
            try:
                detail = function() or "completed"
            except Exception as exc:
                trial.events.append(
                    Event(phase, step, "failed", time.monotonic() - before, runtime.safe(str(exc)))
                )
                raise
            trial.events.append(
                Event(phase, step, "passed", time.monotonic() - before, runtime.safe(str(detail)))
            )

        def requests(current_phase, items):
            for request in items:
                event(
                    current_phase,
                    request.id,
                    lambda req=request: perform(
                        runtime.client, runtime.base_url, req, runtime.env, captures
                    ),
                )

        try:
            runtime = Runtime(
                self.config,
                self.root,
                self.directory / trial.id,
                f"undoci-{self.run_id}-{self.count}",
            )
            event("prepare", "hooks", lambda: runtime.hooks("prepare"))
            event("baseline", "start-old", lambda: runtime.start("old"))
            requests("setup", self.config.setup)
            requests("baseline", self.config.baseline)
            event("upgrade", "stop-old", runtime.stop)
            event("upgrade", "hooks", lambda: runtime.hooks("upgrade"))
            event("upgrade", "start-new", lambda: runtime.start("new"))
            requests("actions", [req for req in self.config.actions if req.id in actions])
            requests("candidate", self.config.candidate)
            event("rollback", "stop-new", runtime.stop)
            event("rollback", "hooks", lambda: runtime.hooks("rollback"))
            event("rollback", "start-old", lambda: runtime.start("old"))
            requests("verify", self.config.verify)
        except StepFailure as exc:
            if exc.code in {"missing-env", "missing-capture", "invalid-path", "config"}:
                trial.status = "error"
            elif phase in ("rollback", "verify"):
                trial.status = "regression"
            elif phase in ("actions", "candidate"):
                trial.status = "invalid"
            else:
                trial.status = "error"
            trial.signature = f"{phase}/{step}/{exc.code}"
            trial.message = runtime.safe(str(exc)) if runtime else str(exc)
        except Exception as exc:
            trial.status = "error"
            trial.signature = f"{phase}/{step}/internal"
            trial.message = f"{type(exc).__name__}: {exc}"
            if runtime:
                trial.message = runtime.safe(trial.message)
        finally:
            if runtime:
                before = time.monotonic()
                trial.cleanup_errors = runtime.close()
                trial.events.append(
                    Event(
                        "cleanup",
                        "resources",
                        "failed" if trial.cleanup_errors else "passed",
                        time.monotonic() - before,
                        "; ".join(trial.cleanup_errors) or "resources released",
                    )
                )
                if trial.cleanup_errors:
                    trial.status = "error"
                    trial.message += " Cleanup failed; inspect this trial's logs."
            trial.duration = time.monotonic() - started
        self.progress(
            f"          {trial.status.upper()}  {trial.duration:.2f}s"
            + (f"  {trial.signature}" if trial.signature else "")
        )
        return trial
