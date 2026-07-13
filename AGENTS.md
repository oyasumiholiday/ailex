# Instructions for AI agents

You are working with **Ailex**, a small typed language designed to be written by AI.

## Learn the language (one page)

Read [PRIMER.en.md](PRIMER.en.md). It is the complete language — do not use syntax or functions
that are not listed there. If a diagnostic lists `scope` or `fields`, only those names exist.

## Write–verify loop

```sh
node core/cli.ts check file.ax    # types + contracts → JSON diagnostics (exit 0 = ok)
node core/cli.ts run file.ax      # check, then transpile to JS and execute (runs `eg` contracts and main())
node core/cli.ts scope file.ax fnName   # names and types usable inside fnName (JSON)
```

1. Write the `.ax` file. Give every function at least one `eg` contract, including a boundary case
   (empty list, zero, negative, absent value).
2. Run `check`. If it fails, read the JSON: `type_mismatch` includes `expected`/`actual` and `scope`;
   `unknown_field` includes the available `fields`. Repair using only names from those lists.
3. Run `run`. Contract violations report the failing call with expected vs actual values.

## Rules of thumb

- The body of a function is one expression. Build up with `let ... in`, not statements.
- Prefer `headOr`/`getOr`/`find`/`unwrapOr` over `head`/`get` when emptiness is possible.
- Operations that can fail (`find`, `parseInt`, `parseFloat`) return `Option[T]` — handle the `none` case.
- `map` works on both `List[T]` and `Option[T]`. `fold` init may be `[]` or `none`.
- Strings concatenate with `+`. Int and Float never mix; convert explicitly.

## Working on the language implementation itself

- Core: `core/lang.ts` (lexer/parser/checker/interpreter), `core/tojs.ts` (JS backend), `core/cli.ts`.
- Any change must keep `npm test` green (89 conformance cases; they verify the two backends agree).
- New stdlib functions need conformance cases with `evals` (those run on BOTH backends; `contracts`
  alone runs only on the interpreter and once missed a backend divergence).
- Design changes should be grounded in evidence: a dogfooding pain point (DOGFOOD.md) or a measured
  model-prior mismatch (EXPERIMENTS.md). The project's core lesson: *an invalid form that models
  repeatedly write is a measurement of a language gap, not a model error.*
