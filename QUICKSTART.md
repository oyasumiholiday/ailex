# Ailex + IntentIR Quickstart

Use this page for a short local or Container trial. No model API key, database server, or network service is required.

## Clone

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

Install the command in an isolated environment when preferred:

```sh
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/intentir demo concurrent-agent
```

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
