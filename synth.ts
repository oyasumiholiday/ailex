// Ailex — 単調型付け可能性 → constrained decoding の橋
//
// 仕様書 Ailex.md §2 の主張「LLM は型エラーを物理的に出力できない」を、
// 訓練データ・LLM 無しで、言語設計の性質だけを分離して実証する。
//
// 実行: node ailex/synth.ts
//
// 核心: 型検査器から「各生成時点で許容される次トークンの集合」を取り出せる。
//   ・その集合でマスクすれば、型エラーになるトークンは選択肢に存在しない（=出力不能）
//   ・集合は通常ごく小さいので、訓練データ不要の素朴な列挙器ですら穴を解ける
//   ・列挙器を LLM に差し替える＝LLM のロジットを同じマスクで絞る、が実装の次段
//
// これが「AIによるAIのためのPJ」の核: 言語の設計が、モデル非依存に生成を助ける。

import { lex, Parser, showTy, showTerm, tyEq, evalTerm, BUILTINS } from "./prototype.ts";
import type { Ty, Term, Fn, Program, Val, RuntimeObs } from "./prototype.ts";

// ───────────────────────── スコープ（型環境）─────────────────────────

type Scope = { name: string; ty: Ty }[];

// 現在定義中の関数の穴を埋めるためのスコープ。
// 自己参照（norm 本体で norm を呼ぶ自明な罠）を避けるため current は除く。
function scopeFor(prog: Program, current: Fn): Scope {
  const s: Scope = [];
  const add = (name: string, ty: Ty) => { if (name !== current.name && !s.some((x) => x.name === name)) s.push({ name, ty }); };
  for (const p of current.params) add(p.name, p.ty);
  for (const b of BUILTINS) add(b.name, b.ty);
  for (const sig of prog.sigs) add(sig.name, sig.ty);
  for (const f of prog.fns) add(f.name, { k: "fun", params: f.params.map((p) => p.ty), ret: f.ret });
  return s;
}

// ───────────────────────── ① 次トークンの許容集合（decoder マスク）─────────────────────────

// 型 goal の項を「開始できる」トークンの集合。これが生成の第一手のマスク。
// 型検査器の情報だけから計算できる点が肝（§2）。
function admissibleFirstTokens(goal: Ty, scope: Scope): string[] {
  const toks: string[] = [];
  // その型のリテラルクラス
  if (goal.k === "base") toks.push(`<${goal.name} リテラル>`);
  // その型の変数
  for (const { name, ty } of scope) if (ty.k !== "fun" && tyEq(ty, goal)) toks.push(name);
  // 戻り値がその型の関数（適用の頭部）
  for (const { name, ty } of scope) if (ty.k === "fun" && tyEq(ty.ret, goal)) toks.push(`${name}(`);
  return toks;
}

// マスクを掛けない素朴な生成器が「開始できてしまう」トークン全部
function unconstrainedFirstTokens(scope: Scope): string[] {
  const toks = ["<Int リテラル>", "<Float リテラル>", "<Bool リテラル>", "["];
  for (const { name, ty } of scope) toks.push(ty.k === "fun" ? `${name}(` : name);
  return toks;
}

// ───────────────────────── ② 型指向の項合成（＝許容集合の全列挙）─────────────────────────

let nid = 5000;
const id = () => nid++;

function cartesian<T>(lists: T[][]): T[][] {
  return lists.reduce<T[][]>((acc, list) => acc.flatMap((a) => list.map((x) => [...a, x])), [[]]);
}

// 型 goal を持つ項を depth まで全列挙する。
// 各項は「構成上」well-typed —— 型エラーな項はそもそも生成され得ない（§2）。
function enumTerms(goal: Ty, scope: Scope, depth: number): Term[] {
  const out: Term[] = [];
  // 変数
  for (const { name, ty } of scope) if (ty.k !== "fun" && tyEq(ty, goal)) out.push({ k: "var", name, id: id() });
  if (depth > 0) {
    // 適用: 戻り値が goal に一致する関数の、各引数を再帰列挙
    for (const { name, ty } of scope) {
      if (ty.k === "fun" && tyEq(ty.ret, goal)) {
        const perArg = ty.params.map((p) => enumTerms(p, scope, depth - 1));
        for (const args of cartesian(perArg)) out.push({ k: "app", head: name, args, id: id() });
      }
    }
  }
  return out;
}

// ───────────────────────── ③ 実例で正解を選ぶ（型で絞り、例で決める）─────────────────────────

function passesExamples(prog: Program, fn: Fn, body: Term): boolean {
  const candidate: Fn = { ...fn, body };
  const fns = new Map<string, Fn>(prog.fns.map((f) => (f.name === fn.name ? [f.name, candidate] : [f.name, f])));
  const obs: RuntimeObs[] = [];
  for (const eg of fn.egs) {
    let got: Val, want: Val;
    try { got = evalTerm(eg.call, new Map(), obs, fns); want = evalTerm(eg.expect, new Map(), obs, fns); }
    catch { return false; }
    if (got !== want) return false;
    if (fn.ensures) { const ens = evalTerm(fn.ensures, new Map<string, Val>([["ret", got]]), obs, fns); if (ens !== true) return false; }
  }
  return obs.length === 0; // 実行時観測（NaN 等）が出たら不合格
}

// ───────────────────────── 実演 ─────────────────────────

function main() {
  const source = `
group vec
  sig dot  : (Vec Float, Vec Float) -> Float
  sig sqrt : (Float) -> Float
  sig norm : (Vec Float) -> Float
end group

fn norm (v : Vec Float) -> Float
  ensures ret >= 0.0
  eg norm([3.0, 4.0]) = 5.0
body Float
  ?h1
end norm
`;
  const prog = new Parser(lex(source)).parseProgram();
  const fn = prog.fns[0];
  const scope = scopeFor(prog, fn);
  const goal: Ty = fn.bodyTy; // Float

  console.log("════════════════════════════════════════════════════════════");
  console.log(" Ailex: 単調型付け可能性 → constrained decoding の実証");
  console.log(" 穴 ?h1 : Float を、訓練データ・LLM 無しで埋める");
  console.log("════════════════════════════════════════════════════════════\n");

  // ── A. decoder マスク ──
  const unc = unconstrainedFirstTokens(scope);
  const con = admissibleFirstTokens(goal, scope);
  console.log("Ⓐ 生成の第一手：次トークンの許容集合（型検査器が計算）\n");
  console.log(`   マスク無し（素朴な生成器が開始できる）: ${unc.length} 通り`);
  console.log(`      ${unc.join("  ")}`);
  console.log(`\n   マスク有り（Float の項を開始できるトークンだけ）: ${con.length} 通り`);
  console.log(`      ${con.join("  ")}`);
  const blocked = unc.filter((t) => !con.includes(t));
  console.log(`\n   → マスクが除外したトークン: ${blocked.join("  ")}`);
  console.log(`   → 特に 'v'（Vec Float）は Float の穴では選択肢に存在しない。`);
  console.log(`      constrained decoding 下では、前回③の型エラー ?h1:=v は物理的に出力不能。`);
  console.log(`      型エラーは「検出されるもの」でなく「表現不可能なもの」になる（§2）。`);

  // ── B. 型指向合成 ──
  const candidates = enumTerms(goal, scope, 2);
  console.log(`\nⒷ 型 Float の項を深さ2まで全列挙（＝許容集合の全体）: ${candidates.length} 個`);
  for (const c of candidates) console.log(`      ${showTerm(c)}`);
  console.log(`   全て構成上 well-typed。型エラーな候補は集合に存在しない。`);
  console.log(`   （比較）型無しに同じトークンを並べる空間は指数的に広く、大半が型エラー。`);
  console.log(`   型が探索空間を ${candidates.length} 個へ圧縮した——ここが「AIが解きやすい」の実体。`);

  // ── C. 実例で決定 ──
  console.log(`\nⒸ 実例 eg norm([3,4])=5 と ensures ret>=0 で候補を篩う\n`);
  const solutions: Term[] = [];
  for (const c of candidates) {
    const ok = passesExamples(prog, fn, c);
    console.log(`      ${ok ? "✓" : "✗"} ${showTerm(c)}`);
    if (ok) solutions.push(c);
  }
  console.log(`\n   → 機械が自力で選んだ穴埋め: ${solutions.map(showTerm).join(" , ") || "（なし）"}`);

  console.log("\n────────────────────────────────────────────────────────────");
  if (solutions.length === 1 && showTerm(solutions[0]) === "sqrt(dot(v, v))") {
    console.log(" ✅ 訓練データ・LLM 無しの素朴な列挙器が、穴を一意に解いた。");
  } else {
    console.log(" 結果: " + solutions.map(showTerm).join(" , "));
  }
  console.log("    型が空間を数個に絞り（Ⓑ）、実例が正解を選ぶ（Ⓒ）。");
  console.log("    列挙器を LLM に差し替える＝LLM のロジットを Ⓐ のマスクで絞る。");
  console.log("    そのとき LLM は不慣れでも型エラーを出せず、訓練不足を推論時制約が補う（§7反論①）。");
  console.log("────────────────────────────────────────────────────────────");
}

// 直接実行時のみデモを走らせる（claude.ts から import しても副作用を出さない）
if (process.argv[1] && process.argv[1].endsWith("synth.ts")) main();

export { scopeFor, enumTerms };
export type { Scope };
