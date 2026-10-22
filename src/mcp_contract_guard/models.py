"""Stable, value-redacted report model."""

from dataclasses import asdict, dataclass, field
from typing import Any

SEVERITIES = {"breaking": 0, "warning": 1, "info": 2}


class InputError(ValueError):
    """Invalid or unsupported input. Messages must not include payload values."""


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    tool: str
    path: str
    message: str
    fixture: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass
class Report:
    mode: str
    findings: list[Finding] = field(default_factory=list)
    fixtures: list[dict[str, Any]] = field(default_factory=list)

    def ordered_findings(self) -> list[Finding]:
        return sorted(
            set(self.findings),
            key=lambda f: (
                SEVERITIES[f.severity],
                f.tool,
                f.path,
                f.code,
                f.fixture or "",
                f.message,
            ),
        )

    def failed(self, fail_on: str = "breaking") -> bool:
        threshold = {"breaking": 0, "warning": 1, "none": -1}[fail_on]
        return any(SEVERITIES[f.severity] <= threshold for f in self.findings)

    def as_dict(self, fail_on: str = "breaking") -> dict[str, Any]:
        findings = self.ordered_findings()
        summary = {
            severity: sum(f.severity == severity for f in findings) for severity in SEVERITIES
        }
        summary.update(
            fixtures=len(self.fixtures),
            input_regressions=sum(
                f["input"]["after"] in {"invalid", "missing_tool"} for f in self.fixtures
            ),
            output_mismatches=sum(f["output"]["after"] == "invalid" for f in self.fixtures),
        )
        return {
            "schema_version": 1,
            "mode": self.mode,
            "status": "fail" if self.failed(fail_on) else "pass",
            "fail_on": fail_on,
            "summary": summary,
            "findings": [f.as_dict() for f in findings],
            "fixtures": sorted(self.fixtures, key=lambda f: (f["tool"], f["id"])),
        }


def pointer(parts: list[str | int] | tuple[str | int, ...]) -> str:
    """Encode an RFC 6901 JSON Pointer; never include instance values."""
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)
