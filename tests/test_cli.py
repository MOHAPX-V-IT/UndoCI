import json

from undoci.cli import main
from undoci.demo import create_demo


def test_schema_export_matches_parser(tmp_path):
    path = tmp_path / "schema.json"
    assert main(["schema", "--output", str(path)]) == 0
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["additionalProperties"] is False
    assert {"baseline", "candidate", "verify", "actions"} <= set(data["required"])


def test_validate_is_read_only(tmp_path):
    path = create_demo(tmp_path / "demo")
    assert main(["validate", str(path)]) == 0
    assert not (tmp_path / "demo" / "orders.sqlite").exists()


def test_invalid_yaml_returns_configuration_exit(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("name: [unfinished", encoding="utf-8")
    assert main(["validate", str(path)]) == 2


def test_invalid_config_does_not_echo_inputs(tmp_path, capsys):
    path = tmp_path / "invalid.yaml"
    path.write_text("unexpected: SECRET_MARKER_123\n", encoding="utf-8")
    assert main(["validate", str(path)]) == 2
    assert "SECRET_MARKER_123" not in capsys.readouterr().err


def test_invalid_replay_version(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"version": 99}', encoding="utf-8")
    assert main(["replay", str(path)]) == 2


def test_demo_command_and_overwrite_protection(tmp_path):
    assert main(["demo", str(tmp_path / "demo"), "--scenario", "safe"]) == 0
    assert main(["demo", str(tmp_path / "demo"), "--scenario", "safe"]) == 2
