# Contributing

Thank you for helping improve Ailex and IntentIR. This repository contains two related layers, so begin by identifying which behavior your change affects:

- Ailex surface language: `core/`, `.ax` examples, and `npm test`
- IntentIR semantic layer: `intentir/`, `.intent` examples, and Python tests
- Evaluation and demonstrations: `benchmarks/` and `demo/`
- Documentation, security, and release process: Markdown and `.github/`

## Before Opening a Pull Request

1. Open or reference an Issue for changes that alter syntax, semantics, stored data, Agent Tool contracts, benchmark methodology, or release behavior.
2. Keep the change scoped. Do not combine unrelated refactors with language or runtime behavior changes.
3. Add tests at the level affected by the change. Cross-backend semantics should be checked in every applicable runtime or generator.
4. Update user-facing documentation and the relevant Japanese validation report when behavior changes.
5. Do not commit credentials, private data, proprietary source, model-provider responses, or hidden evaluation tests.

AI-assisted contributions are welcome. The contributor remains responsible for the code, provenance, licenses, tests, and security of every submitted change. Do not send repository secrets or hidden benchmark material to an external model.

## Development Setup

Requirements:

- Node.js 23 or newer for Ailex
- Python 3.11 or newer for IntentIR
- Optional: `uv` for the locked MCP environment

```sh
npm ci --ignore-scripts
npm test

python3 -m unittest discover -s tests -v
python3 -m compileall -q intentir tests
uv lock --check
```

To run the optional MCP test:

```sh
uv sync --frozen --extra mcp
uv run --frozen --extra mcp python -m unittest discover -s tests -v
```

The concise setup and Container workflow are in [QUICKSTART.md](QUICKSTART.md).

## Pull Request Requirements

- Describe what changed, why it changed, and the affected compatibility boundary.
- Include the exact verification commands and results.
- Record untested environments, external services, and residual risks.
- Preserve deterministic output and structured diagnostics where the existing interface provides them.
- Treat Patch application, database migration, filesystem writes, and external model execution as explicit trust boundaries.
- Keep Agent/MCP writes disabled by default. Any change that expands write authority must include approval, diff, audit, and rollback considerations.
- Follow [SECURITY_QUALITY_CHECKLIST_JA.md](SECURITY_QUALITY_CHECKLIST_JA.md) for release-facing changes.

## Security Reports

Do not report vulnerabilities in a public Issue. Follow [SECURITY.md](SECURITY.md) and use GitHub Private Vulnerability Reporting.

## Licensing

Existing Ailex code is MIT-licensed. IntentIR and its new supporting files are Apache-2.0-licensed. By contributing, you agree that your change may be distributed under the license of the component it modifies. State the intended component when a new file does not have an obvious owner.
