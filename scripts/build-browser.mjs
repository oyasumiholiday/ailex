import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const root = fileURLToPath(new URL("../", import.meta.url));
const entryPoint = fileURLToPath(new URL("../core/browser-entry.ts", import.meta.url));
const outfile = fileURLToPath(new URL("../docs/ailex.js", import.meta.url));
const args = process.argv.slice(2);

if (args.length > 1 || (args.length === 1 && args[0] !== "--check")) {
  console.error("usage: node scripts/build-browser.mjs [--check]");
  process.exit(2);
}

const result = await build({
  absWorkingDir: root,
  bundle: true,
  charset: "ascii",
  entryPoints: [entryPoint],
  format: "esm",
  legalComments: "none",
  outfile,
  platform: "browser",
  sourcemap: false,
  target: "es2022",
  write: false,
});
const generated = result.outputFiles[0].contents;

if (args[0] === "--check") {
  let current;
  try {
    current = await readFile(outfile);
  } catch (error) {
    if (error?.code === "ENOENT") {
      console.error("docs/ailex.js is missing; run npm run build:browser");
      process.exit(1);
    }
    throw error;
  }
  if (!current.equals(generated)) {
    console.error("docs/ailex.js is stale; run npm run build:browser");
    process.exit(1);
  }
  console.log("docs/ailex.js is up to date");
} else {
  await writeFile(outfile, generated);
  console.log("wrote docs/ailex.js");
}
