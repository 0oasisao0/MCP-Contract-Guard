"""Command-line entry point. Only reads local data and writes requested reports."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .diffing import compare_tools
from .loading import load_fixtures, load_snapshot, read_json
from .models import InputError, Report
from .replay import replay
from .reporting import render_json, render_junit, render_text, write_report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp-contract-guard",
        description="Witness-first offline MCP tool-contract regression gate. Never invokes tools.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("compare", "validate"):
        sub = commands.add_parser(
            command,
            help="Compare snapshots"
            if command == "compare"
            else "Check one snapshot and its saved fixtures",
        )
        if command == "compare":
            sub.add_argument("before", help="Complete baseline tools/list JSON")
            sub.add_argument("after", help="Complete candidate tools/list JSON")
        else:
            sub.add_argument("snapshot", help="Complete tools/list JSON")
        sub.add_argument("--fixtures", help="Saved cases JSON (no tool execution)")
        sub.add_argument("--format", choices=("text", "json"), default="text")
        sub.add_argument("--output", help="Write selected report format to a local file")
        sub.add_argument("--junit", help="Also write a JUnit XML report")
        sub.add_argument("--fail-on", choices=("breaking", "warning", "none"), default="breaking")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        inputs = [args.before, args.after] if args.command == "compare" else [args.snapshot]
        if args.fixtures:
            inputs.append(args.fixtures)
        outputs = [p for p in (args.output, args.junit) if p is not None]
        input_paths = {Path(p).resolve() for p in inputs}
        output_paths = [Path(p).resolve() for p in outputs]
        if input_paths.intersection(output_paths) or len(output_paths) != len(set(output_paths)):
            raise InputError("Report destinations must differ from inputs and from each other.")
        before = load_snapshot(read_json(inputs[0]))
        after = load_snapshot(read_json(args.after)) if args.command == "compare" else before
        report = compare_tools(before, after) if args.command == "compare" else Report("validate")
        cases = load_fixtures(read_json(args.fixtures)) if args.fixtures else []
        replay(report, before, after, cases)
        text = (
            render_json(report, args.fail_on)
            if args.format == "json"
            else render_text(report, args.fail_on)
        )
        if args.junit:
            write_report(args.junit, render_junit(report, args.fail_on))
        if args.output:
            write_report(args.output, text)
        else:
            sys.stdout.write(text)
        return int(report.failed(args.fail_on))
    except (InputError, RecursionError, OSError, UnicodeError, RuntimeError):
        # Do not leak values through schema exceptions, JSON snippets, or filenames.
        error = sys.exc_info()[1]
        message = (
            str(error)
            if isinstance(error, InputError)
            else "Input or output could not be processed safely."
        )
        sys.stderr.write(f"mcp-contract-guard: {message}\n")
        return 2
