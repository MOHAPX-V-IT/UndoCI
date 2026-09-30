# Validation record — 2026-09-30

Verified locally on Windows with Python 3.14.6:

| Check | Result |
|---|---|
| `ruff check .` | Passed |
| `ruff format --check .` | Passed |
| `pytest -m "not docker" --cov=undoci` | 73 passed; 87% statement coverage |
| Four local release scenarios | Enum, queue, data-loss and safe outcomes verified |
| Reduced scenario replay | Original failure signature reproduced |
| Process timeout / cleanup / secret redaction | Covered by automated tests |
| Missing verification environment | Correctly reported as execution/configuration error |
| Compose isolation checks | Unsafe resource configurations rejected in unit tests |
| `docker compose config` | PostgreSQL example parsed successfully |
| `python -m build` | Source distribution and wheel built successfully |
| Clean-environment wheel installation | Installed package path verified; safe demo passed |
| Local documentation links and images | All resolved |
| Browser: 1440 × 1080, 390 × 844 | Report rendered without JS errors or horizontal overflow |
| Journal interactions | 14 trials; regression filter showed 6; disclosure and empty state worked |
| Independent report visual review | Pass; no material findings |

The enum showcase required 14 fresh rehearsals and retained `create-order`, `pay-order`,
`partial-refund` from five original actions. Measured elapsed time was 28.7 seconds on this
machine. This is a synthetic demo, not a performance guarantee.

## Not verified locally

Docker Desktop was installed and started, but Docker Engine queries timed out. The live
PostgreSQL integration test was therefore skipped. The repository contains a dedicated
Linux CI job that builds both images and runs that test when pushed; that hosted workflow
has not been executed as part of this local delivery.

Linux, macOS and other Python versions are represented in the CI matrix, not claimed as
locally tested. Expanded tables and keyboard interactions were reviewed in source; the
automated browser check exercised filter/disclosure/empty state and responsive overflow.
