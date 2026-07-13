// Ailex v0.1 — CLI（SPEC §10）
// 使い方: node ailex/core/cli.ts <cmd> <file.ax> [arg]
//   check <file>          型＋契約検査 → 構造化診断(JSON)。0=ok / 1=診断あり
//   run   <file>          検査して JS へ落として実行（eg を検査し、main() があれば評価して表示）
//   fmt   <file>          L1 正規形へ整形して表示
//   scope <file> [fn]     そのスコープで使える名前と型を機械可読(JSON)で（fn 指定でその関数内）
//   emit-js <file>        生成される JavaScript を表示

import { readFileSync } from "node:fs";
import { parseProgram, check, runContracts, showTy, showProgram, showExpr, evalInProgram, valEq, STDLIB, POLY_SIGS, ParseErr } from "./lang.ts";
import type { Program } from "./lang.ts";
import { toJs, runJs } from "./tojs.ts";

function read(file: string): string {
  try { return readFileSync(file, "utf8"); }
  catch { console.error(`ファイルを読めません: ${file}`); process.exit(2); }
}
function parseOrDie(src: string): Program | { diag: any } {
  try { return parseProgram(src); }
  catch (e: any) { return { diag: { ok: false, errors: [{ code: "parse", detail: e.message }] } }; }
}
function scopeList(prog: Program, fnName?: string): { name: string; type: string }[] {
  const out: { name: string; type: string }[] = [];
  const f = fnName ? prog.fns.find((x) => x.name === fnName) : undefined;
  if (f) for (const p of f.params) out.push({ name: p.name, type: showTy(p.ty) });
  for (const [n, sig] of Object.entries(POLY_SIGS)) out.push({ name: n, type: sig });
  for (const [n, b] of Object.entries(STDLIB)) out.push({ name: n, type: showTy(b.ty) });
  for (const uf of prog.fns) out.push({ name: uf.name, type: showTy({ k: "Fun", params: uf.params.map((p) => p.ty), ret: uf.ret }) });
  return out;
}

const [cmd, file, arg] = process.argv.slice(2);
if (!cmd || !file) {
  console.error("使い方: ailex <check|run|fmt|scope|emit-js> <file.ax> [arg]");
  process.exit(2);
}
const src = read(file);
const parsed = parseOrDie(src);
if ("diag" in parsed) {
  if (cmd === "check") { console.log(JSON.stringify(parsed.diag, null, 2)); process.exit(1); }
  console.error(`構文エラー: ${parsed.diag.errors[0].detail}`); process.exit(1);
}
const prog = parsed;

switch (cmd) {
  case "check": {
    const r = check(prog);
    const errors = [...r.errors, ...(r.ok ? runContracts(prog) : [])];
    console.log(JSON.stringify({ ok: errors.length === 0, errors }, null, 2));
    process.exit(errors.length === 0 ? 0 : 1);
  }
  case "scope": {
    console.log(JSON.stringify(scopeList(prog, arg), null, 2));
    break;
  }
  case "fmt": {
    console.log(showProgram(prog));
    break;
  }
  case "emit-js": {
    check(prog); // bin.nt を刻む（/ の意味論）
    console.log(toJs(prog));
    break;
  }
  case "run": {
    const r = check(prog);
    if (!r.ok) { console.error("型検査に失敗:"); console.error(JSON.stringify(r.errors, null, 2)); process.exit(1); }
    // eg 契約 — インタプリタと JS バックエンドの両方で検査する。
    // 契約はユーザのプログラム自身による変換器の検証を兼ねる（両者の不一致＝変換バグを即検出）。
    const viol = runContracts(prog);
    const egCount = prog.fns.reduce((n, f) => n + f.contracts.filter((c) => c.kind === "eg").length, 0);
    if (viol.length) { console.error(`契約違反 ${viol.length} 件:`); console.error(JSON.stringify(viol, null, 2)); process.exit(1); }
    const jsViol: any[] = [];
    for (const f of prog.fns) for (const c of f.contracts) {
      if (c.kind !== "eg") continue;
      try {
        const got = runJs(prog, showExpr(c.call!));
        const want = evalInProgram(prog, showExpr(c.value!));
        if (!valEq(got, want)) jsViol.push({ code: "backend_mismatch", call: showExpr(c.call!), interp: "(合格)", js: JSON.stringify(got), expected: JSON.stringify(want) });
      } catch (e: any) { jsViol.push({ code: "backend_mismatch", call: showExpr(c.call!), js: `error: ${e.message}` }); }
    }
    if (jsViol.length) {
      console.error(`バックエンド不一致 ${jsViol.length} 件（インタプリタは合格・JS 変換側で失敗＝変換器のバグの可能性。報告してください）:`);
      console.error(JSON.stringify(jsViol, null, 2)); process.exit(1);
    }
    if (egCount) console.log(`eg 実例 ${egCount} 件: すべて達成 ✅（インタプリタ・JS 両系で検証）`);
    // main があれば実行（実行時エラーは構造化診断で返す。スタックトレースで死なない）
    const main = prog.fns.find((f) => f.name === "main" && f.params.length === 0);
    if (main) {
      try { console.log("main() =", runJs(prog, "main()")); }
      catch (e: any) {
        console.error(JSON.stringify({ ok: false, errors: [{ code: "runtime", at: "main()", detail: e.message }] }, null, 2));
        process.exit(1);
      }
    }
    else if (!egCount) console.log(`検査 OK（関数 ${prog.fns.length} 個。main も eg も無いので実行対象なし）`);
    break;
  }
  default:
    console.error(`未知のコマンド: ${cmd}`); process.exit(2);
}
