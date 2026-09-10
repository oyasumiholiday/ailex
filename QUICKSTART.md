# Ailex + IntentIR Quickstart

Use this page for a short local or Container trial. No model API key, database server, or network service is required after installation.

## Install the prerelease wheel

Requires Python 3.11 or newer. This preview uses the tag `intentir-v0.14.0`; install its wheel without a source checkout and run the standalone demonstration:

```sh
DEMO_ENV="$(mktemp -d)"
python3 -m venv "$DEMO_ENV"
"$DEMO_ENV/bin/pip" install --no-deps \
  https://github.com/oyasumiholiday/ailex/releases/download/intentir-v0.14.0/intentir-0.14.0-py3-none-any.whl
"$DEMO_ENV/bin/intentir" demo concurrent-agent
```

This installation step downloads the wheel. The demonstration itself uses a temporary workspace and makes no model API or other network calls.

## Use a source checkout

```sh
git clone https://github.com/oyasumiholiday/ailex.git
cd ailex
```

## Try Ailex

Requires Node.js 23 or newer.

```sh
npm ci --ignore-scripts
node core/cli.ts run examples/points.ax
npm test
```

The final test line should report `89/89 passed`.

## Try IntentIR

Requires Python 3.11 or newer. IntentIR has no mandatory third-party runtime dependency.

```sh
python3 -m intentir check examples/todo_crud.intent
python3 -m intentir test examples/todo_crud.intent
python3 -m intentir demo concurrent-agent
```

The demonstration shows two agents reading the same content-addressed graph. Agent A applies a guarded Patch, Agent B's stale Patch is rejected, and Agent B refreshes before applying a verified replacement.

Install the command from the checkout in an isolated environment when preferred:

```sh
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/intentir demo concurrent-agent
```

## Persistent Todo, Patch, and Migration

This walkthrough copies the application and semantic Patch into a fresh temporary directory. It does not overwrite either checked-in sample or an existing database.

```sh
WORK="$(mktemp -d)"
cp examples/todo_crud.intent "$WORK/todo.intent"
cp examples/add_task_priority.patch.json "$WORK/add_task_priority.patch.json"

python3 -m intentir run "$WORK/todo.intent" CreateTask \
  --input '{"id":"task-1","title":"buy milk"}' --db "$WORK/todo.db"
python3 -m intentir run "$WORK/todo.intent" CompleteTask \
  --input '{"id":"task-1"}' --db "$WORK/todo.db"

python3 -m intentir patch "$WORK/todo.intent" \
  "$WORK/add_task_priority.patch.json" --apply
python3 -m intentir migrate "$WORK/todo.intent" --db "$WORK/todo.db"
python3 -m intentir migrate "$WORK/todo.intent" --db "$WORK/todo.db" --apply

python3 -m intentir run "$WORK/todo.intent" RenameTask \
  --input '{"id":"task-1","title":"buy oat milk"}' --db "$WORK/todo.db"
python3 -m intentir run "$WORK/todo.intent" DeleteTask \
  --input '{"id":"task-1"}' --db "$WORK/todo.db"
```

Every command is a new process. The SQLite database preserves the completed task between them; the migration fills the newly added `priority` field with its default `0`. The rename output therefore contains `done: true`, the new title, and `priority: 0`, and the final delete output contains an empty `Task` list. The first `migrate` only prints the plan; the second applies it.

## Run the Container

Build the pinned Python 3.13 image:

```sh
docker build --pull -t intentir:0.14 .
```

Run the default concurrent-agent demonstration without network access and with a read-only root filesystem:

```sh
docker run --rm \
  --network none \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  intentir:0.14
```

Run another IntentIR command by replacing the default arguments:

```sh
docker run --rm --network none intentir:0.14 \
  test examples/todo_crud.intent
```

## Next Steps

- [Ailex language guide](AILEX_README.md)
- [IntentIR commands and architecture](README.md)
- [Concurrent-agent scenario](demo/concurrent_agent/README.md)
- [IntentBench-Evolve](benchmarks/intentbench_evolve/README.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
