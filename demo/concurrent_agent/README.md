# Concurrent Agent Demo

This self-contained scenario demonstrates optimistic concurrency for AI-generated semantic edits.

```sh
python3 -m intentir demo concurrent-agent
```

For machine-readable evidence:

```sh
python3 -m intentir demo concurrent-agent --json
```

Two simulated agents read the same content-addressed `WorkItem` node. Agent A adds `priority` and commits first. Agent B's original Patch is then rejected with `stale_base_module`. Agent B refreshes the Module and Node IDs, rebuilds the same semantic intent, runs the required verification obligations, and commits successfully.

The command uses a temporary workspace and does not modify [workspace.intent](workspace.intent). A successful run ends with `RESULT: PASS` and reports the generated TypeScript and SQLite artifact IDs in JSON mode.
