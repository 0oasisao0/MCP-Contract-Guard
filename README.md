# MCP Contract Guard

[![CI](https://github.com/0oasisao0/MCP-Contract-Guard/actions/workflows/ci.yml/badge.svg)](https://github.com/0oasisao0/MCP-Contract-Guard/actions/workflows/ci.yml)

**Find the known calls a tool-schema change would reject, before merging it.**

MCP Contract Guard is an offline CI gate for saved MCP `tools/list` snapshots. It compares a baseline with a candidate, then validates the same synthetic arguments and optional saved structured results against each version.

A schema diff tells you what changed. A fixture tells you whether a call that used to validate is now rejected. Keep both kinds of evidence in your pull request.

- **Offline by design:** reads JSON files, never connects to an MCP server or executes a tool.
- **Two complementary checks:** conservative schema-change analysis and concrete fixture validation.
- **CI-friendly:** text, JSON, JUnit XML, and explicit exit codes.
- **Payload-conscious:** reports omit raw argument values, structured result values, and schema values. Names and paths remain visible.
- **Small integration surface:** Python 3.10+, with no MCP SDK required.

This is a focused contract check, not a complete compatibility proof, security audit, or replacement for runtime integration tests.

## Try it

From a source checkout:

```sh
git clone https://github.com/0oasisao0/MCP-Contract-Guard.git
cd MCP-Contract-Guard
python -m venv .venv
. .venv/bin/activate
python -m pip install .

# Pass: existing synthetic calls still validate.
mcp-contract-guard compare \
  examples/before.json examples/after-compatible.json \
  --fixtures examples/cases.json

# Fail with exit 1: the candidate rejects previously valid calls.
mcp-contract-guard compare \
  examples/before.json examples/after-breaking.json \
  --fixtures examples/cases.json
```

On Windows, activate the virtual environment with `.venv\Scripts\activate` instead. Dependency installation may require network access; the comparison itself does not.

The examples use an invented `search_notes` tool. The compatible candidate adds an optional argument and widens the accepted limit. The breaking candidate requires a new argument, tightens existing bounds, and weakens a declared output guarantee. All example data is synthetic.

## Commands

```text
mcp-contract-guard compare BEFORE AFTER [--fixtures CASES]
    [--format text|json] [--output PATH] [--junit PATH]
    [--fail-on breaking|warning|none]

mcp-contract-guard validate SNAPSHOT [--fixtures CASES]
    [--format text|json] [--output PATH] [--junit PATH]
    [--fail-on breaking|warning|none]
```

`compare` checks changes between two snapshots and validates fixtures against both. `validate` checks a single snapshot and, when supplied, its fixtures. Neither command captures snapshots or invokes tools.

`--format` selects text or JSON for stdout, or for the file named by `--output`. The filename extension does not choose the format. `--junit` writes an additional JUnit XML report.

Use `--help` for the available options. The default gate fails on breaking findings. `--fail-on warning` also fails on review warnings; `--fail-on none` records findings without failing the gate. Invalid input is still an error under every threshold.

| Exit | Meaning |
| --- | --- |
| `0` | No findings at or above the selected failure threshold |
| `1` | Contract findings meet the selected failure threshold |
| `2` | Invalid input, unsupported input configuration, usage error, or report-write failure |

A zero exit code means the selected checks passed, not that every possible client remains compatible. In particular, warnings do not fail the default gate.

## Snapshot format

Provide the complete tool list in either form:

```json
{
  "tools": [
    {
      "name": "search_notes",
      "description": "Search synthetic notes.",
      "inputSchema": {
        "type": "object",
        "properties": { "query": { "type": "string" } },
        "required": ["query"]
      },
      "outputSchema": {
        "type": "object",
        "properties": { "matches": { "type": "array" } },
        "required": ["matches"]
      }
    }
  ]
}
```

A JSON-RPC response wrapper with the same list under `result.tools` is also accepted. A snapshot containing a non-null `nextCursor` is rejected: collect every page and combine the `tools` arrays first. Do not simply delete a cursor from an incomplete capture.

Capture both versions with equivalent authorization and configuration. A changed account, permission scope, feature flag, or environment can change the visible list and produce misleading removals. Keep the accepted baseline under version control; review updates rather than regenerating it blindly on every build.

Schemas use JSON Schema Draft 2020-12. An omitted `$schema` is interpreted as Draft 2020-12; explicit other drafts are rejected by this tool. Local fragment references are allowed for validation. External references are rejected, including references to local files. Unresolved local references are errors even without fixtures. Reference-heavy or unsupported schema edits require review rather than a blanket compatibility claim. `format` is treated as an annotation, not an assertion: this tool does not validate email addresses, dates, or URIs merely because a schema declares their format.

The MCP specification permits structured results to be any JSON value, not just an object. This tool supports that in `outputSchema` and fixtures. Fixture arguments must be JSON objects. See the [MCP tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools) and [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12).

## Fixture format

```json
{
  "cases": [
    {
      "id": "search-empty-result",
      "tool": "search_notes",
      "arguments": { "query": "hello" },
      "structuredContent": { "matches": [] }
    }
  ]
}
```

`arguments` is required. `structuredContent` is optional and may contain any JSON value, including `null`. Omit it if you do not have a saved result. It is only checked where an `outputSchema` is available.

Use a small, intentional corpus: ordinary calls, boundary values, optional argument combinations, and representative structured results. Replace production content with synthetic equivalents before committing. The tool does not redact the source files themselves.

### Read fixture findings correctly

- **Baseline-invalid:** saved arguments or a saved structured result already fail the baseline. This is a configuration error (exit `2`), not a new regression. Repair the corpus before using it as regression evidence.
- **Input regression:** arguments accepted by the baseline fail the candidate, or the previously available tool is removed. This is concrete evidence for that saved call.
- **Candidate output mismatch:** a saved structured result validates against the baseline but fails the candidate output schema. This is a warning to review the example and producer behavior, not automatic proof that a client will break.

In `validate` mode, any supplied fixture that fails the snapshot is a configuration error (exit `2`).

A narrower output schema can reject an old saved result while improving guarantees to clients. Conversely, widening output possibilities can weaken the contract even when every saved result still validates. Schema direction and fixture validation answer different questions.

## Compatibility has a direction

For a replacement tool to preserve the declared contract:

- **Inputs:** the candidate should accept at least the inputs accepted by the baseline.
- **Outputs:** the candidate should promise only outputs allowed by the baseline.

For example, requiring a new input field narrows accepted calls. Removing a required output field weakens a guarantee consumers could rely on. Complex edits are reported for review when the conservative checker cannot establish a direction.

Description and annotation changes also merit review because they can affect tool selection and expectations. They are not proof of runtime behavior. Tool annotations are never security or authorization guarantees.

Read [the methodology](docs/methodology.md) for the exact boundaries of the check.

## Add a CI gate

Install a reviewed, pinned release or a checked-out revision using your existing dependency policy. From this repository checkout, a minimal CI command is:

```sh
python -m pip install .
mcp-contract-guard compare contracts/baseline.json contracts/candidate.json \
  --fixtures contracts/cases.json \
  --format json --output contract-report.json \
  --junit contract-report.xml \
  --fail-on warning
```

Generate `candidate.json` in your own trusted capture step before this command. MCP Contract Guard intentionally has no server-launch or capture configuration. Store reports as CI artifacts, and let the command's nonzero status block the job. Use your CI system's equivalent of “always upload” if you need artifacts after a failed gate. Restrict report access when tool names or property paths are confidential.

For a gradual rollout, begin with `--fail-on none`, review the findings, then adopt `breaking` or `warning`. Do not suppress exit `2`: an invalid snapshot is not a successful comparison.

## Where it fits

Existing projects already compare MCP tool schemas. MCP Contract Guard makes a deliberate, narrow choice: complete saved snapshots, synthetic fixture impact, offline execution, and reviewable reports.

Use an MCP client, your server's tests, or [MCP Inspector](https://github.com/modelcontextprotocol/inspector) to inspect and exercise a live server. Use this project after you have captured the contract. It does not test authentication, transport, tool execution, prompts, resources, latency, content blocks, or application semantics.

See [THIRD_PARTY.md](THIRD_PARTY.md) for standards, dependencies, and related work. This project is independent and is not an official MCP project.

## Development

```sh
python -m pip install -e '.[dev]'
pytest --cov=mcp_contract_guard
ruff check .
ruff format --check .
python -m build
python -m twine check dist/*
```

See the [local validation record](docs/validation.md) for tested versions, coverage, and limitations.

Contributions should include a small synthetic example and a test that explains why a change is breaking, compatible, or uncertain. See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## 中文速览

MCP Contract Guard 是离线的 MCP 工具契约检查器：比较完整的 `tools/list` JSON 快照，并用同一组人工合成的参数及可选结构化结果分别验证新旧版本。它不会连接服务器，也不会执行工具。

- 输入方向：新版应继续接受旧版接受的参数。
- 输出方向：新版不应削弱旧版对结果的保证。
- 旧版有效、新版无效的参数是具体回归证据；旧结果不符合新输出模式只提示复核，不自动等于客户端兼容性破坏。
- 仅支持 JSON Schema Draft 2020-12；拒绝外部引用和带非空 `nextCursor` 的不完整快照。
- 默认只因破坏性变更退出 `1`；`--fail-on warning` 也会阻止含警告的变更；输入、用法或基线样例错误退出 `2`。
- 有限测试样例不能证明所有情况都兼容。报告不包含原始参数、结果或模式值，但名称与路径仍可能敏感。

快速开始：安装后运行上面的 `examples/` 命令。详细边界见 [methodology](docs/methodology.md)。

## License

[MIT](LICENSE). Copyright © 2026 0oasisao0.
