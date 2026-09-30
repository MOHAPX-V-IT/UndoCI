# Real images. Real PostgreSQL. The same rollback bug.

From the repository root, install UndoCI, start Docker and build the two fixture releases:

```bash
docker build -t undoci-orders:old --build-arg RELEASE=old examples/postgres
docker build -t undoci-orders:new --build-arg RELEASE=new examples/postgres
undoci run examples/postgres/undoci.yaml
```

Expected: exit 1, failure at `verify/old-still-reads/status`, with the retained chain
`create-order → pay-order → partial-refund`. The original workload contains two unrelated notes.

The runner adds an ephemeral, loopback-only API port. PostgreSQL has no host port.
It uses a unique project per trial. Both API versions use the same named database volume
within that trial. The database is not restored when the app is rolled back.

The included database password is a public fixture value for disposable local environments.
Never reuse this Compose file or password for production.

To exercise the integration test:

```bash
# macOS / Linux
UNDOCI_DOCKER_TESTS=1 pytest -m docker -v
# PowerShell
$env:UNDOCI_DOCKER_TESTS = "1"
pytest -m docker -v
```

The test builds both images and runs the full lifecycle twice to confirm the rollback failure.
The CLI additionally performs boundary search and reduction unless `--no-minimize` is supplied.
Pin base image digests if you need reproducibility beyond this demo.
