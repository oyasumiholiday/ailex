# IntentIR 0.14.0 Prerelease Notes

This is the initial GitHub prerelease for tag `intentir-v0.14.0`. The release artifacts are the `intentir-0.14.0-py3-none-any.whl` wheel and GitHub's source archive. IntentIR is versioned `0.14.0`; the separate Ailex TypeScript language remains at `0.5.3`.

## Included

- Content-addressed IntentIR compilation, validation, executable tests, pure functions, CRUD actions, and relational SQLite persistence.
- Guarded semantic Patch planning and application, schema migration planning and application, TypeScript/IR/SQLite builds, and reports.
- Nine model-independent Agent Tools through the dependency-free CLI and optional local MCP stdio server.
- Offline benchmark and concurrent-agent demonstration workflows, plus budget-guarded model-pilot preflight and execution controls.

Start with the [wheel-installed standalone demo](https://github.com/oyasumiholiday/ailex/blob/intentir-v0.14.0/QUICKSTART.md#install-the-prerelease-wheel) or the [persistent Todo, Patch, and migration recipe](https://github.com/oyasumiholiday/ailex/blob/intentir-v0.14.0/QUICKSTART.md#persistent-todo-patch-and-migration).

## Limitations

- IntentIR and Ailex remain separate prototypes; no Ailex-to-IntentIR lowering pipeline is implemented.
- IntentIR is a domain language and research prototype, not a general-purpose language or native binary.
- The MCP adapter requires its optional dependency. Source-writing Agent Tools remain disabled unless explicitly enabled.
- The budget counter has offline test coverage but no live service validation. Accounting uses fixed protocol prices and excludes any separate count-request fees; see [Budget Guard validation](https://github.com/oyasumiholiday/ailex/blob/intentir-v0.14.0/BUDGET_GUARD_VALIDATION_JA.md).
- Published calibration results are same-task measurements and do not establish general method superiority or external human validation.
