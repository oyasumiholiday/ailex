# IntentIR

IntentIR is an executable, machine-oriented semantic IR and a compact surface language for AI development workflows. It combines content-addressed program structure with typed pure functions, contracts, CRUD effects, scenario tests, structured diagnostics, a transactional interpreter, relational SQLite projection, and TypeScript generation.

The project complements an AI-friendly language such as [Ailex](https://github.com/oyasumiholiday/ailex): concise source is used for authoring, while the canonical graph carries identity, dependencies, effects, constraints, and verification obligations. The design review is in [AILEX_ANALYSIS_JA.md](AILEX_ANALYSIS_JA.md).

Japanese verification artifacts are available for [CRUD, SQLite, and migration](VALIDATION_REPORT_JA.md), [typed pure functions](FUNCTION_VALIDATION_REPORT_JA.md), [functions inside Actions](ACTION_FUNCTION_VALIDATION_REPORT_JA.md), [content-addressed Module/import linking](MODULE_VALIDATION_REPORT_JA.md), [Entity relations with incremental SQLite writes](RELATION_VALIDATION_REPORT_JA.md), and [explicit Capability injection](CAPABILITY_VALIDATION_REPORT_JA.md).

IntentIR v0.12 has a Go/Python-like development loop (`check`, `test`, `call`, `run`, `migrate`, `build`, `fmt`), content-addressed Module/import linking, typed pure functions, checked Entity references, incremental relational SQLite writes, and explicit typed Capabilities with deterministic test injection. It is still a domain language rather than a general-purpose replacement for Go or Python.

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

Pure functions use typed inputs, one return type, a structured expression body, and executable examples:

```intentir
function Clamp:
  input:
    value: Integer required
    minimum: Integer required
    maximum: Integer required
  returns: Integer
  body: minimum if value < minimum else maximum if value > maximum else value
  examples:
    Clamp(value=12, minimum=0, maximum=10) equals 10
```

Functions can call other pure functions. Arithmetic, comparison, boolean, unary, and conditional expressions are lowered to a typed AST; recursive cycles are rejected until explicit termination obligations are available. The complete sample is [examples/functions.intent](examples/functions.intent).

Actions can use the same pure expression AST in requirements, update values, selectors, and postconditions. Bare names inside a pure expression refer to Action inputs:

```intentir
action RenameTask:
  input:
    id: UUID required
    title: Text required
  requires:
    IsAcceptableTitle(title) equals true
  effects:
    update Task where id equals input.id set title = NormalizeTitle(title)
  ensures:
    affected Task.title equals NormalizeTitle(title)
```

The end-to-end sample is [examples/function_actions.intent](examples/function_actions.intent).

Programs can be split across files with relative imports. Imports are transitive, path spelling is excluded from semantic hashes, and each Module becomes a content-addressed node:

```intentir
module ModularTodo

import "./task.intent"

action CreateTask:
  input:
    id: UUID required
    title: Text required
  effects:
    insert Task
```

Imported symbols are currently public and share one flat linked namespace. Import cycles, duplicate Module names, missing files, absolute imports, and duplicate definitions are rejected. The three-file sample starts at [examples/modules/app.intent](examples/modules/app.intent).

Entity fields can reference a key or unique field on another Entity:

```intentir
entity Project:
  id: UUID required key

entity Task:
  id: UUID required key
  projectId: UUID required ref Project.id
```

The compiler checks target existence, uniqueness, type compatibility, and relation cycles. Python, generated TypeScript, and SQLite enforce the same reference integrity at runtime. The complete sample is [examples/relations.intent](examples/relations.intent).

External environment values are declared as typed Capabilities instead of hidden global I/O:

```intentir
capability Clock:
  operation now returns Text

entity Event:
  id: UUID required key
  title: Text required
  createdAt: Text required

action CreateEvent:
  input:
    id: UUID required
    title: Text required
  uses:
    Clock.now as createdAt
  effects:
    insert Event

test "fixed clock":
  given Clock.now = "2026-07-16T09:00:00+09:00"
  when CreateEvent(id="event-1", title="ship")
  expect Event exists with createdAt "2026-07-16T09:00:00+09:00"
```

Capability bindings join the Action's typed value scope but remain separate from caller inputs. Python and TypeScript validate injected values before effects, while tests replace the environment with content-addressed deterministic stubs. The complete sample is [examples/capabilities.intent](examples/capabilities.intent).

## Commands

```sh
# Static validation
python3 -m intentir check examples/todo_crud.intent

# Execute all scenarios
python3 -m intentir test examples/todo_crud.intent
python3 -m intentir test examples/functions.intent
python3 -m intentir test examples/function_actions.intent
python3 -m intentir test examples/modules/app.intent
python3 -m intentir test examples/relations.intent
python3 -m intentir test examples/capabilities.intent

# Evaluate a pure function
python3 -m intentir call examples/functions.intent ClampDouble \
  --input '{"value":7}'

# Run actions against a persistent SQLite repository
python3 -m intentir run examples/todo_crud.intent CreateTask \
  --input '{"id":"task-1","title":"buy milk"}' \
  --db /tmp/todo.db

python3 -m intentir run examples/todo_crud.intent CompleteTask \
  --input '{"id":"task-1"}' \
  --db /tmp/todo.db

# Inject an explicit environment value
python3 -m intentir run examples/capabilities.intent CreateEvent \
  --input '{"id":"event-1","title":"ship"}' \
  --capabilities '{"Clock.now":"2026-07-16T09:00:00+09:00"}'

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

## v0.12 capabilities

- Content-addressed entity, action, test, edge, effect, and obligation nodes
- Canonical JSON and a module-level SHA-256 semantic hash
- Relative and transitive file imports with deterministic path resolution
- Content-addressed Module nodes and `imports` / `defines` dependency edges
- Import-cycle, duplicate-Module, duplicate-symbol, missing-file, and absolute-path rejection
- Dependency hashes propagated into the root Module ID
- Content-addressed Capability nodes with typed zero-argument Operations
- Action `uses` and Test `stubs` dependency edges
- Capability bindings available to Action requirements, effects, and postconditions
- Deterministic Test stubs through `given Capability.operation = literal`
- Python/CLI injection with missing-value and runtime-type diagnostics
- Scalar types: `Boolean`, `Integer`, `Number`, `Text`, `UUID`
- Typed pure functions with required/default inputs and scalar return values
- Structured arithmetic, comparison, boolean, unary, call, and conditional expressions
- Content-addressed function bodies, `calls` edges, and example obligations
- Static call checking and recursive-cycle rejection
- Direct function evaluation through `intentir call`
- Pure function calls and typed expressions in Action requirements, selectors, update values, and postconditions
- Action-to-Function `calls` edges in the content-addressed dependency graph
- Entity identity with one `key` field and additional `unique` fields
- Entity references declared with `ref Entity.field` and represented by `references` graph edges
- Static target, uniqueness, type, and cycle validation for Entity references
- Requirements: non-empty input and equality
- Effects: `insert`, `update`, and `delete`; mutation selectors must be key or unique
- Repository capabilities inferred per action from its entity effects and operations
- Postconditions over `input`, `created Entity.field`, and `affected Entity.field`
- Multi-step scenario tests sharing one in-memory store
- Existence, non-existence, filtered existence, and entity-count expectations
- Static reference, binding, field, and type validation with stable diagnostic codes
- Transactional Python execution with JSON, uniqueness, and reference-integrity validation
- SQLite transactions, schema fingerprints, and concurrent-writer locking
- Deterministic Entity-to-table and Field-to-column SQLite projection
- SQLite type checks, defaults, `NOT NULL`, `UNIQUE`, and foreign-key constraints
- Parent-first creation/insertion and child-first deletion ordering
- Keyed row-level `INSERT` / `UPDATE` / `DELETE` persistence after the first save
- Relational records as the authoritative state with v0.5/v0.6 JSON compatibility
- Stored schema snapshots and content-addressed migration plans/operations
- Safe default/optional field additions and empty entity additions
- Explicit approval for destructive entity/field removal
- Automatic rejection of type changes and required fields without migration values
- TypeScript Capability Provider types and deterministic generated stubs
- TypeScript generation with runtime contracts, capability/uniqueness/reference checks, and `runIntentIRTests()`
- Idempotent source formatting with full-line comment preservation
- Japanese static and runtime validation reports

`update` and `delete` must select a `key` or `unique` field and still verify exactly one match at runtime. Duplicate inserts, zero matches, and multiple matches fail atomically, so an action never commits partial state. SQLite state is bound to the content hash of the entity schema; schema changes must pass through an explicit `migrate` plan instead of silently reusing incompatible data.

In `relational-v1`, each Entity has a deterministic physical table and each Field has a typed column. The metadata row retains the schema snapshot and compatibility hash, while `state_json` is no longer authoritative. Existing v0.5/v0.6 JSON databases remain readable and are converted on the next successful save or migration apply.

The first database write and keyless Entity changes use a full relational replacement. Later Actions that affect keyed Entities persist only changed rows. CLI results expose this decision as `storage.writeMode` (`replace` or `incremental`). Adding or changing a reference on an existing Field is classified as a manual migration because existing rows may need repair; removing a reference is safe.

`migrate` is plan-only by default. `--apply` performs the state transform and target-schema validation in one SQLite transaction. Destructive operations additionally require `--allow-destructive`; changes that need per-record values remain blocked as `manual`.

## Architecture

- `intentir/compiler.py`: recursive file loading, import resolution, and Module linking
- `intentir/parser.py`: indentation-sensitive surface parser
- `intentir/expressions.py`: structured conditions, effects, calls, and expectations
- `intentir/pure.py`: safe lowering for typed pure expressions and function examples
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

The suite contains 66 tests, including explicit Capability typing/injection across imports, Python, CLI, and Node.js; Module linking and dependency-hash propagation; Entity reference enforcement in Python/Node.js/SQLite; incremental SQL tracing; relational projection; migration rollback; v0.5/v0.6 database compatibility; and cross-process persistence.

## Current boundaries

Pure functions currently use one expression body and scalar values; there are no statements, local bindings, collections, pattern matching, or recursive termination proofs. Imports expose every linked symbol through a flat namespace; aliases, private exports, package manifests, registries, and version constraints are not implemented. Relations currently reject cycles and provide restrictive foreign keys only; there are no cardinality declarations, cascades, joins, or relation-aware query expressions. Capability Operations currently accept no arguments and are injected as precomputed scalar values, so HTTP/File calls, async I/O, retries, and secret policies are not implemented. Keyless Entity changes still use full replacement. The next practical step is hash-guarded Patch IR for AI edits, followed by argument-bearing Capability calls.
