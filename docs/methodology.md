# What a contract check can establish

## Scope and evidence

MCP Contract Guard compares saved tool definitions and validates saved JSON instances. It does not observe a live server. “Replay” means schema validation of the same saved case against two contracts, not repeating a tool call.

There are two independent sources of evidence:

1. **Structural analysis:** a conservative inspection of changed schema constraints, tool availability, and metadata.
2. **Fixture validation:** an actual instance either validates or fails under each schema.

A finding should be read with its source. A saved old-valid/new-invalid input is a concrete counterexample for that call. A structural warning indicates unresolved risk. Neither a clean structural comparison nor a finite passing corpus proves general equivalence.

## The direction matters

Let `I_old` and `I_new` be the sets of argument objects allowed by the baseline and candidate. Input compatibility asks whether `I_old` is a subset of `I_new`.

Let `O_old` and `O_new` be the sets of structured results allowed by the two output schemas. Output compatibility asks whether `O_new` is a subset of `O_old`.

These are schema-level conditions, not assertions about what a server actually produces. They also do not model a particular consumer's undocumented assumptions.

| Change in isolation | Input interpretation | Output interpretation |
| --- | --- | --- |
| Add a required property | Narrows acceptance | Strengthens the presence guarantee |
| Remove a required property | Widens acceptance | Weakens the presence guarantee |
| Widen an enum or numeric interval | Widens acceptance | Weakens the value guarantee |
| Narrow an enum or numeric interval | Narrows acceptance | Strengthens the value guarantee |
| Allow additional properties | Widens acceptance | Broadens possible results |

“In isolation” is important. Constraints interact. Impossible branches, combinations, references, pattern properties, conditionals, and changes to nested schemas can invalidate an intuitive keyword-only conclusion. The checker is deliberately incomplete and emits review warnings for unsupported or complex edits. It is not a general schema-containment solver.

An optional input property can still affect compatibility. If the old schema allowed arbitrary extra keys, declaring a schema for a previously unlisted key constrains calls that used to be legal. Similarly, adding a result property can conflict with an old consumer contract that forbade additional properties. Do not equate “added” with “safe.”

## Fixture interpretation

Every case contains an `id`, a `tool` name, and an `arguments` object. Optional `structuredContent` is the saved JSON value itself, not a complete `tools/call` envelope.

In comparison mode, the same data is checked against each available version of the named tool. The important outcomes are:

| Baseline input | Candidate input | Interpretation |
| --- | --- | --- |
| Valid | Valid | This call remains accepted |
| Valid | Invalid or tool removed | Concrete input regression |
| Invalid | Any | Invalid baseline fixture: configuration error, exit `2` |

A case naming a tool absent from the baseline cannot establish that an old call has regressed. It is a configuration error. Comparison requires a valid baseline corpus; a baseline argument or structured-result mismatch returns exit `2`, regardless of the selected gate threshold.

Saved structured results are validated wherever an output schema is present. Without an output schema there is no declared output constraint to check. Omitting `structuredContent` skips that part of the fixture; supplying `null` tests the actual null value.

A candidate output mismatch is a warning because it has more than one possible explanation: the result could be stale, the fixture could be wrong, or the producer could violate its declaration. A schema can intentionally narrow allowed outputs while preserving consumer compatibility. This tool cannot tell whether a candidate server will produce the saved value. Check producer behavior separately.

In single-snapshot validation, invalid arguments or saved structured results are fixture/contract configuration errors (exit `2`). There is no prior version from which to infer a regression.

## Supported input profile

- JSON files only; no YAML, transport capture, or server process configuration. Files are limited to 16 MiB each and fixture corpora to 10,000 cases. Duplicate JSON object keys and non-finite numbers are rejected.
- A complete `{ "tools": [...] }` result or a JSON-RPC response containing that result.
- Unique tool names. An incomplete page with a non-null `nextCursor` must be assembled before use; an absent or null cursor is accepted.
- JSON Schema Draft 2020-12, also used when `$schema` is absent.
- Object-valued `inputSchema` declarations and object-valued fixture arguments.
- `outputSchema` declarations can be JSON Schema objects or booleans and can describe any JSON type.
- Fragment-local references can be validated; external retrieval is never performed. Invalid or unresolved references are errors even when no fixture exercises them. `$id` resources and `$dynamicRef` are outside the supported profile and are rejected.
- Decimal literals are parsed losslessly; integral decimal literals are normalized to integers. `multipleOf` uses exact decimal-rational arithmetic, avoiding binary-float false mismatches such as `0.3` against `0.1`. Decimal magnitudes that overflow a finite binary64 range or underflow to zero are rejected as unsupported rather than rounded. Ordinary integer literals retain Python's exact integer representation and interpreter safety limits.
- Local JSON Pointer syntax and schema target locations are checked strictly, and duplicate anchor names are rejected. References inside instance data (`const`, `default`, `examples`) are data, not schema directives.
- `format` is annotation-only. There is no format assertion checker for email addresses, dates, URIs, or other format names. Use separate application tests for those requirements.

The tool deliberately supports a narrower schema profile than all possible MCP deployments. An unsupported dialect is an input error, not a claim that the server violates MCP. See the [MCP schema guidance](https://modelcontextprotocol.io/specification/2026-07-28/server/tools) and [Draft 2020-12 specification](https://json-schema.org/draft/2020-12).

Schema validation and schema comparison have different coverage. A schema accepted by the validator can still contain a change that the comparison layer only knows how to flag for manual review. In particular, local-reference support does not imply complete reasoning about referenced schemas.

## Metadata is part of the review

Changes to descriptions, annotations, or other tool-facing metadata can alter selection behavior and user expectations without changing JSON validation. They warrant review warnings rather than a claim of identical behavior.

A description is not an executable specification. An annotation such as a read-only hint does not enforce permissions, prevent side effects, or establish trust. The actual server and client must implement their own authorization and safety controls.

## Reports and thresholds

Text, JSON, and JUnit reports expose diagnostic categories, schema/instance paths, and labels. They omit raw fixture and schema values to reduce accidental disclosure. This is not a complete anonymization boundary: a tool name, property key, fixture ID, or filename can itself contain sensitive information. Keep all labels synthetic when reports may become public.

Failure thresholds apply to findings, not parser or I/O errors:

- `breaking`: fail on breaking findings.
- `warning`: fail on breaking findings and review warnings.
- `none`: collect findings without failing the contract gate.

JSON output has a versioned envelope (`schema_version: 1`), summary counts, sorted findings, and one outcome row per fixture. Impact counts count affected cases, not individual validation errors. At most 20 errors per fixture/side are retained; validity is not affected by the cap. Reports contain no clock, filesystem paths, or capture payloads. JUnit contains one test case per finding (or one passing case for a clean report); failure selection follows `--fail-on`. Review warnings below the threshold appear in `system-out`.

Malformed input, an invalid baseline fixture, unsupported input configuration, invalid CLI usage, or an inability to write a requested report returns exit `2` regardless of threshold.

## What remains outside the proof

No result establishes:

- Behavioral equivalence, business correctness, or side-effect safety.
- Transport, lifecycle, authentication, authorization, pagination implementation, or SDK compatibility.
- Whether a model chooses the same tool or constructs the same arguments.
- Compatibility of unstructured content blocks, resources, prompts, or notifications.
- That a server implements its advertised schema or will return a particular result.
- Safety against malicious or computationally expensive schemas.
- Coverage of every possible input or consumer assumption.

Combine this gate with server-side validation, client tests, integration tests, and human review. Refresh fixtures when real use teaches you a new boundary, but replace sensitive values with synthetic data first.

## Review checklist

1. Was every tools-list page captured under equivalent authorization and configuration?
2. Is the baseline actually the contract consumers rely on?
3. Do fixture IDs and property names avoid secrets and personal data?
4. Are baseline-invalid cases repaired or explicitly understood?
5. Are concrete input regressions intentional and accompanied by a migration plan?
6. Are output warnings checked against the producer and consumers, not dismissed mechanically?
7. Are unknown or complex schema edits reviewed before accepting a new baseline?
8. Did the gate finish successfully, rather than get skipped or fail while reading input?
