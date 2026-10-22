# Standards, dependencies, and related work

MCP Contract Guard is an independent, original implementation. It does not vendor or copy the code of the related MCP projects listed below. This document records relevant standards and acknowledges prior work; it does not imply endorsement or affiliation.

## Standards

- [Model Context Protocol, tools specification (2026-07-28)](https://modelcontextprotocol.io/specification/2026-07-28/server/tools): tool definitions, listing, input schemas, structured results, output schemas, and the trust limits of annotations.
- [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12): the schema dialect used by this project's validation profile.

The repository's example tools, fixture data, prose, and comparison implementation are original. Examples describe an invented notes service and are not captured from a real account or server.

## Runtime dependencies

These packages are installed normally as dependencies; their code is not copied into the repository. Their own licenses continue to apply.

- [`jsonschema`](https://github.com/python-jsonschema/jsonschema), [MIT license](https://github.com/python-jsonschema/jsonschema/blob/main/COPYING): Python JSON Schema validation. [Documentation](https://python-jsonschema.readthedocs.io/en/stable/).
- [`referencing`](https://github.com/python-jsonschema/referencing), [MIT license](https://github.com/python-jsonschema/referencing/blob/main/COPYING): reference-resolution infrastructure. [Documentation](https://referencing.readthedocs.io/en/stable/).

See `pyproject.toml` for the declared version constraints and development tools. Installed distributions also include their own license metadata and may have additional transitive dependencies. This list is an attribution guide, not a complete software bill of materials for a particular environment.

## Related projects

MCP schema snapshotting and contract checking have established prior art:

- [mcp-contracts/mcp-contracts](https://github.com/mcp-contracts/mcp-contracts): MCP schema snapshot, comparison, and validation tooling.
- [cisco-open/mcptoolkit-contract](https://github.com/cisco-open/mcptoolkit-contract): lifecycle tooling including tool dumps, documentation, and comparisons.
- [gulmezeren2-byte/mcp-contract](https://github.com/gulmezeren2-byte/mcp-contract): snapshot-based MCP tool contract checks with change classifications.
- [modelcontextprotocol/conformance](https://github.com/modelcontextprotocol/conformance): official protocol-level conformance testing, complementary to this offline file-based gate.
- [modelcontextprotocol/inspector](https://github.com/modelcontextprotocol/inspector): interactive MCP server inspection and testing.

MCP Contract Guard does not claim to invent schema diffing or MCP contract tests. Its chosen scope is offline file comparison with synthetic fixture impact and CI reports. Evaluate related tools against your own capture, runtime, and review needs.

## Updating this file

When adding or embedding third-party material, record its source, license, and any required notices here. Merely linking a project does not authorize copying its implementation.
