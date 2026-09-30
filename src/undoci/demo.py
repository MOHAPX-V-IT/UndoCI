from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import yaml


def demo_config(scenario="enum"):
    old = "compatible" if scenario == "safe" else "old"
    command = ["${UNDOCI_PYTHON}", "${UNDOCI_CONFIG_DIR}/app.py", "--version"]
    result = {
        "version": 1,
        "name": {
            "enum": "The refund that breaks rollback",
            "safe": "A compatible rollback",
            "queue": "The job the old worker cannot read",
            "data-loss": "The rollback that silently loses money",
        }[scenario],
        "target": {
            "kind": "process",
            "old": {"run": [*command, old]},
            "new": {"run": [*command, "new"]},
        },
        "setup": [
            {
                "id": "seed-order",
                "method": "POST",
                "path": "/orders",
                "body": {"amount": 100},
                "expect": {"status": 201},
            }
        ],
        "baseline": [
            {
                "id": "old-can-read",
                "path": "/orders",
                "expect": {"assertions": [{"pointer": "", "op": "length", "value": 1}]},
            }
        ],
        "actions": [
            {
                "id": "write-note",
                "method": "POST",
                "path": "/notes",
                "body": {"text": "unrelated"},
                "expect": {"status": 201},
            },
            {
                "id": "create-order",
                "method": "POST",
                "path": "/orders",
                "body": {"amount": 500},
                "expect": {"status": 201},
                "capture": {"order_id": "/id"},
            },
            {"id": "pay-order", "method": "POST", "path": "/orders/{{order_id}}/pay"},
            {
                "id": "partial-refund",
                "method": "POST",
                "path": "/orders/{{order_id}}/refund",
                "depends_on": ["pay-order"],
            },
            {"id": "another-note", "method": "POST", "path": "/notes", "expect": {"status": 201}},
        ],
        "candidate": [{"id": "new-can-read", "path": "/orders"}],
        "verify": [
            {
                "id": "old-still-reads",
                "path": "/orders",
                "expect": {"assertions": [{"pointer": "/0/amount", "op": "eq", "value": 100}]},
            }
        ],
        "analysis": {"max_trials": 40, "confirmations": 2},
    }
    if scenario == "queue":
        result["actions"] = [
            result["actions"][0],
            {"id": "enqueue-job", "method": "POST", "path": "/jobs", "expect": {"status": 201}},
            result["actions"][-1],
        ]
        result["candidate"] = [{"id": "new-reads-jobs", "path": "/jobs"}]
        result["verify"] = [{"id": "old-worker-drains", "method": "POST", "path": "/drain"}]
    elif scenario == "data-loss":
        result["actions"] = [result["actions"][0], result["actions"][-1]]
        result["lifecycle"] = {
            "rollback": [{"run": ["${UNDOCI_PYTHON}", "${UNDOCI_CONFIG_DIR}/app.py", "--damage"]}]
        }
    return result


def create_demo(directory: Path, scenario="enum") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    destinations = [directory / "app.py", directory / "undoci.yaml"]
    if any(path.exists() for path in destinations):
        raise ValueError(
            "demo destination already contains app.py or undoci.yaml; choose a new folder"
        )
    destinations[0].write_text(
        files("undoci").joinpath("templates/app.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    destinations[1].write_text(
        yaml.safe_dump(demo_config(scenario), sort_keys=False), encoding="utf-8"
    )
    return destinations[1]
