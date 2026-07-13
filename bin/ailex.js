#!/usr/bin/env node
// ailex CLI エントリポイント（npm bin 用・クロスプラットフォーム）
// Node >=23（型ストリップで .ts を直接実行）。
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const cli = join(here, "..", "core", "cli.ts");
const r = spawnSync(process.execPath, [cli, ...process.argv.slice(2)], { stdio: "inherit" });
process.exit(r.status ?? 1);
