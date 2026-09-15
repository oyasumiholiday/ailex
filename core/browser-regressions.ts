import assert from "node:assert/strict";

const ailex = await import(new URL("../docs/ailex.js", import.meta.url).href);
const expectedExports = [
  "check",
  "evalInProgram",
  "parseProgram",
  "runContracts",
  "runJs",
  "showExpr",
  "showProgram",
  "toJs",
  "valEq",
];

assert.deepEqual(Object.keys(ailex).sort(), expectedExports.sort());

function checked(source: string) {
  const program = ailex.parseProgram(source);
  const result = ailex.check(program);
  assert.equal(result.ok, true, JSON.stringify(result.errors));
  return program;
}

function expectDiagnostic(source: string, code: string, name: string) {
  const result = ailex.check(ailex.parseProgram(source));
  assert.equal(result.ok, false);
  const error = result.errors.find((item: any) => item.code === code && item.name === name);
  assert.ok(error, JSON.stringify(result.errors));
  return error;
}

const lengthArity = expectDiagnostic(`fn f () -> Int
body Int
  length([1], 999)
end f`, "arity_mismatch", "length");
assert.equal(lengthArity.expected, 1);
assert.equal(lengthArity.actual, 2);
assert.ok(lengthArity.scope.some((item: any) => item.name === "map" && item.type.includes("Option[T]")));

const foldArity = expectDiagnostic(`fn f () -> Int
body Int
  fold()
end f`, "arity_mismatch", "fold");
assert.equal(foldArity.expected, 3);
assert.equal(foldArity.actual, 0);

const guards = checked(`fn andGuard (v : List[Int]) -> Bool
  eg andGuard([]) = false
body Bool
  length(v) > 0 && head(v) > 0
end andGuard
fn orGuard (v : List[Int]) -> Bool
  eg orGuard([]) = true
body Bool
  length(v) == 0 || head(v) > 0
end orGuard`);
assert.equal(ailex.evalInProgram(guards, "andGuard([])"), false);
assert.equal(ailex.runJs(guards, "andGuard([])"), false);
assert.equal(ailex.evalInProgram(guards, "orGuard([])"), true);
assert.equal(ailex.runJs(guards, "orGuard([])"), true);

for (const [type, expression] of [["Int", "1 / 0"], ["Float", "0.0 / 0.0"]]) {
  const division = checked(`fn divide () -> ${type}
body ${type}
  ${expression}
end divide`);
  assert.throws(() => ailex.evalInProgram(division, "divide()"), /0 除算/);
  assert.throws(() => ailex.runJs(division, "divide()"), /0 除算/);
}

const sample = checked(`fn three () -> Int
  ensures ret == 3
  eg three() = 3
body Int
  3
end three`);
assert.deepEqual(ailex.runContracts(sample), []);
assert.equal(ailex.evalInProgram(sample, "three()"), 3);
assert.equal(ailex.runJs(sample, "three()"), 3);

console.log("Browser bundle regressions: passed");
