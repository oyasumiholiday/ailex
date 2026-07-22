# Ailex

> This document covers the Ailex surface language. See the [repository overview](README.md) for the combined Ailex + IntentIR system.

**A small typed language designed for AI to write.** Executable example-contracts, structured diagnostics that disclose scope, and two backends (interpreter + JavaScript) verified against the same test suite.

[日本語版 README](README.ja.md)

```
type Point = {x : Float, y : Float}

fn dist (p : Point, q : Point) -> Float
  ensures ret >= 0.0
  eg dist({x = 0.0, y = 0.0}, {x = 3.0, y = 4.0}) = 5.0
body Float
  sqrt((p.x - q.x) * (p.x - q.x) + (p.y - q.y) * (p.y - q.y))
end dist
```

The `eg` line is not documentation — it is an **executed contract**. `ailex run` checks it and reports violations as structured diagnostics.

## Why an AI-first language (every claim is backed by measurement)

1. **Diagnostics disclose what is available.** Type errors carry the scope (every usable name with its type) as JSON; unknown record fields carry the list of available fields. In repair-loop experiments, this disclosure turned divergent name-guessing on unknown APIs into a one-step fix (pass@k 80% → 98–100%, [EXPERIMENTS.md](EXPERIMENTS.md) §Q1).
2. **Syntax does not fight the model's prior.** Infix operators; lambdas with optional annotations (`fn (acc, x) => ...`); `+` concatenates strings; `map` works on Option. Each of these exists because measurement said so: when lambda annotations were mandatory, *every* first-attempt failure was that parse error — fixing the language took both Claude Haiku and Claude Opus from 50–63% to **100%** first-attempt correctness (§A1→A2). When `map` didn't work on Option, both models wrote the same natural expression and failed identically; after the fix their unchanged first answers became correct (§A3→A4).
3. **Contracts are executable examples.** The smallest unit of specification (`eg`) lives next to the function and is always checked.
4. **Behavior you can rely on.** Two backends (tree-walking interpreter / JavaScript transpiler) are continuously verified to agree on the same 89-case conformance suite. `==` compares lists and records deeply. Runtime failures return structured diagnostics instead of stack traces.

Teaching the language costs one page: with [PRIMER.en.md](PRIMER.en.md) alone as context, Claude Haiku 4.5 and Claude Opus 4.8 wrote **16/16 tasks** (records, Option, string processing included) correctly on the first attempt. That measurement is the language's acceptance test and runs on every language change.

## Use it

Requires Node.js 23+ (runs TypeScript directly).

```sh
node core/cli.ts run examples/points.ax     # check, transpile to JS, execute
node core/cli.ts check file.ax              # types + contracts → structured JSON diagnostics
node core/cli.ts scope file.ax dist         # names and types in scope (JSON)
node core/cli.ts fmt file.ax                # canonical formatting
node core/cli.ts emit-js file.ax            # show the generated JavaScript
# inside the repo: ./ailex run ...  |  npm bin: bin/ailex.js (ready for npm i -g / npx; not yet published)
```

Tests: `npm test` (89 conformance cases, including interpreter/JS backend agreement).

## Teach it to your agent

Ailex is designed to be taught in-context, not pretrained:

- Drop [PRIMER.en.md](PRIMER.en.md) into the agent's system prompt or context. That is the entire language.
- Point the agent at `ailex check` / `ailex run` for the write–verify loop. Diagnostics are JSON and include scope, so agents recover from errors without guessing.
- Repo-level instructions for coding agents live in [AGENTS.md](AGENTS.md).
- A ready-made Claude Code skill (which lets the agent *propose* Ailex when a task fits) is in [agent/SKILL.md](agent/SKILL.md).

## The language (v0.5.3)

Types `Int / Float / Bool / String / List[T] / Option[T] / records / (T)->U`, type aliases, infix operators, `if` expressions, `let..in`, recursion, anonymous functions (annotations optional), `map/filter/fold` (map also on Option), string stdlib (`split/join/contains/substring/trim/toString`, `+` concatenation), safe access (`headOr/getOr`), `Option[T]` (`some/none/isSome/unwrapOr` and Option-returning `find/parseInt/parseFloat`), contracts (`requires/ensures/eg`). Full reference: [PRIMER.en.md](PRIMER.en.md). Design history: [SPEC.md](SPEC.md) (Japanese).

## Honest status

- A solo project moving from research prototype to language release. The API is not stable.
- Not yet supported: effects/IO, modules, pattern matching, immediate lambda calls, user-defined polymorphism. `head/get` raise runtime errors on empty/out-of-range (prefer `headOr/getOr`/`find`).
- Every design decision is grounded in measurement or dogfooding ([DOGFOOD.md](DOGFOOD.md), [EXPERIMENTS.md](EXPERIMENTS.md), both Japanese). Failed experiments and retracted claims are kept in those documents — including the original hypothesis that *machine-readable format* of feedback matters (measurement refuted it; the information content is what matters).
- The "models were never trained on this language" problem is answered by in-context teaching, verified at 16-task scale. Larger scale is unverified.

## Documents

| File | Contents | Language |
|---|---|---|
| [PRIMER.en.md](PRIMER.en.md) | Canonical one-page reference for agents | English |
| [AGENTS.md](AGENTS.md) | Instructions for coding agents in this repo | English |
| [agent/SKILL.md](agent/SKILL.md) | Claude Code skill (lets an agent propose and use Ailex) | English |
| [PRIMER.md](PRIMER.md) | 上と同内容の日本語版 | 日本語 |
| [README.ja.md](README.ja.md) | この README の日本語版 | 日本語 |
| [SPEC.md](SPEC.md) | Spec and design history | 日本語 |
| [CHANGELOG.md](CHANGELOG.md) | Version history with evidence links | 日本語 |
| [README.md](README.md) | Promoted IntentIR semantic layer and combined system overview | English / 日本語 |
| [DOGFOOD.md](DOGFOOD.md) / [EXPERIMENTS.md](EXPERIMENTS.md) | Pain-point log / measurement log (incl. negative results) | 日本語 |
