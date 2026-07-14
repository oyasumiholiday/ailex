# IntentIR

IntentIR is an executable, machine-oriented semantic IR and a compact surface language for AI development workflows. It combines content-addressed program structure with contracts, CRUD effects, scenario tests, structured diagnostics, a transactional interpreter, relational SQLite projection, and TypeScript generation.

The project complements an AI-friendly language such as [Ailex](https://github.com/oyasumiholiday/ailex): concise source is used for authoring, while the canonical graph carries identity, dependencies, effects, constraints, and verification obligations. The design review is in [AILEX_ANALYSIS_JA.md](AILEX_ANALYSIS_JA.md).

IntentIR v0.7 has a Go/Python-like development loop (`check`, `test`, `run`, `migrate`, `build`, `fmt`), key and unique constraints, typed relational SQLite storage, and content-addressed migration plans. It is still a domain language rather than a general-purpose replacement for Go or Python.

## Example

```intentir
module TodoCrud

entity Task:
  id: UUID required key
  title: Text required
  done: Boolean default false

action CreateTask:
  input:
    id: UUID required
    title: Text required
  effects:
    insert Task

action CompleteTask:
  input:
    id: UUID required
  effects:
    update Task where id equals input.id set done = true
  ensures:
    affected Task.done equals true

action DeleteTask:
  input:
    id: UUID required
  effects:
    delete Task where id equals input.id

test "complete and delete":
  when CreateTask(id="task-1", title="buy milk")
  when CompleteTask(id="task-1")
  expect Task count equals 1
  expect Task exists with done true
```

The complete lifecycle sample is [examples/todo_crud.intent](examples/todo_crud.intent).

## Commands

```sh
# Static validation
python3 -m intentir check examples/todo_crud.intent

# Execute all scenarios
python3 -m intentir test examples/todo_crud.intent

# Run actions against a persistent SQLite repository
python3 -m intentir run examples/todo_crud.intent CreateTask \
  --input '{"id":"task-1","title":"buy milk"}' \
  --db /tmp/todo.db

python3 -m intentir run examples/todo_crud.intent CompleteTask \
  --input '{"id":"task-1"}' \
  --db /tmp/todo.db

# JSON state files remain available for portable one-shot execution
python3 -m intentir run examples/todo_crud.intent CreateTask \
  --input '{"id":"task-2","title":"portable"}' \
  --write-state /tmp/todo-state.json

# Plan and apply a storage schema migration
python3 -m intentir run examples/inventory_v1.intent CreateItem \
  --input '{"id":"item-1","name":"milk"}' \
  --db /tmp/inventory.db
python3 -m intentir migrate examples/inventory_v2.intent --db /tmp/inventory.db
python3 -m intentir migrate examples/inventory_v2.intent --db /tmp/inventory.db --apply

# Generate TypeScript, graph IR, or deterministic SQLite DDL
python3 -m intentir build examples/todo_crud.intent --target typescript
python3 -m intentir build examples/todo_crud.intent --target ir
python3 -m intentir build examples/todo_crud.intent --target sqlite

# Format, emit IR, and generate a Japanese report
python3 -m intentir fmt --check examples/todo_crud.intent
python3 -m intentir fmt -w examples/todo_crud.intent
python3 -m intentir ir examples/todo_crud.intent --canonical
python3 -m intentir report examples/todo_crud.intent -o /tmp/report.md
```

The v0.3 invocation remains compatible:

```sh
python3 -m intentir examples/todo.intent --emit verify
python3 -m intentir examples/todo.intent --emit typescript
```

## v0.7 capabilities

- Content-addressed entity, action, test, edge, effect, and obligation nodes
- Canonical JSON and a module-level SHA-256 semantic hash
- Scalar types: `Boolean`, `Integer`, `Number`, `Text`, `UUID`
- Entity identity with one `key` field and additional `unique` fields
- Requirements: non-empty input and equality
- Effects: `insert`, `update`, and `delete`; mutation selectors must be key or unique
- Repository capabilities inferred per action from its entity effects and operations
- Postconditions over `input`, `created Entity.field`, and `affected Entity.field`
- Multi-step scenario tests sharing one in-memory store
- Existence, non-existence, filtered existence, and entity-count expectations
- Static reference, binding, field, and type validation with stable diagnostic codes
- Transactional Python execution with JSON and SQLite state validation
- SQLite transactions, schema fingerprints, and concurrent-writer locking
- Deterministic Entity-to-table and Field-to-column SQLite projection
- SQLite type checks, defaults, `NOT NULL`, and `UNIQUE` constraints
- Relational records as the authoritative state with v0.5/v0.6 JSON compatibility
- Stored schema snapshots and content-addressed migration plans/operations
- Safe default/optional field additions and empty entity additions
- Explicit approval for destructive entity/field removal
- Automatic rejection of type changes and required fields without migration values
- TypeScript generation with runtime contracts, uniqueness checks, and `runIntentIRTests()`
- Idempotent source formatting with full-line comment preservation
- Japanese static and runtime validation reports

`update` and `delete` must select a `key` or `unique` field and still verify exactly one match at runtime. Duplicate inserts, zero matches, and multiple matches fail atomically, so an action never commits partial state. SQLite state is bound to the content hash of the entity schema; schema changes must pass through an explicit `migrate` plan instead of silently reusing incompatible data.

In `relational-v1`, each Entity has a deterministic physical table and each Field has a typed column. The metadata row retains the schema snapshot and compatibility hash, while `state_json` is no longer authoritative. Existing v0.5/v0.6 JSON databases remain readable and are converted on the next successful save or migration apply.

`migrate` is plan-only by default. `--apply` performs the state transform and target-schema validation in one SQLite transaction. Destructive operations additionally require `--allow-destructive`; changes that need per-record values remain blocked as `manual`.

## Architecture

- `intentir/parser.py`: indentation-sensitive surface parser
- `intentir/expressions.py`: structured conditions, effects, calls, and expectations
- `intentir/validator.py`: static diagnostics and type/reference checks
- `intentir/ir.py`: content-addressed graph and verification obligations
- `intentir/verifier.py`: transactional interpreter and scenario verifier
- `intentir/storage.py`: SQLite state repository and storage schema fingerprints
- `intentir/sqlite_projection.py`: deterministic relational projection and DDL generation
- `intentir/migration.py`: migration diff, safety classification, and state transforms
- `intentir/generators/typescript.py`: TypeScript backend and generated test runner
- `intentir/formatter.py`: canonical source formatter
- `intentir/cli.py`: command-line development workflow
- `intentir/reports.py`: Japanese validation reports

## Verification

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q intentir tests
```

The suite contains 34 tests, including relational projection, physical SQLite constraints, metadata tamper protection, migration table-rebuild rollback, v0.5/v0.6 database compatibility, cross-process persistence, and a Node.js E2E run of generated TypeScript CRUD and uniqueness checks.

## Current boundaries

SQLite now stores Entity records in relational tables, but the interpreter still loads and rewrites a complete Module State per Action rather than issuing incremental SQL. Migration cannot infer renames or synthesize missing values for new required fields. IntentIR also lacks functions, general expressions, branching, loops, relationships, modules/imports, package management, declared HTTP/File capabilities, async I/O, and a debugger. The next practical step is functions and module boundaries, followed by Entity relations, incremental repositories, and hash-guarded Patch IR for AI edits.
