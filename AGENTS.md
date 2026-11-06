# Instructions for AI Agents

The active project is **IntentIR**, an AI-native intermediate language for creating, exchanging, verifying, and patching structured typed programs. Read [GOALS_JA.md](GOALS_JA.md) for direction and [README.md](README.md) and [QUICKSTART.md](QUICKSTART.md) for the public implementation and workflows.

## Public Scope

- `intentir/`: Python compiler, semantic graph, validators, interpreter, generators, guarded Patch, CLI, Agent Tools, and optional MCP stdio server.
- `tests/`: public regression tests.
- `examples/*.intent`: public textual IntentIR examples.
- `intentir/templates/todo/`: packaged Todo starter and its guide.

This checkout and the published alpha wheel accept textual `.intent`, not direct structured `.intent.json` authoring. The latter is local-development-only work, absent here. Do not invent its syntax, link absent specifications, suggest private examples, or describe unpublished modules as public features. Canonical graph JSON, Patch envelopes, and Agent Tool JSON arguments are distinct from authoring JSON.

Inspect existing implementation, tests, configuration, and CI before changing behavior. Keep changes scoped and preserve unrelated work. Do not add dependencies or regenerate lockfiles merely for documentation.

## CodeGraph When Available

If CodeGraph and an initialized index are available, prefer `codegraph_context` for structural questions and one capped `codegraph_explore` for related source. Use native search and file reads for literal text or focused reads of an identified file. Do not assume a fresh clone has an initialized index; if the tool reports it is uninitialized, ask before running `codegraph init -i`.

## Write and Verify

Use Python >=3.11 and Node.js 24, matching CI, for generated TypeScript execution. From the repository root:

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q intentir tests
python3 -m intentir check examples/todo_crud.intent --json
python3 -m intentir test examples/todo_crud.intent --json
```

For a changed program, replace the example path with that program and run both `check` and `test`. Include executable boundary cases. Repair diagnostics using supported syntax and names in scope; do not infer correctness from formatting or schema acceptance alone.

The core package has no mandatory runtime dependencies. For optional MCP coverage, use the declared extra and frozen environment:

```sh
uv sync --frozen --extra mcp
uv run --frozen --extra mcp python -m unittest discover -s tests -v
```

Report actual results, optional dependency skips, and missing Node execution. Generated TypeScript execution is not standalone typechecking. Do not claim complete coverage when checks did not run.

## Change and Safety Boundaries

- Preserve content-addressed semantics and stale-source rejection. Construct Patch envelopes using current IDs, `baseModuleId`, and original-base `expectedId` preconditions; never update guards merely to conceal a behavioral change.
- Inspect supported semantic member paths and preview a Patch before an explicitly authorized application. A structural difference is not automatically a replayable Patch.
- Keep static checking, affected-test verification, and full scenario execution distinct. Passing examples is not proof for all inputs.
- Shared semantics and generator changes need Python and generated-TypeScript regression coverage with independent expected results.
- Source changes and SQLite schema migration are separate operations. Preserve the stopped-writer paired backup and restore procedures in [Quickstart](QUICKSTART.md).
- Keep Agent/MCP writes disabled by default. Enable writes only within explicit approval and audit boundaries.
- Do not describe guarded patches or structural checks as a complete runtime sandbox.
- Keep deterministic demos, handcrafted fixtures, paid model trials, cross-vendor AI exchange, and independent human use distinct as evidence.

## Legacy and Licensing

`core/`, `.ax` examples, and Ailex primers are retained legacy material, not IntentIR syntax or current authoring instructions. Do not expand them or require a language merger by default. For explicitly scoped compatibility work, use the [legacy index](docs/LEGACY_AILEX.md), including its browser build/check guidance.

The original public Ailex agent instructions are preserved byte-for-byte in [the archive](docs/AILEX_AGENT_INSTRUCTIONS_ARCHIVE.md). Relative links there retain their historical repository-root interpretation.

Preserve [MIT](LICENSE) licensing for Ailex and [Apache-2.0](LICENSE-APACHE) licensing for IntentIR and its new supporting files.

## Approval and Evidence

Paid APIs, credential use, private-data transmission, publication, external distribution, and deployment require separate approval for the intended action and scope. Historical approvals and available credentials do not authorize a new run. Ordinary reading of public official documentation needs no extra approval. Do not commit, push, release, or deploy unless requested.

Check a relevant source before attributing academic support. Label unsupported wording as provisional and ask for the passage or page when needed. Research submissions and historical experiment criteria are not gates for ordinary IntentIR development.
