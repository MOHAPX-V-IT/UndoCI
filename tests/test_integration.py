import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from undoci.analysis import analyze
from undoci.cli import main
from undoci.config import load_config
from undoci.demo import create_demo
from undoci.report import write_report


@pytest.mark.integration
@pytest.mark.parametrize(
    ("scenario", "status", "retained"),
    [
        ("enum", "regression", ["create-order", "pay-order", "partial-refund"]),
        ("queue", "regression", ["enqueue-job"]),
        ("data-loss", "regression", []),
        ("safe", "passed", None),
    ],
)
def test_real_release_roundtrip(tmp_path, scenario, status, retained):
    path = create_demo(tmp_path / scenario, scenario)
    report, directory = analyze(load_config(path), path, tmp_path / "results")
    assert report.status == status, report.to_dict()
    if retained is not None:
        assert report.reduced_actions == retained
        assert report.confirmed
    assert not any(trial.cleanup_errors for trial in report.trials)
    write_report(report, directory)
    assert (directory / "junit.xml").is_file()
    if scenario == "enum":
        assert report.boundary_action == "partial-refund"
        assert (
            main(["replay", str(directory / "replay.json"), "--output", str(tmp_path / "replay")])
            == 1
        )


@pytest.mark.integration
def test_bad_candidate_is_not_reported_as_rollback_regression(tmp_path):
    path = create_demo(tmp_path / "demo")
    config = load_config(path)
    config.actions[0].path = "/missing-endpoint"
    report, _ = analyze(config, path, tmp_path / "out")
    assert report.status == "error"
    assert report.trials[0].status == "invalid"


@pytest.mark.integration
def test_missing_verify_environment_is_configuration_error(tmp_path, monkeypatch):
    monkeypatch.delenv("UNDOCI_TEST_MISSING_TOKEN", raising=False)
    path = create_demo(tmp_path / "demo", "safe")
    config = load_config(path)
    config.verify[0].headers = {"Authorization": "${UNDOCI_TEST_MISSING_TOKEN}"}
    report, _ = analyze(config, path, tmp_path / "out")
    assert report.status == "error"
    assert report.signature.endswith("missing-env")


@pytest.mark.integration
def test_startup_failure_has_evidence_and_cleanup(tmp_path):
    path = create_demo(tmp_path / "demo")
    config = load_config(path)
    config.target.old.run = [sys.executable, "-c", "raise SystemExit(7)"]
    report, _ = analyze(config, path, tmp_path / "out")
    assert report.status == "error"
    assert "startup-exit" in report.signature
    assert not report.trials[0].cleanup_errors


def test_demo_does_not_overwrite(tmp_path):
    create_demo(tmp_path)
    with pytest.raises(ValueError, match="already contains"):
        create_demo(tmp_path)


def test_replay_rejects_modified_config(tmp_path):
    path = create_demo(tmp_path / "demo")
    manifest = tmp_path / "replay.json"
    manifest.write_text(
        json.dumps(
            {"version": 1, "config_path": str(path), "config_digest": "wrong", "actions": []}
        ),
        encoding="utf-8",
    )
    assert main(["replay", str(manifest)]) == 2


@pytest.mark.docker
def test_postgres_compose_roundtrip(tmp_path):
    if os.environ.get("UNDOCI_DOCKER_TESTS") != "1":
        pytest.skip("set UNDOCI_DOCKER_TESTS=1 to build and test Docker images")
    root = Path(__file__).resolve().parents[1]
    for release in ["old", "new"]:
        subprocess.run(
            [
                "docker",
                "build",
                "-t",
                f"undoci-orders:{release}",
                "--build-arg",
                f"RELEASE={release}",
                str(root / "examples/postgres"),
            ],
            check=True,
            timeout=300,
        )
    path = root / "examples/postgres/undoci.yaml"
    report, _ = analyze(load_config(path), path, tmp_path / "out", minimize=False)
    assert report.status == "regression", report.to_dict()
    assert report.confirmed
    assert not any(trial.cleanup_errors for trial in report.trials)
