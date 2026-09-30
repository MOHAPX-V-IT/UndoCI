"""HTTP oracles, JSON pointers and typed capture interpolation."""

from __future__ import annotations

import os
import re
import time
from typing import Any

import httpx

from undoci.config import CAPTURE, Request

ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class StepFailure(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def expand(value: Any, env: dict[str, str], captures: dict[str, Any] | None = None) -> Any:
    captures = captures or {}
    if isinstance(value, str):
        match = CAPTURE.fullmatch(value)
        if match:
            if match[1] not in captures:
                raise StepFailure("missing-capture", f"capture unavailable: {match[1]}")
            return captures[match[1]]

        def capture(m):
            if m[1] not in captures:
                raise StepFailure("missing-capture", f"capture unavailable: {m[1]}")
            return str(captures[m[1]])

        def environment(m):
            if m[1] not in env:
                raise StepFailure("missing-env", f"environment variable unavailable: {m[1]}")
            return env[m[1]]

        # Expand env first so captured values are never reinterpreted as environment templates.
        return CAPTURE.sub(capture, ENV.sub(environment, value))
    if isinstance(value, list):
        return [expand(item, env, captures) for item in value]
    if isinstance(value, dict):
        return {key: expand(item, env, captures) for key, item in value.items()}
    return value


def pointer(document: Any, path: str) -> Any:
    current = document
    if not path:
        return current
    for component in path[1:].split("/"):
        key = component.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", key):
                raise KeyError(path)
            try:
                current = current[int(key)]
            except IndexError as exc:
                raise KeyError(path) from exc
        elif isinstance(current, dict):
            current = current[key]
        else:
            raise KeyError(path)
    return current


def json_equal(left: Any, right: Any) -> bool:
    """JSON comparisons must not treat True as 1, including nested containers."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            json_equal(value, right[key]) for key, value in left.items()
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            json_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


def perform(
    client: httpx.Client,
    base_url: str,
    request: Request,
    env: dict[str, str],
    captures: dict[str, Any],
) -> str:
    path = expand(request.path, env, captures)
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
        raise StepFailure("invalid-path", "expanded request path must start with a single /")
    deadline = time.monotonic() + request.timeout
    try:
        with client.stream(
            request.method,
            base_url + path,
            headers=expand(request.headers, env, captures),
            json=expand(request.body, env, captures),
            timeout=request.timeout,
        ) as response:
            if response.status_code != request.expect.status:
                raise StepFailure(
                    "status",
                    f"expected HTTP {request.expect.status}, received HTTP {response.status_code}",
                )
            chunks = bytearray()
            for chunk in response.iter_bytes():
                if time.monotonic() > deadline:
                    raise StepFailure("response-timeout", "response exceeded total time budget")
                chunks.extend(chunk)
                if len(chunks) > 5_000_000:
                    raise StepFailure("response-size", "response exceeds 5 MB")
    except httpx.HTTPError as exc:
        # URLs and server response bodies can contain secrets; do not include them.
        raise StepFailure("transport", f"HTTP request failed ({type(exc).__name__})") from exc
    document: Any = None
    if request.expect.assertions or request.capture:
        import json

        try:
            document = json.loads(chunks)
        except (ValueError, UnicodeError) as exc:
            raise StepFailure("json", "expected a JSON response") from exc
    for index, assertion in enumerate(request.expect.assertions):
        expected = expand(assertion.value, env, captures)
        try:
            actual = pointer(document, assertion.pointer)
            exists = True
        except KeyError:
            actual, exists = None, False
        passed = False
        try:
            if assertion.op == "exists":
                passed = exists == (True if expected is None else expected)
            elif exists:
                if assertion.op == "eq":
                    passed = json_equal(actual, expected)
                elif assertion.op == "ne":
                    passed = not json_equal(actual, expected)
                elif assertion.op == "contains":
                    passed = (
                        any(json_equal(item, expected) for item in actual)
                        if isinstance(actual, list)
                        else expected in actual
                    )
                elif assertion.op == "length":
                    passed = len(actual) == expected
                elif assertion.op == "gte":
                    passed = actual >= expected
                elif assertion.op == "lte":
                    passed = actual <= expected
        except (TypeError, ValueError):
            passed = False
        if not passed:
            raise StepFailure(
                f"assertion-{index}",
                f"JSON assertion {index + 1} failed at {assertion.pointer or '/'} "
                f"({assertion.op}); values omitted from report",
            )
    pending = {}
    for key, path in request.capture.items():
        try:
            pending[key] = pointer(document, path)
        except KeyError as exc:
            raise StepFailure("capture", f"capture pointer not found: {path}") from exc
    captures.update(pending)
    return (
        f"{request.method} · HTTP {response.status_code} · "
        f"{len(request.expect.assertions)} assertion(s)"
    )


def redact(text: str, env: dict[str, str], extra_keys: list[str]) -> str:
    keys = set(extra_keys) | {
        key
        for key in env
        if re.search(r"TOKEN|SECRET|PASSWORD|API_KEY|CREDENTIAL", key, flags=re.I)
    }
    for key in keys:
        if value := env.get(key):
            text = text.replace(value, "[REDACTED]")
    return text


def environment(values: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update({key: expand(value, env) for key, value in values.items()})
    return env
