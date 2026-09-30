import yaml

from undoci.analysis import analyze, reduce_actions
from undoci.config import Config
from undoci.data import Trial
from undoci.demo import demo_config


def test_reduction_preserves_dependency_chain():
    actions = ["noise", "create", "pay", "refund", "noise2"]
    deps = {"pay": {"create"}, "refund": {"pay", "create"}}
    reduced, complete = reduce_actions(actions, deps, lambda ids: "refund" in ids)
    assert reduced == ["create", "pay", "refund"]
    assert complete


def test_migration_only_reduces_to_empty():
    assert reduce_actions(["a", "b"], {}, lambda _: True) == ([], True)


def test_budget_returns_best_known():
    calls = 0

    def predicate(ids):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise StopIteration
        return True

    reduced, complete = reduce_actions(["a", "b", "c", "d"], {}, predicate)
    assert len(reduced) == 2
    assert not complete


def run_fake(tmp_path, outcome, *, budget=40, confirmations=2):
    raw = demo_config()
    raw["actions"] = [{"id": item, "path": "/"} for item in ["a", "b", "c", "d"]]
    raw["analysis"] = {"max_trials": budget, "confirmations": confirmations}
    config = Config.model_validate(raw)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    class FakeRunner:
        def __init__(self, *args):
            self.count = 0

        def run(self, actions):
            self.count += 1
            status, signature = outcome(actions, self.count)
            return Trial(f"trial-{self.count}", actions.copy(), status, signature)

    return analyze(config, path, tmp_path / "out", runner_factory=FakeRunner)[0]


def test_prefix_search_is_not_binary(tmp_path):
    # b breaks, c repairs, d breaks again: failures are not monotonic.
    report = run_fake(
        tmp_path,
        lambda a, _: (
            ("regression", "verify/read/status")
            if ("b" in a and "c" not in a) or "d" in a
            else ("passed", None)
        ),
    )
    assert report.boundary_action == "b"
    assert report.confirmed


def test_flaky_initial_run_is_inconclusive(tmp_path):
    report = run_fake(
        tmp_path,
        lambda _, count: ("regression", "verify/read/status") if count == 1 else ("passed", None),
    )
    assert report.status == "inconclusive"
    assert not report.confirmed


def test_other_failure_signature_cannot_replace_target(tmp_path):
    def outcome(actions, _):
        if "d" in actions:
            return "regression", "verify/target/status"
        if "b" in actions:
            return "regression", "verify/unrelated/status"
        return "passed", None

    report = run_fake(tmp_path, outcome)
    assert report.reduced_actions == ["d"]


def test_invalid_subsets_do_not_count_as_reproduction(tmp_path):
    def outcome(actions, _):
        if "d" in actions and "a" not in actions:
            return "invalid", "actions/d/status"
        if "d" in actions:
            return "regression", "verify/read/status"
        return "passed", None

    report = run_fake(tmp_path, outcome)
    assert report.reduced_actions == ["a", "d"]


def test_analysis_respects_budget(tmp_path):
    report = run_fake(tmp_path, lambda a, _: ("regression", "x"), budget=3)
    assert len(report.trials) <= 3
    assert report.reduction == "budget-limited"


def test_initial_workload_failure_is_error(tmp_path):
    report = run_fake(tmp_path, lambda _, count: ("invalid", "actions/a/status"))
    assert report.status == "error"


def test_unconfirmed_failure_with_tiny_budget_is_inconclusive(tmp_path):
    report = run_fake(tmp_path, lambda _, count: ("regression", "x"), budget=1)
    assert report.status == "inconclusive"
    assert not report.confirmed
