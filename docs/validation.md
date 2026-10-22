# Validation record for 0.1.0

Local verification on 2026-10-22, using Linux:

| Check | Result |
| --- | --- |
| Full suite, Python 3.12.14 | 372 passed |
| Full suite, Python 3.13.5 | 372 passed |
| Branch-aware coverage on both interpreters | 95.58%; required floor 90% |
| Declared minimum runtime dependencies | 372 passed with jsonschema 4.23.0 and referencing 0.35.0 |
| Ruff lint and formatting | Passed |
| Dependency consistency (`pip check`) | Passed |
| Isolated source-distribution and wheel build | Passed |
| Distribution metadata (`twine check`) | Passed |
| Full suite against installed wheel, outside checkout with no source package on PYTHONPATH | 372 passed; 95.58% coverage |
| Installed console script | Version, compatible and breaking demos passed |
| Compatible demo, warning threshold | Exit 0; 3 valid saved calls |
| Breaking demo | Exit 1; 3 input-regression cases |
| JSON and JUnit demo reports | Parsed successfully |

The latest-dependency runs used jsonschema 4.26.0, referencing 0.37.0,
pytest 9.1.1, pytest-cov 7.1.0, coverage 7.16.2 and Ruff 0.17.1.
Build validation used build 1.6.1, Hatchling 1.32.4 and Twine 7.0.0.
The [environment inventory](validation-environment.txt) records the Python 3.12
verification environment. It is not a universal cross-platform lockfile or a
recommendation to keep dependencies permanently pinned to these versions.

## Regression coverage

Tests include:

- Input acceptance versus output-guarantee variance, in both directions.
- Required fields, effective additional-property schemas, bounds, enum/const,
  integer/number relationships, arrays, and conservative complex-schema review.
- Saved-input counterexamples, invalid baselines, arbitrary JSON outputs, and
  candidate-output mismatches that must remain warnings.
- Duplicate JSON keys/identifiers, incomplete snapshots, unsupported dialects,
  invalid schema syntax, recursive evaluation and report-write errors.
- Local references, strict pointer syntax, schema-only targets, duplicate anchors,
  external-reference rejection and zero HTTP requests to a listening test server.
- An explicit denial of network and subprocess entry points while running the CLI;
  a captured shell-command string remains inert data.
- Payload redaction, XML/terminal escaping, deterministic output across hash seeds,
  same-path multi-error ordering and safe symlink-loop errors.
- Lossless decimal parsing, decimal multipleOf, large integers and nested dialect
  declarations that must retain the custom numeric evaluator.

Independent review found and drove regression fixes for deterministic ordering,
reference validation, numeric precision/overflow, and path-resolution errors.

## Reproduce

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pip check
pytest --cov=mcp_contract_guard --cov-report=term-missing
ruff check .
ruff format --check .
python -m build
python -m twine check dist/*
```

For the minimum-runtime-dependency check, use a separate environment and install
`jsonschema==4.23.0` and `referencing==0.35.0` with this project and pytest.

GitHub Actions is configured for Python 3.10–3.14. This local record does not claim
those remote jobs have run, or that local results prove security, complete JSON
Schema subsumption, or behavior of any live MCP server.
