import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const cli = fileURLToPath(new URL("./cli.ts", import.meta.url));
const dir = mkdtempSync(join(tmpdir(), "ailex-cli-regressions-"));
let serial = 0;

function invoke(command: string, source: string) {
  const file = join(dir, `case-${serial++}.ax`);
  writeFileSync(file, source, "utf8");
  const result = spawnSync(process.execPath, [cli, command, file], { encoding: "utf8", timeout: 10_000 });
  assert.equal(result.error, undefined);
  return result;
}

function parseJson(text: string) {
  assert.notEqual(text.trim(), "", "expected a structured JSON diagnostic");
  return JSON.parse(text) as { ok: boolean; errors: any[] };
}

function assertArity(source: string, name: string, signature: string, expected: number, actual: number) {
  const result = invoke("check", source);
  assert.equal(result.status, 1);
  assert.equal(result.stderr, "");
  const diagnostic = parseJson(result.stdout);
  assert.equal(diagnostic.ok, false);
  const error = diagnostic.errors.find((item) => item.code === "arity_mismatch" && item.name === name);
  assert.ok(error, `missing arity_mismatch for ${name}: ${result.stdout}`);
  assert.equal(error.expected, expected);
  assert.equal(error.actual, actual);
  assert.ok(Array.isArray(error.scope));
  assert.ok(error.scope.some((item: any) => item.name === name && item.type === signature));
  assert.ok(error.scope.some((item: any) => item.name === "map" && item.type.includes("Option[T]")));
}

try {
  assertArity(`fn f () -> Int
  eg f() = 0
body Int
  fold()
end f`, "fold", "(List[T], U, (U, T) -> U) -> U", 3, 0);

  assertArity(`fn f () -> Int
  eg f() = 1
body Int
  length([1], 999)
end f`, "length", "(List[T]) -> Int", 1, 2);

  const invalidRun = invoke("run", `fn main () -> Int
  eg main() = 1
body Int
  length([1], 999)
end main`);
  assert.equal(invalidRun.status, 1);
  assert.doesNotMatch(invalidRun.stdout, /main\(\)\s*=/);
  assert.match(invalidRun.stderr, /arity_mismatch/);

  const zeroDivision = invoke("run", `fn main () -> Int
body Int
  1 / 0
end main`);
  assert.equal(zeroDivision.status, 1);
  assert.doesNotMatch(zeroDivision.stdout, /Infinity/);
  const runtimeDiagnostic = parseJson(zeroDivision.stderr);
  assert.equal(runtimeDiagnostic.ok, false);
  assert.ok(runtimeDiagnostic.errors.some((item) => item.code === "runtime"));

  for (const source of [
    `fn main () -> Float
  eg main() = 1.0
body Float
  sqrt(true)
end main`,
    `fn main () -> Int
  eg main() = 1
body Int
  length([1], 999)
end main`,
  ]) {
    const invalidEmit = invoke("emit-js", source);
    assert.equal(invalidEmit.status, 1);
    assert.equal(invalidEmit.stdout, "");
    const diagnostic = parseJson(invalidEmit.stderr);
    assert.equal(diagnostic.ok, false);
    assert.ok(diagnostic.errors.length > 0);
  }

  const valid = `fn main () -> Int
  eg main() = 1
body Int
  length([1])
end main`;
  const validEmit = invoke("emit-js", valid);
  assert.equal(validEmit.status, 0);
  assert.match(validEmit.stdout, /const main = \(\) =>/);
  const validRun = invoke("run", valid);
  assert.equal(validRun.status, 0);
  assert.match(validRun.stdout, /main\(\) = 1/);

  const badCallbacks = invoke("check", `fn keep (v : List[Int]) -> List[Int]
  eg keep([]) = []
body List[Int]
  filter(v, 7)
end keep
fn locate (v : List[Int]) -> Option[Int]
  eg locate([]) = none
body Option[Int]
  find(v, 7)
end locate`);
  assert.equal(badCallbacks.status, 1);
  const callbackDiagnostic = parseJson(badCallbacks.stdout);
  assert.equal(callbackDiagnostic.errors.filter((item) => item.code === "type_mismatch").length, 2);

  console.log("CLI regressions: passed");
} finally {
  rmSync(dir, { recursive: true, force: true });
}
