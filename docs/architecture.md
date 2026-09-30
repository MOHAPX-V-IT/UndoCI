# Architecture

UndoCI is a synchronous Python CLI with a deliberately small dependency surface: Pydantic,
PyYAML and HTTPX. No daemon, cloud service, LLM, browser or database is required by the tool.
The target application supplies its own persistence.

```text
CLI → strict config → analysis controller → fresh trial runner
                            │                     │
                            │                runtime driver
                            │                ├─ process tree
                            │                └─ Compose project
                            │                     │
                            │                HTTP assertions
                            ▼
                 JSON / HTML / JUnit / Markdown / replay
```

## Modules

| Module | Responsibility |
|---|---|
| `config.py` | Schema, safe YAML loading, validation, dependency inference |
| `runtime.py` | Host commands, service readiness, process trees, Compose resources |
| `requests.py` | Interpolation, JSON Pointer assertions, bounded HTTP, redaction |
| `runner.py` | A single old → new → old stateful rehearsal |
| `analysis.py` | Repeatability, first failing prefix, dependency-aware ddmin |
| `report.py` | Escaped offline artifacts and machine-readable verdicts |
| `demo.py` | Standalone runnable fixtures from packaged resources |
| `cli.py` | Commands, exit semantics, config-pinned replay |

## State isolation

Each trial has a unique directory and, for Compose, a unique project. State is fresh *between*
trials but preserved *within* a trial. Never restore a baseline snapshot on the rollback path:
that would erase the very writes being tested. Process fixtures must opt in by storing state
under `UNDOCI_TRIAL_DIR`; unmanaged databases cannot be automatically isolated.

## Outcomes

- `passed`: all declared checks passed.
- `regression`: rollback hook/startup or post-rollback verification failed.
- `invalid`: candidate action/precondition or candidate verification failed. At the top level
  this produces exit 2, not a claimed rollback regression.
- `error`: baseline, preparation, upgrade, internal execution or cleanup failure.
- `inconclusive` (report level): original or reduced result did not repeat, or replay found a
  different failure signature.

A signature identifies `phase/step/failure-code`. Matching signatures are a pragmatic reduction
oracle, not a theorem about causality. HTTP failures intentionally omit response bodies and
values. Hooks and readiness have their own error codes.

## Search

1. Run the full scenario and confirm its signature in fresh trials.
2. Run the empty action list, then prefixes in increasing order. Do not assume monotonicity.
3. Use dependency-aware delta debugging to remove chunks.
4. Sweep single removals (with transitive dependent pruning).
5. Confirm the reduced result with fresh trials.

Search is sequential and budgeted. A trial cache avoids duplicate subset executions during
search, but confirmation always bypasses it. Unvisited configurations remain unknown.
Linear boundary search costs up to N + 1 rehearsals; shrinking can require substantially more.

## Extension boundaries

To support a new runtime, implement the same lifecycle as `Runtime`: hooks, start, stop,
base URL, environment and close. A future runtime should preserve the same evidence and
cleanup semantics. Direct SQL assertions, broker-specific probes, concurrent workloads,
multi-service release switching and payload shrinking are not implemented in this release.
HTTP invariant endpoints and explicit host hooks can integrate existing project checks today.
