# Contributing

Thank you for helping make contract changes easier to review.

## Development setup

Python 3.10 or newer is required. From the repository root:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest --cov=mcp_contract_guard --cov-report=term-missing
ruff check .
ruff format --check .
python -m build
python -m twine check dist/*
```

On Windows, use `.venv\Scripts\activate` to activate the environment. Check the package configuration for current dependency and tool settings.

## A useful change

Open an issue before a large change. For a bug report or pull request, include:

1. The current behavior and the intended behavior.
2. Minimal, synthetic baseline and candidate snapshots.
3. A fixture when concrete input acceptance is relevant.
4. The expected classification and why its direction is correct.
5. Tests covering the regression and its reverse direction where meaningful.

Keep changes focused. Never include production tool dumps, personal data, credentials, or private customer examples. See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## Design rules

- Keep comparison and validation offline. Do not start servers, execute tools, or retrieve external references.
- Do not confuse accepted inputs with promised outputs. They have opposite compatibility directions.
- Prefer a review warning to an unjustified compatibility guarantee.
- Preserve baseline validation: a case that was never valid is not evidence of a new input regression.
- Keep saved-output mismatches separate from client-compatibility claims.
- Do not print raw fixture or schema values in diagnostics. Test hostile labels, control characters, and sensitive-looking values as well as ordinary cases.
- Treat tool descriptions and annotations as untrusted metadata, not enforcement.
- Keep the CLI, README examples, report behavior, and exit-code tests aligned.
- Add dependency and standards attribution when introducing external components. Do not copy code from related projects without an explicit license review and proper attribution.

For schema-analysis changes, test interactions rather than only one keyword at a time. Useful edge cases include contradictory constraints, optional properties under open objects, closed output objects, number/integer relationships, composition, and local references.

## Before submitting

Run the test suite, linter, package build, and the README example commands. Confirm that the compatible example exits `0`, the breaking comparison exits `1`, and malformed input exits `2`. If you change a report field, update the documentation and report tests.

Contributions are accepted under this repository's [MIT license](LICENSE). Submit only work you have the right to contribute. Explain any substantial third-party material and its license in the pull request.
