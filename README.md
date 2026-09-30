<p align="center">
  <img src="docs/assets/undoci-banner.png" alt="UndoCI — Ship forward. Know your way back." width="100%">
</p>

<p align="center">
  <strong>Find the write that breaks your rollback. Before your users do.</strong>
</p>

<p align="center">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-ffad42?style=flat-square&labelColor=17191c">
  <img alt="License MIT" src="https://img.shields.io/badge/license-MIT-ffad42?style=flat-square&labelColor=17191c">
  <img alt="Runs locally" src="https://img.shields.io/badge/runs-locally-ffad42?style=flat-square&labelColor=17191c">
  <img alt="Early release" src="https://img.shields.io/badge/status-early%20release-ffad42?style=flat-square&labelColor=17191c">
</p>

<p align="center">
  <a href="#see-it-break-in-under-a-minute">Quick start</a> ·
  <a href="#bring-your-own-application">Your application</a> ·
  <a href="docs/configuration.md">Configuration</a> ·
  <a href="docs/architecture.md">How it works</a> ·
  <a href="README.ru.md">Русский</a>
</p>

---

## Green deploy. Broken rollback.

Your new release passes its tests. It writes a new order status, changes a job payload, or migrates a field. Then you need to roll back.

The old container starts. Its health check passes. **It can no longer read the data your new release just wrote.**

UndoCI rehearses that exact situation in a disposable environment. It starts your previous release, establishes a baseline, upgrades, runs a workload, rolls back **without restoring the data**, and checks whether the previous release still works.

When it fails, UndoCI searches for the first failing action prefix and reduces the workload to a small, repeatable reproducer.

```text
OLD RELEASE      NEW RELEASE                         OLD RELEASE
    │                 │                                   │
    ├─ baseline       ├─ create-order                     ├─ health: OK
    │                 ├─ pay-order                        └─ GET /orders: 500
    │                 └─ partial-refund ◄── boundary
    └──── upgrade ────┴──────────── rollback ──────────────┘
                      Data stays. Code goes back.
```

## See it break in under a minute

Requires Python 3.11+. The local demo needs **no Docker, API keys, account, or external service**. Timing depends on your machine; analysis runs multiple fresh rehearsals.

Install from this repository (a registry release is not assumed):

```bash
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell instead: .\.venv\Scripts\Activate.ps1
python -m pip install -e .

undoci demo ./refund-demo
undoci run ./refund-demo/undoci.yaml
```

Expected result for the intentionally broken demo:

```text
REGRESSION
First failing prefix ends at: partial-refund
Retained actions: create-order, pay-order, partial-refund
```

The command intentionally exits with **1**: it found a rollback regression. Open the printed `report.html` path to inspect every rehearsal. Run the saved `replay.json` to reproduce the reduced case:

```bash
undoci replay .undoci/<run-id>/replay.json
```

Now try the compatible reader:

```bash
undoci demo ./safe-demo --scenario safe
undoci run ./safe-demo/undoci.yaml
# PASSED · exit 0
```

## From a failure to evidence

| Capability | What you get |
|---|---|
| Real release lifecycle | Old → new → old, preserving state between versions |
| Baseline and candidate checks | Separate invalid setup/workloads from rollback failures |
| First failing prefix | Ordered search that does not assume failures are monotonic |
| Dependency-aware reduction | Remove unrelated actions while preserving declared dependencies and captures |
| Repeat confirmation | Re-run failures in fresh environments; flag inconsistent results |
| Two execution drivers | Managed local processes or isolated Docker Compose projects |
| Portable evidence | Offline HTML, JSON, JUnit XML, Markdown summary, replay manifest |
| Bounded execution | Per-command and HTTP timeouts, trial budget, cleanup on interruption |
| Explicit assertions | HTTP status plus JSON Pointer checks, without an LLM judge |

<p align="center"><img src="docs/assets/report-preview.png" alt="UndoCI report showing a rollback failure, retained actions and rehearsal journal" width="100%"></p>

## Bring your own application

Start with a small, deterministic workflow. Configure how to launch your old and new releases, how to prepare isolated state, and which behaviors must survive a rollback.

```yaml
version: 1
name: Orders remain readable after rollback
target:
  kind: process
  old:
    run: ["${UNDOCI_PYTHON}", "old_server.py"]
  new:
    run: ["${UNDOCI_PYTHON}", "new_server.py"]

# Each process must listen on UNDOCI_PORT and store disposable state
# under UNDOCI_TRIAL_DIR. Both releases get the same directory in a trial.
baseline:
  - id: baseline-read
    path: /orders
actions:
  - id: create-order
    method: POST
    path: /orders
    body: {amount: 500}
    expect: {status: 201}
    capture: {order_id: /id}
  - id: refund-order
    method: POST
    path: /orders/{{order_id}}/refund
candidate:
  - id: new-reader
    path: /orders
verify:
  - id: old-reader
    path: /orders
```

This is an integration sketch, not a bundled server. Adapt paths, startup arguments and assertions to your API. `undoci demo` creates a complete runnable example, including payment before refund.

```bash
undoci validate undoci.yaml
undoci run undoci.yaml --max-trials 40
undoci run undoci.yaml --no-minimize
undoci schema --output undoci.schema.json
undoci doctor
```

Use lifecycle hooks for schema migrations and fixture seeding. Commands are argument arrays, executed without an implicit shell. Use `${ENV_VAR}` for environment values and `{{capture_name}}` for response captures. See the [complete configuration reference](docs/configuration.md).

### Docker Compose + PostgreSQL

The [PostgreSQL example](examples/postgres/README.md) runs two actual application images against a shared PostgreSQL volume. Each rehearsal gets its own Compose project; application replacement preserves the database, and final cleanup removes that project's containers, network and volumes.

```bash
docker build -t undoci-orders:old --build-arg RELEASE=old examples/postgres
docker build -t undoci-orders:new --build-arg RELEASE=new examples/postgres
undoci run examples/postgres/undoci.yaml
```

Use Docker Compose with `up --wait` support. Fixed resource names, external volumes/networks, writable host bind mounts, privileged containers and host networking are rejected. Use dedicated test configuration; see [security and isolation](SECURITY.md).

## Four demos. Four different lessons.

| Scenario | Run | Expected result |
|---|---|---|
| New enum value | `undoci demo enum-demo --scenario enum` | Old reader rejects a partially refunded order |
| Queue payload change | `undoci demo queue-demo --scenario queue` | Old worker cannot consume a newly written job |
| Destructive rollback | `undoci demo loss-demo --scenario data-loss` | Seeded data changes even without candidate actions |
| Compatible release | `undoci demo safe-demo --scenario safe` | Old reader accepts new state; checks pass |

After creating a demo, run `undoci run <directory>/undoci.yaml`. Queue behavior is demonstrated with a SQLite-backed job table, not a live external broker.

## Make rollback evidence a CI artifact

Install UndoCI from a checkout or a built wheel. No GitHub credentials are needed by the runner.

```yaml
- uses: actions/setup-python@v5
  with:
    python-version: "3.12"
- run: python -m pip install -e .
- name: Rehearse rollback
  run: undoci run path/to/undoci.yaml --output rollback-evidence
- name: Keep evidence even on failure
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: rollback-evidence
    path: rollback-evidence/
```

| Exit code | Meaning |
|---|---|
| `0` | Configured checks passed |
| `1` | Rollback regression found |
| `2` | Configuration, setup, candidate workload or cleanup error |
| `3` | Failure was inconsistent or replay produced a different failure |
| `130` | Interrupted; cleanup attempted |

Every run has its own folder. `latest.json` points to the latest completed report. The JUnit file contains one test case for the overall rehearsal verdict; the full trial journal lives in JSON and HTML.

## What the result actually proves

UndoCI checks **your declared contract** against **your configured workload**. It does not prove every possible rollback safe.

- **A health check is only readiness.** Add assertions for data, reads and workers that matter.
- **A 1-minimal scenario is not the globally shortest one.** No single removable action (with dependent actions pruned) still reproduces the matching failure in the explored runs. Budget-limited results are labeled.
- **Signatures are evidence identifiers, not root-cause proofs.** They identify the failing phase, step and assertion.
- **Repeatable is not deterministic by magic.** Seed randomness and isolate clocks/external services in your application when needed.
- **Invalid scenarios do not count as reproduced failures.** Removing a business prerequisite can make a reduction candidate invalid.
- **External effects are not reversible.** Use fakes for email, payments and third-party APIs. This is a test runner, not a production deployment tool.
- **Replay pins configuration content, not binaries.** Pin image digests and source revisions if you need reproducibility across machines.

This is an early release with a complete end-to-end workflow, not a claim of production certification. There is no telemetry, hosted control plane, automatic deployment or automatic code repair.

## Development

```bash
python -m pip install -e ".[dev]"
ruff check .
pytest -m "not docker"
python -m build
# With Docker running:
pytest -m docker
```

See [architecture](docs/architecture.md), [contributing](CONTRIBUTING.md), [security](SECURITY.md), and the [changelog](CHANGELOG.md). The repository includes cross-platform Python CI and a separate Docker integration job.

## Why another tool?

Migration runners help change your schema. Deployment systems can restore an old image. UndoCI asks the question between those two operations:

**Can that old image still do its job after the new release has been used?**

Use it alongside migration tooling, contract tests and deployment checks. The differentiator is the combined workflow: preserved state, rollback-specific assertions, ordered boundary discovery and a reduced replayable workload.

## License

[MIT](LICENSE). Build on it, contribute adapters, and bring a rollback bug we can reproduce.
