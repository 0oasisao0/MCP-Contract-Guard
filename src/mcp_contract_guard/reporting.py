"""Deterministic plain text, JSON and JUnit output without captured values."""

import json
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from .models import SEVERITIES, InputError, Report


def render_json(report: Report, fail_on: str) -> str:
    return json.dumps(report.as_dict(fail_on), sort_keys=True, indent=2, ensure_ascii=True) + "\n"


def _label(text: str) -> str:
    # Escape terminal control characters, not merely XML markup.
    return json.dumps(text, ensure_ascii=True)[1:-1]


def render_text(report: Report, fail_on: str) -> str:
    data = report.as_dict(fail_on)
    counts = data["summary"]
    lines = [
        f"{data['status'].upper()}: {counts['breaking']} breaking, "
        f"{counts['warning']} warning, {counts['info']} info",
        f"Fixtures: {counts['fixtures']} total; {counts['input_regressions']} input regressions; "
        f"{counts['output_mismatches']} saved-output mismatches.",
    ]
    for finding in report.ordered_findings():
        case = f" fixture={_label(finding.fixture)}" if finding.fixture is not None else ""
        lines.append(
            f"[{finding.severity}] {finding.code} tool={_label(finding.tool)} "
            f"path={_label(finding.path) or '/'}{case}: {finding.message}"
        )
    lines.append("Directional rules and saved fixtures are not a proof of full compatibility.")
    return "\n".join(lines) + "\n"


def _xml_safe(text: str) -> str:
    # XML 1.0 cannot represent NUL/control chars even as character entities.
    return "".join(
        c
        if c in "\t\n\r"
        or 0x20 <= ord(c) <= 0xD7FF
        or 0xE000 <= ord(c) <= 0xFFFD
        or 0x10000 <= ord(c) <= 0x10FFFF
        else f"\\u{ord(c):04x}"
        for c in text
    )


def render_junit(report: Report, fail_on: str) -> str:
    findings = report.ordered_findings()
    threshold = {"breaking": 0, "warning": 1, "none": -1}[fail_on]
    failures = sum(SEVERITIES[f.severity] <= threshold for f in findings)
    suite = ET.Element(
        "testsuite",
        name="mcp-contract-guard",
        tests=str(max(1, len(findings))),
        failures=str(failures),
        errors="0",
        skipped="0",
    )
    if not findings:
        ET.SubElement(suite, "testcase", classname="contract", name="no_findings")
    for index, finding in enumerate(findings):
        name = f"{index:04d}:{finding.code}:{finding.path}"
        if finding.fixture is not None:
            name += f":{finding.fixture}"
        case = ET.SubElement(
            suite, "testcase", classname=_xml_safe(finding.tool), name=_xml_safe(name)
        )
        if SEVERITIES[finding.severity] <= threshold:
            node = ET.SubElement(
                case, "failure", type=finding.code, message=_xml_safe(finding.message)
            )
        else:
            node = ET.SubElement(case, "system-out")
        node.text = _xml_safe(f"{finding.severity}: {finding.message}")
    ET.indent(suite, space="  ")
    return ET.tostring(suite, encoding="unicode", xml_declaration=False) + "\n"


def write_report(path: str, text: str) -> None:
    """Replace a report atomically; do not leave a half-written file on failure."""
    temporary = None
    try:
        target = Path(path)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent, prefix=".mcp-guard-", delete=False
        ) as stream:
            temporary = stream.name
            stream.write(text)
        os.replace(temporary, target)
    except (OSError, UnicodeError):
        raise InputError("Cannot write report; check destination and permissions.") from None
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass
