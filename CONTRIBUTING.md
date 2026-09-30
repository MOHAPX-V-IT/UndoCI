# Contributing

Start with a small rollback failure somebody can reproduce. Include an old release,
a new release, a fixture and a behavioral assertion. Synthetic data only.

## Local checks

```bash
python -m venv .venv
# Activate the environment for your shell.
python -m pip install -e ".[dev]"
ruff check .
ruff format --check .
pytest -m "not docker"
python -m build
```

Docker integration is opt-in: set `UNDOCI_DOCKER_TESTS=1` and run `pytest -m docker`.
The images are test fixtures, and their Compose resources are removed after each trial.

## Invariants to preserve

- No state restore between new-release writes and old-release verification.
- An invalid workload never counts as a rollback regression during reduction.
- No monotonicity assumption when locating the first failing prefix.
- Matching phase/step/assertion signature required when reducing.
- Fresh state between trials; final repeat confirmation bypasses caches.
- Every execution path attempts cleanup. Cleanup failures remain visible.
- Strict config parsing; no silent unknown keys or duplicate YAML keys.
- Escape all report content; keep offline HTML independent of third-party scripts.

Add a regression test for any change affecting verdicts, cleanup, isolation or replay.
Update the schema with `undoci schema --output docs/undoci.schema.json` after config changes.
Keep both READMEs accurate. Avoid claims about universal safety or globally shortest scenarios.

Open an issue with expected behavior, actual verdict, version and a redacted synthetic fixture.
Do not attach tokens, production snapshots, customer records or raw private logs.
