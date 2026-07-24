# IntentBench-Evolve

This directory contains the model-independent benchmark harness and its first smoke suite.

```sh
python3 -m intentir benchmark \
  benchmarks/intentbench_evolve/smoke_manifest.json

python3 -m intentir benchmark \
  benchmarks/intentbench_evolve/smoke_manifest.json \
  --json

python3 -m intentir benchmark \
  benchmarks/intentbench_evolve/trajectory_manifest.json
```

The smoke suite applies the same requirement through four editing interfaces:

- `full-file`: a complete replacement source file
- `unified-diff`: a Git-compatible patch restricted to `workspace.intent`
- `structure-edit`: semantic operations whose current IDs are resolved by the runner
- `intent-patch`: semantic operations carrying agent-supplied Module and Node IDs

Every resulting program is compiled and checked against the same appended evaluation tests. The runner also rejects candidates that remove baseline tests or modify symbols outside `expectedChangedSymbols`.

The included candidates are handcrafted to validate the harness. Their 4/4 result is **not** an empirical comparison and must not be reported as evidence that any condition is superior. Model-generated candidates, fixed prompts, repeated trials, and held-out tasks are required before making performance claims.

Wall-clock measurements are excluded by default so JSON output remains deterministic. Add `--measure-time` when collecting timed runs. The unified-diff condition requires `git`; all referenced paths are constrained to the manifest directory, and diffs may modify only `workspace.intent`.

Machine-readable contracts are available for the independent [manifest](schema/manifest.schema.json) and [result](schema/result.schema.json), [structure edit](schema/structure_edit.schema.json), trajectory [manifest](schema/trajectory_manifest.schema.json) and [result](schema/trajectory_result.schema.json), and model [request](schema/model_request.schema.json) and [response](schema/model_response.schema.json). Runtime validation additionally enforces that candidate keys match the selected conditions and that resolved files remain inside the suite directory.

The paid pilot configuration has its own machine-readable [protocol schema](schema/pilot_protocol.schema.json). The checked-in protocol uses a date-pinned model snapshot and records the pricing observation date instead of silently following a moving alias.

The trajectory suite carries each condition's successful source into the next checkpoint and accumulates all prior evaluation tests. It currently contains one handcrafted application with four checkpoints, producing 16 fixture runs.

## External model adapter

`benchmark-model` connects one editing condition to an explicit external command:

```sh
python3 -m intentir benchmark-model \
  benchmarks/intentbench_evolve/model_trajectory_manifest.json \
  --condition intent-patch \
  --adapter-command /path/to/model-wrapper \
  --json
```

The wrapper receives one [model request](schema/model_request.schema.json) as JSON on stdin and must emit one [model response](schema/model_response.schema.json) on stdout. Requests include the current source, instruction, Module/Node IDs, a minimal versioned IntentIR syntax reference, and a condition-specific output contract. Output contracts separate interface metadata from the exact candidate shape, list legal JSON fields, and define target-reference semantics. They never include evaluation-test text. Responses echo the content-addressed `requestId`, identify the model, return the candidate as a string, and report provider token usage when available.

Candidate paths are optional in a trajectory manifest used with `benchmark-model`; they remain mandatory for fixture execution through `benchmark`. The included `model_trajectory_manifest.json` is therefore ready for a provider wrapper without carrying handcrafted answers.

With `--measure-time`, checkpoint latency starts before the wrapper process and ends after candidate evaluation. Without it, timing fields are omitted so fixture results remain reproducible byte for byte.

The command is supplied only on the CLI and is never read from an untrusted manifest. It is executed without a shell, with a timeout and bounded response/candidate sizes. API credentials should be provided through the wrapper's environment or secret store, never through command arguments or result JSON.

## OpenAI Responses API wrapper

The installed `intentir-openai-adapter` command is a dependency-free reference provider wrapper. It requires an explicit model ID and reads authentication only from `OPENAI_API_KEY`:

```sh
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

It asks the Responses API for a strict `{candidate: string}` Structured Output with `store: false`. The ordinary benchmark result records the candidate hash, usage, response/model identifiers, and content-addressed prompt/configuration provenance. Provider bodies, credentials, and evaluation tests are not copied into diagnostics. Current automated coverage uses fake provider responses and does not spend API credits.

## Budget-guarded pilot

The default `pilot` command is a network-free preflight. Use the original protocol to reproduce the first pilot, or the separately identified v2 protocol for the post-pilot contract calibration:

```sh
python3 -m intentir pilot \
  benchmarks/intentbench_evolve/openai_pilot_protocol.json \
  --json

python3 -m intentir pilot \
  benchmarks/intentbench_evolve/openai_calibration_v2_protocol.json \
  --json

python3 -m intentir pilot \
  benchmarks/intentbench_evolve/openai_calibration_v3_protocol.json \
  --json
```

Paid execution additionally requires `--execute`, an exact `--confirm-budget-usd` match, `OPENAI_API_KEY`, and a new output directory. It archives the normalized protocol, every secret-free request/payload/response, candidates, token usage, accounted cost, trial result, and summary. No retry is performed after a provider or candidate failure. See [the Japanese pilot protocol](../../PILOT_EXPERIMENT_PROTOCOL_JA.md) before authorizing a paid run.

Failed runs include a stable `failure.stage` plus diagnostic codes, and summaries aggregate them under `failuresByCode`. The current stages distinguish generation, stale preconditions, semantic scope, verification, and other candidate failures.

The v3 paid calibration used 11 provider calls, accounted for 0.040957 USD, and accepted 9 of 11 reached checkpoints. Both `full-file` and `intent-patch` completed all four checkpoints. This is a single-task calibration result, not a statistical comparison. See the [Japanese v3 result](../../OPENAI_CALIBRATION_V3_RESULT_2026-07-24_JA.md).
