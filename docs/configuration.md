# Configuration reference

`undoci validate undoci.yaml` checks the versioned contract without executing commands.
Unknown fields, duplicate YAML keys, unresolved capture references and forward dependencies
are rejected. See [JSON Schema](undoci.schema.json) for every field and constraint.

Paths inside commands are resolved from the configuration file's directory. CLI output paths
are resolved from the current working directory. Commands have no implicit shell: use arrays
and pass arguments separately. Shell syntax is never evaluated unless you explicitly start a shell.

## Required contract

```yaml
version: 1
name: My release
target: # choose process or compose below
  kind: process
  old: {run: ["python", "old.py"]}
  new: {run: ["python", "new.py"]}
baseline:
  - {id: before, path: /items}
actions:
  - {id: create, method: POST, path: /items, expect: {status: 201}}
candidate:
  - {id: upgraded, path: /items}
verify:
  - {id: restored, path: /items}
```

`baseline`, `actions`, `candidate` and `verify` must each contain at least one step.
`setup` is optional and executes only on the initial old release. This is where you seed
records and capture stable fixture IDs. `baseline` checks the old version; `candidate` checks
the new version after the workload; `verify` checks the old version after rollback.

## Process driver

```yaml
target:
  kind: process
  old:
    run: ["${UNDOCI_PYTHON}", "old.py", "--port", "${UNDOCI_PORT}"]
    cwd: "${UNDOCI_CONFIG_DIR}"
    env: {MODE: old}
    ready_path: /health
    ready_status: 200
    timeout: 30
  new:
    run: ["${UNDOCI_PYTHON}", "new.py", "--port", "${UNDOCI_PORT}"]
    ready_path: /health
    timeout: 30
```

The service binds to `127.0.0.1:UNDOCI_PORT`. A free port is selected per trial; the usual
close-before-bind race still applies; run on a dedicated test host to avoid competing listeners.
Store your test data under `UNDOCI_TRIAL_DIR`.
The runner launches services in process groups and terminates them between releases.
On Windows it uses `taskkill /T /F`; on POSIX it terminates the process group.

The process driver provides lifecycle management, **not an OS security sandbox**.
Your application can still access whatever the current OS user can access.

## Compose driver

```yaml
target:
  kind: compose
  file: compose.yaml
  service: api
  old_image: my-app:old
  new_image: my-app:new
  container_port: 8000
  ready_path: /health
  ready_status: 200
  timeout: 120
```

Use `image: ${UNDOCI_IMAGE}` for the target service in the Compose file. Do not declare
its host ports; UndoCI supplies one ephemeral loopback port. Dependent services start
with the old app and remain running throughout each trial. The target service is stopped
and replaced on transitions. Images must already be built or pullable. Multiple app services
are not switched atomically in this version; the configured `service` is the release boundary.

Each trial uses `undoci-<run>-<trial>` as the project name. Cleanup runs
`docker compose down --volumes --remove-orphans` only for that generated project. Fixed-name
and external volumes/networks, fixed container names, privileged mode, host networking and
writable bind mounts are unsupported. Docker daemon availability is required.

## Lifecycle hooks

```yaml
lifecycle:
  prepare:
    - run: ["${UNDOCI_PYTHON}", "fixtures.py", "${UNDOCI_TRIAL_DIR}"]
      timeout: 20
  upgrade:
    - run: ["${UNDOCI_PYTHON}", "migrate.py", "up"]
  rollback:
    - run: ["${UNDOCI_PYTHON}", "migrate.py", "down"]
  cleanup: []
```

Hooks run on the **host**, not automatically inside the app container. Commands receive the
trial environment. For an in-container command, explicitly invoke `docker compose` with
the generated `UNDOCI_PROJECT`, your Compose file and any needed overrides.

Lifecycle order:

1. Create an empty trial directory and run `prepare`.
2. Start old, wait for readiness, run `setup`, then `baseline`.
3. Stop old, run `upgrade`, start new, wait for readiness.
4. Run selected `actions`, then `candidate` checks.
5. Stop new, run `rollback`, start old, wait for readiness.
6. Run `verify` checks.
7. Stop services, run `cleanup`, collect logs, remove Compose resources.

Cleanup is attempted even when a check fails or the run is interrupted. Cleanup failure
makes the overall trial an execution error. Logs and trial directories remain for inspection;
their contents may include fixture data. No automatic deletion of local evidence is performed.

## Requests and assertions

```yaml
- id: create-item
  method: POST
  path: /items
  headers:
    Authorization: "Bearer ${TEST_API_TOKEN}"
  body: {title: example}
  timeout: 10
  expect:
    status: 201
    assertions:
      - {pointer: /id, op: exists}
      - {pointer: /title, op: eq, value: example}
  capture:
    item_id: /id
```

HTTP defaults: `GET`, status `200`, 10-second timeout, no redirects and no proxy environment
inheritance. Paths must start with one `/`. Responses over 5 MB fail explicitly. Response
bodies and authorization headers are not recorded in the report.

Pointers follow JSON Pointer notation: `/items/0/id`, with `~1` for `/` and `~0` for `~`.
An empty pointer selects the entire response. Supported operators:

| Operator | Meaning |
|---|---|
| `eq` / `ne` | Equal / unequal, including JSON value type |
| `exists` | Pointer exists; set `value: false` to require absence |
| `contains` | Membership in an array/object or substring in a string |
| `length` | Array, string or object length |
| `gte` / `lte` | Greater / less than or equal |

`${NAME}` reads an environment variable; missing values fail. `{{item_id}}` reads an earlier
response capture. A whole-value capture in a JSON body preserves its type. Embedded captures
become text. Capture names must be unique.

## Dependencies and useful oracles

```yaml
- id: pay
  method: POST
  path: /orders/{{order_id}}/pay
- id: refund
  method: POST
  path: /orders/{{order_id}}/refund
  depends_on: [pay]
```

Capture references automatically create dependencies between actions. Declare additional
business prerequisites with `depends_on`. The reducer removes dependents with their missing
prerequisite and preserves original order. Independent action reordering is not explored.

Candidate and rollback verification checks must not depend on removable action captures or
declare dependencies. Use invariant endpoints, collections, or stable `setup` captures.
For example, an assertion that there are *exactly six* orders can make smaller workloads
invalid; a check that all remaining orders are readable is usually more useful for reduction.

## Environment and logs

Built-ins: `UNDOCI_TRIAL_DIR`, `UNDOCI_CONFIG_DIR`, `UNDOCI_PROJECT`, `UNDOCI_PYTHON`,
`UNDOCI_PORT`, `UNDOCI_BASE_URL`, `UNDOCI_VERSION`; Compose also sets `UNDOCI_IMAGE`.
Version is `old` or `new`. Port/base URL are available once allocated (before process startup,
after Compose publishes its port). Reserved names cannot be set through top-level `env`.

Top-level `env` values can reference variables inherited from the parent process, not other
entries in that same mapping. Use `redact_env: [MY_CUSTOM_SECRET]` for extra redaction.
Values whose environment keys contain TOKEN, SECRET, PASSWORD, API_KEY or CREDENTIAL are
automatically redacted from saved command/service logs. Redaction is literal and best effort;
transformed secrets, files, and arbitrary application data are not covered.

Logs retain at most 64 KB per command/service. Raw process output temporarily lives in
OS-managed temporary files while a process runs. Avoid logging sensitive data in fixtures.

## Analysis and replay

```yaml
analysis:
  max_trials: 40
  confirmations: 2
```

The budget includes the first run, repeat confirmations, prefix search, reductions and final
confirmation runs. Search results are cached within a run; confirmation bypasses the cache.
Prefixes are scanned linearly because a later operation may repair an incompatibility.
An earlier invalid prefix makes the boundary inconclusive, explicitly labeled in the report.

Reduction retains the original failure signature. Different failures and invalid workloads
are not counted as reproductions. `1-minimal` means no single action removal with dependent
pruning preserved that signature in the tested scenarios; it does not mean globally minimal.

Replay manifests store action IDs, original configuration path, SHA-256 of the YAML, and the
expected signature. Move the repository with `undoci replay replay.json --config new/path.yaml`.
Configuration changes require `--allow-config-change`. Pin application source, images and
external dependencies yourself. A passing replay means the selected regression was not found;
a different rollback failure returns an inconclusive result.
