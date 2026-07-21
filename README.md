# Ailex + IntentIR

This repository contains two layers of one AI-first programming system:

- [Ailex](AILEX_README.md) is the compact typed surface language that AI and people write.
- IntentIR is the executable, machine-oriented semantic layer that AI agents and compilers transform safely.

Start with the [short Quickstart](QUICKSTART.md) for local and Container commands.

IntentIR combines content-addressed program structure with typed pure functions, contracts, CRUD effects, scenario tests, structured diagnostics, a transactional interpreter, relational SQLite projection, and TypeScript generation. Concise Ailex source is intended for authoring, while the canonical graph carries identity, dependencies, effects, constraints, and verification obligations. The design review is in [AILEX_ANALYSIS_JA.md](AILEX_ANALYSIS_JA.md).

Japanese verification artifacts are available for [CRUD, SQLite, and migration](VALIDATION_REPORT_JA.md), [typed pure functions](FUNCTION_VALIDATION_REPORT_JA.md), [functions inside Actions](ACTION_FUNCTION_VALIDATION_REPORT_JA.md), [content-addressed Module/import linking](MODULE_VALIDATION_REPORT_JA.md), [Entity relations with incremental SQLite writes](RELATION_VALIDATION_REPORT_JA.md), [explicit Capability injection](CAPABILITY_VALIDATION_REPORT_JA.md), [hash-guarded semantic patches](PATCH_VALIDATION_REPORT_JA.md), and the [Agent/MCP interface](AGENT_MCP_VALIDATION_REPORT_JA.md).

Security and quality reviews use the project-specific [Japanese checklist](SECURITY_QUALITY_CHECKLIST_JA.md), derived from the preserved [full review criteria](docs/SECURITY_QUALITY_REVIEW_CRITERIA_JA.md). The current findings and release blockers are recorded in the [2026-07-21 baseline review](SECURITY_QUALITY_BASELINE_2026-07-21_JA.md).

The primary external milestone is an [ICSE 2027 Tool Demonstration submission](ICSE_2027_DEMO_SUBMISSION_PLAN_JA.md) by October 23, 2026 AoE. Development is therefore focused on a reproducible concurrent-agent demo, an easy-to-run public artifact, and a controlled editing benchmark.

IntentIR v0.14 exposes its content-addressed graph, impact analysis, verifier, builders, and transactional Patch protocol through nine model-independent Agent Tools. The same structured contract is available through a dependency-free CLI and an optional local MCP stdio server. IntentIR is still a domain language rather than a general-purpose replacement for Go or Python.

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

# Preview an AI-oriented semantic patch; source remains unchanged
python3 -m intentir patch \
  examples/todo_crud.intent examples/add_task_priority.patch.json

# Apply only after the hash guards and requested obligations succeed
python3 -m intentir patch \
  examples/todo_crud.intent examples/add_task_priority.patch.json --apply

# Invoke the dependency-free structured Agent API
python3 -m intentir agent intentir.describe_module \
  --root . \
  --arguments '{"source":"examples/todo_crud.intent"}'

python3 -m intentir agent intentir.get_impact \
  --root . \
  --arguments '{"source":"examples/todo_crud.intent","symbols":["entity:Task"]}'

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

Install the optional official MCP Python SDK and start a local stdio server:

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[mcp]'
.venv/bin/intentir-mcp --root .
```

The MCP client must launch `intentir-mcp` as a subprocess. The server intentionally exposes stdio only and rejects every source path outside `--root`. Source writes are disabled by default; start it with `--allow-writes` only when the host provides an explicit user approval and audit flow for `intentir.apply_patch`.

## Concurrent-agent demonstration

Run the self-contained ICSE demonstration scenario:

```sh
python3 -m intentir demo concurrent-agent
```

Two agents start from the same content-addressed Module and Entity IDs. Agent A commits first, Agent B's stale Patch is rejected with `stale_base_module`, and Agent B refreshes the graph before applying a verified replacement Patch. The command also verifies the final program and builds TypeScript and SQLite artifacts. It uses a temporary workspace and does not modify the repository fixture. Use `--json` for machine-readable evidence; see [demo/concurrent_agent](demo/concurrent_agent/README.md) for the scenario source and details.

## IntentBench-Evolve

Run the four-condition benchmark harness smoke suite:

```sh
python3 -m intentir benchmark \
  benchmarks/intentbench_evolve/smoke_manifest.json
```

The runner materializes `full-file`, `unified-diff`, `structure-edit`, and `intent-patch` candidates, then compiles each result against the same appended evaluation tests. It also checks baseline-test preservation and expected semantic scope. Use `--json` for deterministic machine-readable results and `--measure-time` only when collecting wall-clock data. The [benchmark documentation](benchmarks/intentbench_evolve/README.md) and [Japanese validation report](BENCHMARK_VALIDATION_REPORT_JA.md) explicitly distinguish the handcrafted 4/4 smoke result from a model comparison.

Run the four-checkpoint trajectory suite. Each condition keeps its own evolving source, and every successful checkpoint becomes the base of the next one. Evaluation tests accumulate without being included in model requests.

```sh
python3 -m intentir benchmark \
  benchmarks/intentbench_evolve/trajectory_manifest.json
```

Connect one condition to a provider-specific wrapper through the model-independent JSON stdin/stdout protocol:

```sh
python3 -m intentir benchmark-model \
  benchmarks/intentbench_evolve/model_trajectory_manifest.json \
  --condition intent-patch \
  --adapter-command /path/to/model-wrapper \
  --measure-time \
  --json
```

The model trajectory manifest does not need handcrafted candidate paths. The wrapper receives the instruction, current source, content-addressed Module/Node IDs, and the selected output contract. It returns a candidate plus model and token-usage metadata. The command is supplied only by the operator, runs without a shell, and is never loaded from a benchmark manifest. The included fixture adapter validates this protocol but is not evidence about a real model.

An installable OpenAI Responses API wrapper is included without adding an SDK dependency. Select an explicit model snapshot for reproducible trials; the API key is read only from `OPENAI_API_KEY`.

```sh
export OPENAI_API_KEY='...'
python3 -m intentir benchmark-model \
  benchmarks/intentbench_evolve/model_trajectory_manifest.json \
  --condition intent-patch \
  --adapter-command intentir-openai-adapter \
  --adapter-arg=--model \
  --adapter-arg=gpt-5-2025-08-07 \
  --adapter-arg=--reasoning-effort \
  --adapter-arg=low \
  --measure-time \
  --fail-on-run-failure \
  --json
```

The wrapper uses Structured Outputs, disables response storage, and records the provider response ID, returned and requested model IDs, token usage, prompt/configuration hashes, reasoning effort, and output limit. It never writes the API key into the provider payload or benchmark result. The network call is intentionally not part of the dependency-free test suite; provider parsing and failure behavior are tested offline.

## v0.14 capabilities

- Nine structured Agent Tools with discoverable input and output JSON Schemas
- Module description, exact Node lookup, bounded graph context, and reverse-dependency impact
- Separate Patch validation, human diff rendering, and atomic Patch application
- Selective verification plus in-memory IR, TypeScript, and SQLite builds
- Dependency-free `intentir agent` command for debugging and non-MCP integrations
- Optional official MCP Python SDK adapter pinned to the stable v1 line
- Local stdio transport with project-root path containment
- Source writes disabled by default and enabled only with `--allow-writes`
- MCP Tool annotations distinguishing read-only operations from destructive Patch application
- Stable `ok / result / diagnostics` MCP response Envelope
- Provider-neutral benchmark Model Adapter over JSON stdin/stdout
- Dependency-free OpenAI Responses API wrapper with strict candidate output
- Content-addressed prompt/configuration provenance and failure-code aggregation
- Hash-guarded Patch Envelope with `baseModuleId` and per-target `expectedId`
- Seven closed semantic operations: add, replace, remove, rename, set, insert, and remove member
- Atomic parse, static validation, affected-test verification, and file replacement
- Reverse dependency impact analysis from changed graph nodes
- Deterministic Patch ID and result Module ID
- Stable structured stale/conflict/validation diagnostics
- Dry-run by default, explicit `--apply`, JSON output, and unified human-readable diff
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
- `intentir/patch.py`: guarded semantic patch planning, impact analysis, and atomic apply
- `intentir/agent.py`: bounded model-independent Agent Tool service
- `intentir/mcp_server.py`: optional MCP stdio adapter and Tool schemas
- `intentir/trajectory.py`: cumulative multi-checkpoint benchmark runner
- `intentir/model_adapter.py`: provider-neutral external model protocol
- `intentir/providers/openai_responses.py`: dependency-free OpenAI Responses API wrapper
- `intentir/benchmark.py`: four editing conditions and common evaluation
- `intentir/generators/typescript.py`: TypeScript backend and generated test runner
- `intentir/formatter.py`: canonical source formatter
- `intentir/cli.py`: command-line development workflow
- `intentir/reports.py`: Japanese validation reports

## Verification

```sh
npm test
python3 -m unittest discover -s tests -v
python3 -m compileall -q intentir tests
```

The Ailex suite contains 89 conformance cases. The IntentIR suite contains 91 tests: 90 dependency-free tests and one optional end-to-end MCP stdio test. It covers Tool discovery, structured success/failure results, root-path containment, benchmark path/diff boundaries, four editing adapters, cumulative trajectories, external model provenance and failure classification, the offline-tested OpenAI wrapper, concurrent-agent stale rejection and refresh, Patch validation/application, TypeScript/SQLite builds, and all prior compiler/runtime/storage behavior.

## License

The Ailex implementation is licensed under the [MIT License](LICENSE). The IntentIR Python package and its new supporting files are licensed under the [Apache License 2.0](LICENSE-APACHE).

## Current boundaries

Pure functions currently use one expression body and scalar values; there are no statements, local bindings, collections, pattern matching, or recursive termination proofs. Imports expose every linked symbol through a flat namespace; aliases, private exports, package manifests, registries, and version constraints are not implemented. Relations currently reject cycles and provide restrictive foreign keys only; there are no cardinality declarations, cascades, joins, or relation-aware query expressions. Capability Operations currently accept no arguments and are injected as precomputed scalar values, so HTTP/File calls, async I/O, retries, and secret policies are not implemented. Keyless Entity changes still use full replacement. Patch operations edit definitions in the root source file only, use the currently supported semantic member paths, and canonical formatting may not preserve comments inside changed definitions. The MCP adapter currently supports local stdio only; remote HTTP transport, authentication, Resources, Prompts, and editor-specific installation helpers are not implemented. The OpenAI provider path is implemented and offline-tested, but no paid API trial has been executed or verified in this repository. The current trajectory candidates are handcrafted fixtures. The next practical step is to freeze the selected model snapshot and prompt, expand to the planned 10 applications and 40 checkpoints, and record real-model trials without exposing evaluation tests.
