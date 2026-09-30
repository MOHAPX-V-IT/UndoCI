import copy

import pytest
import yaml
from pydantic import ValidationError

from undoci.config import Config, action_dependencies, load_config
from undoci.demo import demo_config


def test_demo_contract_and_inferred_dependencies():
    config = Config.model_validate(demo_config())
    deps = action_dependencies(config)
    assert deps["partial-refund"] == {"pay-order", "create-order"}
    assert deps["pay-order"] == {"create-order"}


@pytest.mark.parametrize("scenario", ["enum", "safe", "queue", "data-loss"])
def test_all_demo_configs(scenario):
    Config.model_validate(demo_config(scenario))


@pytest.mark.parametrize(
    "change",
    [
        lambda c: c.update({"unknown": True}),
        lambda c: c.update({"verify": []}),
        lambda c: c.update({"env": {"UNDOCI_PORT": "1"}}),
        lambda c: c["actions"][0].update({"path": "https://external.test"}),
        lambda c: c["actions"][0].update({"path": "//external.test"}),
        lambda c: c["actions"][0].update({"path": "/{{missing}}"}),
        lambda c: c["actions"][0].update({"depends_on": ["partial-refund"]}),
        lambda c: c["verify"][0].update({"path": "/{{order_id}}"}),
        lambda c: c["analysis"].update({"max_trials": 0}),
        lambda c: c["actions"][1].update({"capture": {"order_id": "id"}}),
        lambda c: c["target"]["old"].update({"env": {"UNDOCI_PORT": "8000"}}),
        lambda c: c["actions"][0].update({"id": "old-can-read"}),
    ],
)
def test_rejects_invalid_contract(change):
    raw = copy.deepcopy(demo_config())
    change(raw)
    with pytest.raises(ValidationError):
        Config.model_validate(raw)


def test_duplicate_yaml_keys_rejected(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("name: first\nname: second\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate YAML"):
        load_config(path)


def test_yaml_cannot_construct_python(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("!!python/object/apply:os.system ['echo bad']", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        load_config(path)
