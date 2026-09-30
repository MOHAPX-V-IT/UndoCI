import httpx
import pytest

from undoci.config import Request
from undoci.requests import StepFailure, expand, json_equal, perform, pointer, redact


def test_pointer_escaping_and_arrays():
    assert pointer({"a/b": {"~": [7]}}, "/a~1b/~0/0") == 7
    with pytest.raises(KeyError):
        pointer([10], "/-1")
    with pytest.raises(KeyError):
        pointer([10], "/9")


def test_capture_keeps_json_type():
    assert expand({"id": "{{order}}"}, {}, {"order": 12}) == {"id": 12}
    assert expand("/orders/{{order}}", {}, {"order": 12}) == "/orders/12"
    assert expand("${TOKEN}", {"TOKEN": "abc"}) == "abc"
    assert expand("{{literal}}", {}, {"literal": "${SECRET}"}) == "${SECRET}"


def test_missing_values_fail_explicitly():
    with pytest.raises(StepFailure, match="environment variable"):
        expand("${MISSING}", {})
    with pytest.raises(StepFailure, match="capture"):
        expand("{{missing}}", {})


@pytest.mark.parametrize(
    ("op", "value"),
    [
        ("eq", 3),
        ("ne", 4),
        ("gte", 2),
        ("lte", 3),
        ("exists", True),
    ],
)
def test_assertions(op, value):
    req = Request.model_validate(
        {
            "id": "check",
            "path": "/",
            "expect": {"assertions": [{"pointer": "/number", "op": op, "value": value}]},
        }
    )
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"number": 3}))
    ) as client:
        perform(client, "http://test", req, {}, {})


def test_capture_and_headers():
    def handler(request):
        assert request.headers["Authorization"] == "Bearer fake"
        return httpx.Response(201, json={"id": 7, "items": ["a"]})

    req = Request.model_validate(
        {
            "id": "create",
            "path": "/orders",
            "method": "POST",
            "headers": {"Authorization": "Bearer ${TOKEN}"},
            "expect": {
                "status": 201,
                "assertions": [
                    {"pointer": "/items", "op": "contains", "value": "a"},
                    {"pointer": "/items", "op": "length", "value": 1},
                ],
            },
            "capture": {"id": "/id"},
        }
    )
    captures = {}
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        perform(client, "http://test", req, {"TOKEN": "fake"}, captures)
    assert captures == {"id": 7}


def test_failure_does_not_leak_response():
    req = Request(id="check", path="/")
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(500, text="secret-value"))
        ) as client,
        pytest.raises(StepFailure) as exc,
    ):
        perform(client, "http://test", req, {}, {})
    assert "secret-value" not in str(exc.value)
    assert exc.value.code == "status"


def test_bool_is_not_equal_to_integer():
    req = Request.model_validate(
        {"id": "check", "path": "/", "expect": {"assertions": [{"pointer": "/ok", "value": 1}]}}
    )
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"ok": True}))
        ) as client,
        pytest.raises(StepFailure),
    ):
        perform(client, "http://test", req, {}, {})


def test_redaction():
    assert (
        redact("token abc and xyz", {"API_TOKEN": "abc", "CUSTOM": "xyz"}, ["CUSTOM"])
        == "token [REDACTED] and [REDACTED]"
    )


def test_nested_json_equality_preserves_types():
    assert not json_equal({"items": [{"value": True}]}, {"items": [{"value": 1}]})
    assert json_equal({"items": [1, None, False]}, {"items": [1, None, False]})
    assert not json_equal([1], [1, 2])
