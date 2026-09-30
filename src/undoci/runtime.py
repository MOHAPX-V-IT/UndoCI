"""Isolated process / Compose lifecycles with bounded commands and cleanup."""

from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import IO

import httpx
import yaml

from undoci.config import Command, ComposeTarget, Config, ProcessTarget
from undoci.requests import StepFailure, environment, expand, redact


def stop_process(process: subprocess.Popen):
    """Terminate the process tree, including grandchildren on timeout / cancellation."""
    if os.name == "nt":
        if process.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        # A parent may have exited while a child still owns a socket.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired as exc:
        raise StepFailure("cleanup", "process tree did not terminate") from exc


def spawn(args, cwd, env, output):
    options = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    try:
        return subprocess.Popen(
            args,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            **options,
        )
    except OSError as exc:
        raise StepFailure("spawn", f"cannot start executable ({type(exc).__name__})") from exc


class Runtime:
    def __init__(self, config: Config, root: Path, trial_dir: Path, project: str):
        self.config, self.root, self.directory = config, root, trial_dir
        self.directory.mkdir(parents=True, exist_ok=False)
        self.project = project
        self.env = environment(config.env)
        self.env.update(
            {
                "UNDOCI_TRIAL_DIR": str(trial_dir),
                "UNDOCI_PROJECT": project,
                "UNDOCI_CONFIG_DIR": str(root),
                "PYTHONUNBUFFERED": "1",
                "UNDOCI_PYTHON": sys.executable,
            }
        )
        self.secrets: set[str] = set()
        self._remember_secrets(self.env)
        self.process: subprocess.Popen | None = None
        self.output: IO | None = None
        self.base_url = ""
        self.command_number = 0
        self.compose_initialized = False
        self.override = self.directory / "compose.override.yaml"
        self.client = httpx.Client(trust_env=False, follow_redirects=False)
        if isinstance(config.target, ProcessTarget):
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                self.port = sock.getsockname()[1]
            self.base_url = f"http://127.0.0.1:{self.port}"
            self.env["UNDOCI_PORT"] = str(self.port)
            self.env["UNDOCI_BASE_URL"] = self.base_url

    def safe(self, value: str):
        for secret in sorted(self.secrets, key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
        return value

    def _remember_secrets(self, env):
        for key, value in env.items():
            if value and (
                key in self.config.redact_env
                or re.search(r"TOKEN|SECRET|PASSWORD|API_KEY|CREDENTIAL", key, flags=re.I)
            ):
                self.secrets.add(value)

    def _save_log(self, output: IO, name: str) -> str:
        output.flush()
        output.seek(0, 2)
        size = output.tell()
        output.seek(max(0, size - 64_000))
        text = self.safe(output.read().decode("utf-8", errors="replace"))
        if size > 64_000:
            text = "[earlier output truncated]\n" + text
        (self.directory / name).write_text(text, encoding="utf-8")
        return text

    def command(self, command: Command, *, capture=False) -> str:
        env = self.env.copy()
        env.update(expand(command.env, env))
        # Include per-command credentials in redaction without copying them into the report.
        secret_env = self.env | env
        self._remember_secrets(secret_env)
        args = expand(command.run, env)
        cwd = Path(expand(command.cwd, env)) if command.cwd else self.root
        if not cwd.is_absolute():
            cwd = self.root / cwd
        self.command_number += 1
        with tempfile.TemporaryFile() as output:
            process = spawn(args, cwd, env, output)
            try:
                process.wait(timeout=command.timeout)
            except subprocess.TimeoutExpired as exc:
                stop_process(process)
                raise StepFailure("timeout", f"command exceeded {command.timeout:g}s") from exc
            except BaseException:
                stop_process(process)
                raise
            finally:
                # Always remove orphaned children left behind by finite hooks on POSIX.
                if os.name != "nt":
                    stop_process(process)
                output.flush()
                output.seek(0)
                raw = output.read(5_000_000).decode("utf-8", errors="replace")
                safe = redact(raw[-64_000:], secret_env, self.config.redact_env)
                (self.directory / f"command-{self.command_number:03}.log").write_text(
                    safe, encoding="utf-8"
                )
            if process.returncode:
                raise StepFailure(
                    "exit",
                    f"command exited with code {process.returncode}; "
                    f"see command-{self.command_number:03}.log",
                )
            return raw if capture else "command completed"

    def hooks(self, phase: str):
        for command in getattr(self.config.lifecycle, phase):
            self.command(command)

    def _compose(self, args: list[str], *, capture=False):
        target = self.config.target
        assert isinstance(target, ComposeTarget)
        path = (self.root / target.file).resolve()
        prefix = [
            "docker",
            "compose",
            "--project-name",
            self.project,
            "--project-directory",
            str(path.parent),
            "-f",
            str(path),
            "-f",
            str(self.override),
        ]
        return self.command(Command(run=prefix + args, timeout=target.timeout), capture=capture)

    def _compose_validate(self):
        config = json.loads(self._compose(["config", "--format", "json"], capture=True))
        for kind in ("volumes", "networks"):
            for value in config.get(kind, {}).values():
                if value.get("external") or (
                    value.get("name") and not value["name"].startswith(self.project + "_")
                ):
                    raise StepFailure(
                        "isolation",
                        "Compose resources must be project-scoped; "
                        "external and fixed-name resources are not supported",
                    )
        for name, service in config.get("services", {}).items():
            if service.get("container_name") or service.get("network_mode") == "host":
                raise StepFailure(
                    "isolation", "fixed container names / host networking unsupported"
                )
            if service.get("privileged"):
                raise StepFailure("isolation", "privileged Compose services unsupported")
            ports = service.get("ports", [])
            target = self.config.target
            if ports and (
                name != target.service
                or len(ports) != 1
                or any(
                    port.get("host_ip") != "127.0.0.1" or str(port.get("published")) != "0"
                    for port in ports
                )
            ):
                raise StepFailure("isolation", "let UndoCI allocate the only published port")
            for volume in service.get("volumes", []):
                if volume.get("type") == "bind" and not volume.get("read_only"):
                    raise StepFailure("isolation", "Compose bind mounts must be read-only")

    def start(self, version: str):
        target = self.config.target
        self.env["UNDOCI_VERSION"] = version
        if isinstance(target, ProcessTarget):
            service = getattr(target, version)
            env = self.env | expand(service.env, self.env)
            self._remember_secrets(env)
            cwd = Path(expand(service.cwd, env)) if service.cwd else self.root
            if not cwd.is_absolute():
                cwd = self.root / cwd
            self.output = tempfile.TemporaryFile()
            self.process = spawn(expand(service.run, env), cwd, env, self.output)
            self._ready(service.ready_path, service.ready_status, service.timeout)
        else:
            image = expand(target.old_image if version == "old" else target.new_image, self.env)
            self.env["UNDOCI_IMAGE"] = image
            self.override.write_text(
                yaml.safe_dump(
                    {
                        "services": {
                            target.service: {
                                "image": image,
                                "ports": [
                                    {
                                        "target": target.container_port,
                                        "published": "0",
                                        "host_ip": "127.0.0.1",
                                        "protocol": "tcp",
                                    }
                                ],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            if not self.compose_initialized:
                self._compose_validate()
                # Set before up so partially-created resources are cleaned on failure.
                self.compose_initialized = True
                self._compose(["up", "-d", "--wait", "--wait-timeout", str(int(target.timeout))])
            else:
                self._compose(["up", "-d", "--no-deps", "--force-recreate", target.service])
            address = (
                self._compose(["port", target.service, str(target.container_port)], capture=True)
                .strip()
                .splitlines()[-1]
            )
            if not address.startswith("127.0.0.1:"):
                raise StepFailure("isolation", "expected a loopback-only published service port")
            self.base_url = "http://" + address
            self.env["UNDOCI_BASE_URL"] = self.base_url
            self.env["UNDOCI_PORT"] = address.rsplit(":", 1)[1]
            self._ready(target.ready_path, target.ready_status, target.timeout)

    def _ready(self, path: str, status: int, timeout: float):
        if not path.startswith("/") or path.startswith("//"):
            raise StepFailure("config", "readiness path must start with a single /")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise StepFailure("startup-exit", "service exited before becoming ready")
            try:
                with self.client.stream(
                    "GET",
                    self.base_url + path,
                    timeout=min(1, max(0.01, deadline - time.monotonic())),
                ) as response:
                    if response.status_code == status:
                        if self.process is not None and self.process.poll() is not None:
                            raise StepFailure("startup-exit", "service exited during readiness")
                        return
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        raise StepFailure("readiness", f"service did not become ready within {timeout:g}s")

    def stop(self):
        if self.process is not None:
            try:
                stop_process(self.process)
            finally:
                self.process = None
                if self.output:
                    name = (
                        f"service-{self.env.get('UNDOCI_VERSION', 'unknown')}-{time.time_ns()}.log"
                    )
                    self._save_log(self.output, name)
                    self.output.close()
                    self.output = None
        elif self.output is not None:
            self.output.close()
            self.output = None
        if isinstance(self.config.target, ComposeTarget) and self.compose_initialized:
            self._compose(["stop", self.config.target.service])

    def close(self) -> list[str]:
        errors = []
        for operation in [self.stop, lambda: self.hooks("cleanup")]:
            try:
                operation()
            except Exception as exc:
                errors.append(self.safe(str(exc)))
        if self.compose_initialized:
            try:
                self._compose(["logs", "--no-color", "--tail", "200"])
            except Exception as exc:
                errors.append(self.safe(str(exc)))
            try:
                self._compose(["down", "--volumes", "--remove-orphans", "--timeout", "10"])
            except Exception as exc:
                errors.append(self.safe(str(exc)))
        self.client.close()
        return errors
