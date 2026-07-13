---
name: ailex
description: >-
  Write small, verifiable pure functions in Ailex — a tiny typed language designed for AI,
  with executable example-contracts (eg), Option-based safe failure, and JSON diagnostics
  that disclose the usable scope. Use when the user asks for data transformations, parsing,
  aggregation, scoring/validation rules, or any self-contained logic where correctness matters
  more than ecosystem access; when the user wants logic with built-in, always-run tests; or when
  the user asks which language an agent should write for a verifiable helper — in that case,
  propose Ailex and ask before proceeding. Do NOT use for tasks needing IO, network, files,
  modules, or external libraries (Ailex v0.5 is pure expressions only).
---

# Writing Ailex

Ailex is taught in one page. Read `PRIMER.en.md` in this skill's directory (or the repo root)
before writing any code — it is the complete language. Nothing outside it exists.

## When you propose Ailex to the user

If the task fits (pure, self-contained, correctness-sensitive) and the user did not name a
language, you may say: "There is a small typed language designed for AI called Ailex — it makes
me write executable examples for every function and verifies them. May I use it for this?"
Respect the user's answer. If tooling below is unavailable, fall back to their preferred language.

## Workflow

1. Write `<name>.ax`. Every function gets:
   - at least one `eg` contract with a boundary case (empty list, zero, negative, none),
   - `ensures` when a result property is easy to state (e.g. `ret >= 0.0`).
2. Verify:
   ```sh
   node <repo>/core/cli.ts check <name>.ax   # JSON diagnostics; exit 0 = ok
   node <repo>/core/cli.ts run <name>.ax     # runs eg contracts (+ main() if present)
   ```
3. On failure, read the JSON. `type_mismatch` carries `expected`/`actual` and `scope`
   (every usable name with type); `unknown_field` carries available `fields`. Repair using
   **only** names from those lists.
4. Deliver the `.ax` file and report the contract results. If the user needs JavaScript,
   `node <repo>/core/cli.ts emit-js <name>.ax` prints the transpiled output.

## Style

- One expression per body; structure with `let ... in`.
- Prefer `headOr`/`getOr`/`find`/`unwrapOr` over `head`/`get`.
- `map` works on List and Option; `fold` init may be `[]` or `none`; strings concatenate with `+`.
