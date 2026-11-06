# Legacy Ailex Index

The active project is [IntentIR](../README.md); current priorities are in [GOALS_JA.md](../GOALS_JA.md). The earlier Ailex implementation and artifacts remain in place for historical reference and compatibility. No Ailex-to-IntentIR lowering or merged implementation is claimed or required.

## Preserved References

| Location | Purpose |
|---|---|
| [AILEX_README.md](../AILEX_README.md) | Earlier English Ailex introduction |
| [AILEX_README.ja.md](../AILEX_README.ja.md) | Byte-for-byte copy of the public root Japanese README before this cleanup |
| [PRIMER.en.md](../PRIMER.en.md), [PRIMER.md](../PRIMER.md) | English and Japanese Ailex syntax and standard library |
| [SPEC.md](../SPEC.md), [CHANGELOG.md](../CHANGELOG.md) | Ailex specification and history |
| [core/README.md](../core/README.md), [core/](../core/) | TypeScript implementation and compatibility tests |
| [examples/](../examples/) (`*.ax`) | Ailex programs, separate from IntentIR `.intent` |
| [agent/](../agent/) | Earlier Ailex agent material |
| [DOGFOOD.md](../DOGFOOD.md), [EXPERIMENTS.md](../EXPERIMENTS.md) | Historical experiments, including negative results |
| [AILEX_ANALYSIS_JA.md](../AILEX_ANALYSIS_JA.md) | Earlier design and integration discussion, not implemented integration |
| [AILEX_AGENT_INSTRUCTIONS_ARCHIVE.md](AILEX_AGENT_INSTRUCTIONS_ARCHIVE.md) | Exact previous public root agent instructions |

The Japanese README snapshot retains its original wording, links, and historical counts. Those counts are not current verification requirements. The archived agent instructions retain repository-root-relative links; interpret them from the original root, not from `docs/`. Earlier descriptions of a combined project do not override the current IntentIR scope. Historical research plans, results, and approvals do not authorize new paid trials.

## Compatibility Commands

These commands are only for the retained Ailex prototype, not IntentIR installation. Ailex requires Node.js 23 or newer; Node.js 24 matches current CI. From the repository root:

```sh
npm ci --ignore-scripts
node core/cli.ts run examples/points.ax
npm test
```

The CLI also supports checking, scope inspection, formatting, and JavaScript output:

```sh
node core/cli.ts check examples/points.ax
node core/cli.ts scope examples/points.ax dist
node core/cli.ts fmt examples/points.ax
node core/cli.ts emit-js examples/points.ax
```

Use the preserved primer for Ailex syntax. Do not apply it to IntentIR. Report actual results rather than fixed historical test counts.

## Browser Bundle

After changing exported legacy parser, checker, interpreter, or JavaScript-backend behavior, use the lockfile-pinned toolchain installed above:

```sh
npm run build:browser
npm run check:browser
```

Do not edit `docs/ailex.js` by hand. The build command is the regeneration path; the check command verifies byte-for-byte freshness without writing the bundle. These commands maintain the Ailex browser prototype, not IntentIR.

## Licensing

The retained Ailex implementation remains [MIT-licensed](../LICENSE). The IntentIR Python package and its new supporting files remain [Apache-2.0-licensed](../LICENSE-APACHE). This documentation cleanup does not relicense existing artifacts or change the historical repository name.
