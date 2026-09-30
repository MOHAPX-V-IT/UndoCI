from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml
from pydantic import ValidationError

from undoci import __version__
from undoci.analysis import analyze
from undoci.config import Config, action_dependencies, digest, load_config
from undoci.demo import create_demo
from undoci.report import render, write_report

EXIT = {"passed": 0, "regression": 1, "error": 2, "inconclusive": 3}


def parser():
    root = argparse.ArgumentParser(prog="undoci", description="Ship forward. Know your way back.")
    root.add_argument("--version", action="version", version=f"UndoCI {__version__}")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("run", "validate"):
        child = commands.add_parser(
            name,
            help="Rehearse a release"
            if name == "run"
            else "Validate configuration without running commands",
        )
        child.add_argument("config", type=Path)
        if name == "run":
            child.add_argument("--output", type=Path, default=Path(".undoci"))
            child.add_argument("--no-minimize", action="store_true")
            child.add_argument("--max-trials", type=int)
            child.add_argument("--quiet", action="store_true")
    demo = commands.add_parser("demo", help="Create a runnable, dependency-free sample app")
    demo.add_argument("directory", type=Path, nargs="?", default=Path("undoci-demo"))
    demo.add_argument("--scenario", choices=["enum", "queue", "data-loss", "safe"], default="enum")
    replay = commands.add_parser("replay", help="Re-run a reduced scenario from a manifest")
    replay.add_argument("manifest", type=Path)
    replay.add_argument("--config", type=Path, help="Relocate the original configuration")
    replay.add_argument("--allow-config-change", action="store_true")
    replay.add_argument("--output", type=Path, default=Path(".undoci"))
    schema = commands.add_parser("schema", help="Export the configuration JSON Schema")
    schema.add_argument("--output", type=Path)
    report = commands.add_parser("report", help="Render an existing JSON report offline")
    report.add_argument("source", type=Path)
    report.add_argument("--output", type=Path, required=True)
    commands.add_parser("doctor", help="Check Python and Docker availability")
    return root


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "doctor":
            print(
                f"UndoCI {__version__}\nPython {sys.version.split()[0]}\n"
                "Local process driver: ready"
            )
            if shutil.which("docker"):
                try:
                    result = subprocess.run(
                        ["docker", "info", "--format", "{{.ServerVersion}}"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    print(
                        "Docker engine: "
                        + (
                            result.stdout.strip()
                            if result.returncode == 0
                            else "not available (start Docker Desktop)"
                        )
                    )
                except subprocess.TimeoutExpired:
                    print("Docker engine: check timed out")
            else:
                print("Docker: not installed (optional)")
            return 0
        if args.command == "demo":
            path = create_demo(args.directory.resolve(), args.scenario)
            print(f'Created {args.scenario} demo.\nRun: undoci run "{path}"')
            return 0
        if args.command == "schema":
            content = json.dumps(Config.model_json_schema(), indent=2)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(content + "\n", encoding="utf-8")
            else:
                print(content)
            return 0
        if args.command == "report":
            data = json.loads(args.source.read_text(encoding="utf-8"))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(render(data), encoding="utf-8")
            print(args.output.resolve())
            return 0
        selected = None
        expected = None
        if args.command == "replay":
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            if manifest.get("version") != 1:
                raise ValueError("unsupported replay manifest version")
            path = (args.config or Path(manifest["config_path"])).resolve()
            if not args.allow_config_change and digest(path) != manifest["config_digest"]:
                raise ValueError("configuration changed; use --allow-config-change deliberately")
            selected, expected = manifest["actions"], manifest.get("expected_signature")
            if not isinstance(selected, list) or any(
                not isinstance(item, str) for item in selected
            ):
                raise ValueError("manifest actions must be a list of IDs")
            config = load_config(path)
            dependencies = action_dependencies(config)
            if any(not dependencies.get(item, set()) <= set(selected) for item in selected):
                raise ValueError("replay action dependencies are missing")
        else:
            path = args.config.resolve()
            config = load_config(path)
        if args.command == "validate":
            print(
                f"Valid: {config.name} ({len(config.actions)} actions, {config.target.kind} driver)"
            )
            return 0
        if getattr(args, "max_trials", None) is not None:
            config.analysis.max_trials = args.max_trials
            # Assignment itself does not validate unless requested explicitly.
            config = Config.model_validate(config.model_dump())
        report, directory = analyze(
            config,
            path,
            args.output,
            minimize=args.command != "replay" and not args.no_minimize,
            selected=selected,
            progress=None if getattr(args, "quiet", False) else print,
        )
        if args.command == "replay" and expected and report.signature != expected:
            report.notes.append("Replay did not reproduce the saved failure signature.")
            if report.status == "regression":
                report.status = "inconclusive"
        write_report(report, directory)
        print(
            f"\n{report.status.upper()} | {len(report.trials)} rehearsals | {report.duration:.1f}s"
        )
        if report.boundary_action:
            print(f"First failing prefix ends at: {report.boundary_action}")
        if report.status == "regression":
            print(f"Retained actions: {', '.join(report.reduced_actions) or '(none)'}")
        print(f"Report: {directory / 'report.html'}")
        print(f"Replay: {directory / 'replay.json'}")
        return EXIT[report.status]
    except KeyboardInterrupt:
        print("\nInterrupted. Active trial cleanup attempted.", file=sys.stderr)
        return 130
    except ValidationError as exc:
        # Do not echo rejected values (they may be credentials).
        for error in exc.errors(include_input=False, include_url=False):
            print(
                f"Configuration error at {'.'.join(map(str, error['loc']))}: {error['msg']}",
                file=sys.stderr,
            )
        return 2
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        print(f"UndoCI error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
