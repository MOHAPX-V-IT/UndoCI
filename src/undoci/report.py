"""Offline, escaped evidence artifacts: HTML, JSON, JUnit, Markdown and replay manifest."""

from __future__ import annotations

import html
import json
import xml.etree.ElementTree as ET
from importlib.resources import files
from pathlib import Path

from undoci.data import Report


def escape(value):
    return html.escape(str(value), quote=True)


def render(data: dict) -> str:
    titles = {
        "passed": "Your way back held.",
        "regression": "This release breaks the way back.",
        "error": "The rehearsal could not finish.",
        "inconclusive": "The evidence is not repeatable.",
    }
    status = data["status"]
    # Restrict class names independently of user-controlled report JSON.
    css_status = status if status in titles else "error"
    count = len(data["trials"])
    original = data["original_actions"]
    reduced = data["reduced_actions"]
    sequence = "".join(
        '<li class="'
        + ("kept" if action in reduced else "removed")
        + '"><code>'
        + escape(action)
        + "</code><span>"
        + ("retained" if action in reduced else "removed")
        + "</span></li>"
        for action in original
    )
    rows = []
    for trial in data["trials"]:
        events = "".join(
            '<tr><td><span class="state '
            + ("passed" if event["status"] == "passed" else "error")
            + '">'
            + escape(event["status"])
            + "</span></td><td>"
            + escape(event["phase"])
            + "</td><td><code>"
            + escape(event["step"])
            + "</code></td><td>"
            + escape(event["detail"])
            + f"</td><td>{event['duration']:.2f}s</td></tr>"
            for event in trial["events"]
        )
        rows.append(
            '<details class="trial" data-status="' + escape(trial["status"]) + '"><summary>'
            '<span class="trial-id">'
            + escape(trial["id"])
            + '</span><span class="state">'
            + escape(trial["status"])
            + "</span><span>"
            + str(len(trial["actions"]))
            + ' actions</span><span class="timing">'
            + f"{trial['duration']:.2f}s</span></summary>"
            '<div class="trial-body"><p>'
            + escape(trial["message"] or "All checks passed.")
            + '</p><p class="muted">Actions: <code>'
            + escape(" → ".join(trial["actions"]) or "none — migration only")
            + "</code></p>"
            '<div class="table-scroll" tabindex="0" role="region" aria-label="Trial events">'
            "<table><thead><tr><th>Status</th><th>Phase</th><th>Step</th><th>Evidence</th>"
            "<th>Time</th></tr></thead><tbody>" + events + "</tbody></table></div></div></details>"
        )
    note = "".join("<li>" + escape(note) + "</li>" for note in data["notes"])
    reason = next(
        (trial["message"] for trial in data["trials"] if trial["status"] != "passed"),
        "All configured checks passed in this rehearsal.",
    )
    template = files("undoci").joinpath("templates/report.html").read_text(encoding="utf-8")
    replacements = {
        "TITLE": escape(data["name"]),
        "STATUS": escape(status.upper()),
        "STATUS_CLASS": css_status,
        "HEADLINE": titles.get(status, titles["error"]),
        "REASON": escape(reason),
        "RUN_ID": escape(data["run_id"]),
        "DATE": escape(data["created_at"]),
        "TRIALS_COUNT": str(count),
        "DURATION": f"{data['duration']:.1f}s",
        "SIGNATURE": escape(data.get("signature") or "No failing assertion"),
        "BOUNDARY": escape(data.get("boundary_action") or "No action boundary established"),
        "BOUNDARY_NOTE": escape(data["boundary_note"]),
        "SEQUENCE": sequence,
        "REDUCTION": escape(data["reduction"]),
        "CONFIRMED": "Repeated successfully" if data["confirmed"] else "Not confirmed",
        "REDUCED_COUNT": str(len(reduced)),
        "ORIGINAL_COUNT": str(len(original)),
        "TRIAL_ROWS": "".join(rows),
        "NOTES": note,
    }
    # Single-pass substitution: user text containing template markers stays literal.
    import re

    return re.sub(r"@@([A-Z_]+)@@", lambda match: replacements[match[1]], template)


def write_report(report: Report, directory: Path):
    data = report.to_dict()
    (directory / "report.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (directory / "report.html").write_text(render(data), encoding="utf-8")
    replay = {
        "version": 1,
        "config_path": report.config_path,
        "config_digest": report.config_digest,
        "actions": report.reduced_actions,
        "expected_signature": report.signature,
    }
    (directory / "replay.json").write_text(json.dumps(replay, indent=2), encoding="utf-8")
    failed = report.status == "regression"
    errored = report.status in ("error", "inconclusive")
    suite = ET.Element(
        "testsuite",
        name="UndoCI",
        tests="1",
        failures=str(int(failed)),
        errors=str(int(errored)),
        time=f"{report.duration:.3f}",
    )
    case = ET.SubElement(
        suite,
        "testcase",
        classname="undoci.rollback",
        name=report.name,
        time=f"{report.duration:.3f}",
    )
    if failed or errored:
        node = ET.SubElement(case, "failure" if failed else "error", message=report.status)
        node.text = (report.signature or "") + "\n" + "\n".join(report.notes)
    ET.ElementTree(suite).write(directory / "junit.xml", encoding="utf-8", xml_declaration=True)
    md = (
        f"# UndoCI: {report.status.upper()}\n\n{report.name}\n\n"
        f"- Trials: {len(report.trials)}\n- Duration: {report.duration:.1f}s\n"
        f"- Failure signature: `{report.signature or 'none'}`\n"
        f"- Boundary: `{report.boundary_action or 'not established'}`\n"
        f"- Reduction: {report.reduction}\n\n"
        "## Retained actions\n\n"
        + ("\n".join(f"- `{item}`" for item in report.reduced_actions) or "No actions required.")
        + "\n\nEvidence applies only to the configured workloads, versions and assertions.\n"
    )
    (directory / "summary.md").write_text(md, encoding="utf-8")
    (directory.parent / "latest.json").write_text(
        json.dumps({"run_id": report.run_id, "report": str(directory / "report.html")}, indent=2),
        encoding="utf-8",
    )
