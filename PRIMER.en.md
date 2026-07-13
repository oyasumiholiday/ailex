# Ailex Primer (canonical reference for AI agents, v0.5.2)

> Put this document directly into an LLM's system prompt or context.
> It describes the *entire* language — syntax or functions not listed here do not exist.
> Measured result: with only this one-page primer as in-context learning, Claude Haiku 4.5 and
> Claude Opus 4.8 both wrote 16/16 tasks correctly on the first attempt (EXPERIMENTS.md §A3–A4).

## Shape of a program

```
type Point = {x : Float, y : Float}          -- type alias (declare before use)

fn dist (p : Point, q : Point) -> Float      -- function declaration
  ensures ret >= 0.0                          -- contract: property of the result (ret)
  eg dist({x = 0.0, y = 0.0}, {x = 3.0, y = 4.0}) = 5.0   -- contract: an example that is EXECUTED
body Float                                    -- body type restated
  sqrt((p.x - q.x) * (p.x - q.x) + (p.y - q.y) * (p.y - q.y))
end dist
```

- The body is **a single expression**. There is no `return` and there are no statements.
- Comments run from `--` to end of line.
- `eg` lines are executed; if they don't hold, the checker reports a contract violation.
  Include boundary cases (zero, empty list, negatives).
- Recursion and forward references are allowed. If a `main () -> T` exists, `run` evaluates it.

## Types

`Int` / `Float` / `Bool` / `String` / `List[T]` / `Option[T]` / records `{x : Float, y : Float}` / functions `(T) -> U`

- **Int and Float never mix.** Convert explicitly with `toFloat(i)` / `toInt(f)` (`toInt` truncates).
- Literals: `1` (Int), `1.0` (Float), `true`, `"s"`, `[1.0, 2.0]`, `{x = 1.0, y = 2.0}`
- Records are structural (field order does not matter). Access with `p.x` (chains: `c.center.x`).

## Expressions

- Operators: `+ - * /` (`/` truncates on Int; **`+` also concatenates Strings**),
  comparisons `== != > >= < <=` (`==` compares lists/records **deeply**), logic `&& || !`
- Branching is an expression: `if(cond, then, else)`
- Binding: `let x : T = expr in expr`
- Anonymous functions: `fn (x) => x * 2.0` (parameter type annotations optional)

## Built-in functions (this is all of them)

| Group | Functions |
|---|---|
| Numeric | `sqrt(Float)->Float`, `toFloat(Int)->Float`, `toInt(Float)->Int` |
| Lists | `length(v)->Int`, `get(v,i)->T`, `head(v)->T`, `tail(v)->List[T]`, `append(v,x)->List[T]` |
| Safe access | `headOr(v, default)->T`, `getOr(v, i, default)->T` (default on empty/out-of-range) |
| Higher-order | `map(v, f)` (**works on List and Option**), `filter(v, pred)`, `fold(v, init, fn (acc, x) => ...)` (init may be `[]` or `none`) |
| Numeric lists | `dot(a, b)->Float`, `sum(v)->Float` (for List[Float]) |
| Strings | `strlen`, `concat(s,t)`, `split(s,sep)->List[String]`, `join(xs,sep)`, `contains(s,t)->Bool`, `substring(s,i,j)`, `trim(s)`, `toString(number/Bool/String)->String` |
| Option | `some(x)->Option[T]`, `none`, `isSome(o)->Bool`, `unwrapOr(o, default)->T`, `find(v, pred)->Option[T]`, `parseInt(s)->Option[Int]`, `parseFloat(s)->Option[Float]` |

- `head`/`get` raise a **runtime error** on empty/out-of-range. Prefer `headOr`/`getOr` when unsure.
- **Operations that can fail return Option** (`find`/`parseInt`/`parseFloat`). Extract with `unwrapOr(o, default)`.
- `none` is only writable where its type is known from context
  (`let o : Option[Int] = none`, `if(c, some(x), none)`, an argument expecting an Option, a fold init).

## Common idioms

```
fold(xs, 0.0, fn (acc, x) => acc + x)                 -- sum
length(filter(v, fn (x) => x < 0.0))                  -- count matching
map(ps, fn (p) => p.x)                                -- project a field from records
fold(es, 0.0, fn (a, e) => if(e.amount > a, e.amount, a))  -- maximum
join(split(trim(s), " "), "-")                        -- re-join words with "-"
unwrapOr(parseInt(s), 0)                              -- String → Int (0 on failure)
"n=" + toString(n) + "!"                              -- string building with +
fold(lines, [], fn (acc, x) => append(acc, x))        -- fold init can be [] or none
unwrapOr(map(find(es, p), fn (e) => e.cat), "none")   -- find then transform (map over Option)
```

## Checking and diagnostics (for tools)

- `ailex check f.ax` → structured JSON diagnostics. Type errors include the **scope**
  (every usable name with its type); unknown record fields include the **list of available fields**;
  runtime failures come back as `{code: "runtime", detail}`.
- `ailex scope f.ax [fnName]` → machine-readable names-and-types in scope.
- `ailex run f.ax` → type-check + contract-check, then transpile to JavaScript and execute.
- When repairing from diagnostics, use **only names listed in `scope`/`fields`** — nothing else exists.
