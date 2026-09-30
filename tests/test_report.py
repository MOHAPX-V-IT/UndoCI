import json
import xml.etree.ElementTree as ET

from undoci.data import Event, Report, Trial
from undoci.report import render, write_report


def test_report_escapes_untrusted_text_and_template_tokens(tmp_path):
    report = Report("<script>alert(1)</script> @@TITLE@@", "123", "now", "/config", "hash")
    report.status = "regression"
    report.trials = [
        Trial(
            "trial-001",
            [],
            "regression",
            "verify/read/status",
            "<img src=x onerror=alert(1)>",
            events=[Event("verify", "x", "failed", 0.1, "<script>bad</script>")],
        )
    ]
    write_report(report, tmp_path)
    text = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "<script>alert" not in text
    assert "&lt;script&gt;alert" in text
    assert "@@TITLE@@" in text
    assert "<img src=x" not in text
    assert ET.parse(tmp_path / "junit.xml").getroot().attrib["failures"] == "1"
    assert json.loads((tmp_path / "replay.json").read_text())["config_digest"] == "hash"


def test_passed_and_error_report_verdicts(tmp_path):
    report = Report("test", "123", "now", "config", "hash", status="passed")
    assert "Your way back held." in render(report.to_dict())
    report.status = "error"
    write_report(report, tmp_path)
    assert ET.parse(tmp_path / "junit.xml").getroot().attrib["errors"] == "1"
