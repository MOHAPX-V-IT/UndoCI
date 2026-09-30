import json
import sys

import pytest

from undoci.analysis import analyze
from undoci.config import Command, ComposeTarget, Config, load_config
from undoci.demo import create_demo, demo_config
from undoci.requests import StepFailure
from undoci.runtime import Runtime


@pytest.fixture
def runtime(tmp_path):
    config = Config.model_validate(demo_config())
    instance = Runtime(config, tmp_path, tmp_path / "trial", "undoci-test-1")
    yield instance
    assert not instance.close()


def test_hook_timeout_is_bounded_and_logged(runtime):
    with pytest.raises(StepFailure) as error:
        runtime.command(
            Command(run=[sys.executable, "-c", "import time; time.sleep(20)"], timeout=0.2)
        )
    assert error.value.code == "timeout"
    assert (runtime.directory / "command-001.log").exists()


def test_hook_exit_error_does_not_echo_secret(runtime):
    command = Command(
        run=[
            sys.executable,
            "-c",
            "import os; print(os.environ['API_TOKEN']); raise SystemExit(9)",
        ],
        env={"API_TOKEN": "sensitive-test-marker"},
    )
    with pytest.raises(StepFailure) as error:
        runtime.command(command)
    log = (runtime.directory / "command-001.log").read_text(encoding="utf-8")
    assert "sensitive-test-marker" not in log
    assert "[REDACTED]" in log
    assert "sensitive-test-marker" not in str(error.value)


@pytest.mark.integration
def test_cleanup_failure_is_never_a_pass(tmp_path):
    path = create_demo(tmp_path / "demo", "safe")
    config = load_config(path)
    config.lifecycle.cleanup = [Command(run=[sys.executable, "-c", "raise SystemExit(1)"])]
    report, _ = analyze(config, path, tmp_path / "out")
    assert report.status == "error"
    assert report.trials[0].cleanup_errors


@pytest.mark.integration
def test_service_environment_does_not_bleed_between_releases(tmp_path):
    path = create_demo(tmp_path / "demo", "safe")
    config = load_config(path)
    for version, release in [("old", "compatible"), ("new", "new")]:
        service = getattr(config.target, version)
        service.run = [
            "${UNDOCI_PYTHON}",
            "-c",
            "import os,runpy,sys; print('ISOLATION='+os.getenv('ONLY_OLD','unset'),flush=True); "
            f"sys.argv=['app.py','--version','{release}']; runpy.run_path('app.py')",
        ]
    config.target.old.env = {"ONLY_OLD": "old-value"}
    report, directory = analyze(config, path, tmp_path / "out", minimize=False)
    assert report.status == "passed"
    new_logs = list((directory / "trial-001").glob("service-new-*.log"))
    assert "ISOLATION=unset" in new_logs[0].read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "unsafe",
    [
        {"volumes": {"data": {"external": True}}},
        {"volumes": {"data": {"name": "production"}}},
        {"networks": {"shared": {"external": True}}},
        {"services": {"api": {"container_name": "production-api"}}},
        {"services": {"api": {"network_mode": "host"}}},
        {"services": {"api": {"privileged": True}}},
        {"services": {"api": {"volumes": [{"type": "bind", "read_only": False}]}}},
        {"services": {"api": {"ports": [{"host_ip": "0.0.0.0", "published": "8000"}]}}},
        {"services": {"db": {"ports": [{"host_ip": "127.0.0.1", "published": "0"}]}}},
    ],
)
def test_compose_rejects_unisolated_resources(runtime, monkeypatch, unsafe):
    runtime.config.target = ComposeTarget(
        kind="compose", file="compose.yaml", service="api", old_image="old", new_image="new"
    )
    monkeypatch.setattr(runtime, "_compose", lambda *args, **kwargs: json.dumps(unsafe))
    with pytest.raises(StepFailure) as exc:
        runtime._compose_validate()
    assert exc.value.code == "isolation"


def test_compose_accepts_scoped_resources(runtime, monkeypatch):
    runtime.config.target = ComposeTarget(
        kind="compose", file="compose.yaml", service="api", old_image="old", new_image="new"
    )
    config = {
        "volumes": {"data": {"name": "undoci-test-1_data"}},
        "networks": {"default": {"name": "undoci-test-1_default"}},
        "services": {"api": {"ports": [{"host_ip": "127.0.0.1", "published": "0"}]}},
    }
    monkeypatch.setattr(runtime, "_compose", lambda *args, **kwargs: json.dumps(config))
    runtime._compose_validate()
