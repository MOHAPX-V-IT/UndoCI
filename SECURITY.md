# Security and execution boundaries

UndoCI executes application processes and hooks specified in the configuration. A YAML file
is executable project configuration: review it as you would a CI workflow or shell script.
Do not run configurations from untrusted repositories with privileged credentials.

The process driver is not a security sandbox. Child applications inherit the caller's
environment, including credentials. Use a dedicated test environment with limited credentials.
The Compose driver isolates names and persistence but does not make Docker a hostile-code sandbox.

## Disposable state

Use `UNDOCI_TRIAL_DIR` for local state and project-scoped volumes for Compose. Never point
prepare/upgrade/rollback/cleanup hooks at production. Host hooks can execute arbitrary code;
Compose isolation checks do not constrain what a host hook can do.

Compose checks reject external/fixed-name volumes and networks, container names, privileged
services, host networking, writable host mounts and user-defined published ports. Images
may still make outbound requests. Replace payments, email and other irreversible external
effects with controlled test doubles.

## Evidence and redaction

HTTP response bodies and request headers are omitted from reports. Known secret environment
values are literally redacted in saved process/command logs. Custom keys can be declared in
`redact_env`. This does not cover encoded values, secrets in arbitrary config fields, data files
written by your application, or every possible log format.

Trial directories may contain a database, application files and logs. Do not publish the
entire evidence directory without inspection. Even `report.json` contains your config path,
scenario names, step IDs and potentially application-specific assertion pointers.

Raw process output uses OS-managed temporary files while commands run. Final saved logs are
bounded, but raw output can consume disk while a process is active. Hooks should finish without
daemonizing children, especially on Windows, where descendants of already-exited parents cannot
always be discovered reliably by `taskkill`.

## Reporting a vulnerability

If this repository has private vulnerability reporting enabled on its hosting platform,
use that channel. Otherwise contact the repository maintainer privately before publishing
sensitive details. This source distribution does not invent a maintainer email address.
