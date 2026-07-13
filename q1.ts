// Ailex — 実験 Q1: 構造化フィードバック vs 自然言語フィードバック
//
// 問い: 検証器の応答を「機械可読な構造化データ（期待型・スコープ候補・未達の例）」として
//       修復ループに還流すると、自然言語フィードバックに比べて修復ラウンドが減り pass@k が上がるか？
//
// 背景（PRIOR_ART.md）: Self-Repair(ICLR 2024, arXiv:2306.09896) は「自己修復のボトルネックは
//   フィードバックの質」を実証したが、そのフィードバックは自然言語。構造化フィードバックを還流した
//   例は見当たらない＝これが Ailex の最有力の新規性候補。
//
// 設計: Ailex の本体式を全項生成（マスク無し・文法をプロンプトで教える）。同一モデル・同一タスクで
//   フィードバックの「形式と内容」だけを2条件で振る（他は完全に同一）。
//   - nl:         コンパイラ/リンタ風の散文（期待/実際、失敗例。スコープ列挙はしない）
//   - structured: 機械可読 JSON（期待型・スコープ候補[名前:型]・失敗例。Hazel流の中身を構造で）
//   採点は隠しテスト（見せない）。修復フィードバックは公開例のみ（テストリーク無し）。
//   型エラー数は指標にしない（Ailex側で循環論法）——測るのは機能的正解率とラウンド数。
//
// 実行: node ailex/q1.ts   （ailex/.env or ANTHROPIC_API_KEY と SDK が必要。無ければスタンドイン）
//   環境変数: MODEL（既定 claude-opus-4-8）, ROUNDS（既定4）, REPEATS（既定1）, ARMS（既定 "nl,structured"）

import "./env.ts";
import { checkFn, showTy } from "./prototype.ts";
import type { Program, Fn, Ty } from "./prototype.ts";
import { scopeFor } from "./synth.ts";
import type { Scope } from "./synth.ts";
import { TASKS, buildAilex, ailexExamples, ailexFirstFail, ailexRun, parseProg } from "./tasks.ts";
import type { Task } from "./tasks.ts";
import { writeFileSync, mkdirSync } from "node:fs";

const MODEL = process.env.MODEL || "claude-opus-4-8";
// TEACH=full: 文法＋スコープ＋例を全部教える（易しすぎて修復が起きない）
// TEACH=min : 文法の構文だけ教え、使える関数（スコープ）は伏せる。モデルは名前/型を当てて外し、
//             検証結果から回復する必要がある。構造化フィードバックはスコープ[名前:型]を明かす＝
//             これが差になるはず（Q1 を測れる regime）。
const TEACH = process.env.TEACH || "min";
const ROUNDS = Number(process.env.ROUNDS || 4);
const REPEATS = Number(process.env.REPEATS || 1);
const ARMS = (process.env.ARMS || "nl,nl_rich,structured").split(",").map((s) => s.trim());
const PRICING: Record<string, [number, number]> = {
  "claude-opus-4-8": [5, 25], "claude-opus-4-7": [5, 25], "claude-sonnet-5": [3, 15], "claude-haiku-4-5": [1, 5], "claude-fable-5": [10, 50],
};
interface Usage { inTok: number; outTok: number }
const costOf = (m: string, u: Usage) => { const [i, o] = PRICING[m] || [5, 25]; return u.inTok / 1e6 * i + u.outTok / 1e6 * o; };

// ───────────────────────── 候補の評価とフィードバック ─────────────────────────

type Feedback =
  | { kind: "parse"; detail: string }
  | { kind: "type"; expected: string; actual: string; msg: string }
  | { kind: "hole"; n: number; expected: string }
  | { kind: "example"; call: string; expected: number; actual: string }
  | { kind: "ok" };

// term(本体式の文字列) を評価して {feedback, prog, fn} を返す。
function evaluate(task: Task, term: string): { fb: Feedback; prog?: Program; fn?: Fn } {
  let prog: Program;
  try { prog = parseProg(buildAilex(task, term)); }
  catch (e: any) { return { fb: { kind: "parse", detail: e.message } }; }
  const fn = prog.fns[0];
  const ck = checkFn(prog, fn);
  if (ck.errors.length > 0) {
    const e = ck.errors[0];
    return { fb: { kind: "type", expected: showTy(e.expected), actual: showTy(e.actual), msg: e.msg }, prog, fn };
  }
  if (ck.holes.length > 0) {
    return { fb: { kind: "hole", n: ck.holes.length, expected: showTy(ck.holes[0].expected) }, prog, fn };
  }
  const fail = ailexFirstFail(prog, fn, task.publicT);
  if (fail) {
    const call = `${task.fname}(${fail.input.map((v) => Array.isArray(v) ? `[${v.join(", ")}]` : String(v)).join(", ")})`;
    return { fb: { kind: "example", call, expected: fail.expected, actual: fail.actual }, prog, fn };
  }
  return { fb: { kind: "ok" }, prog, fn };
}

// 自然言語フィードバック（コンパイラ/リンタ風の散文。スコープ列挙はしない）
function renderNL(fb: Feedback): string {
  switch (fb.kind) {
    case "parse": return `構文エラー: ${fb.detail}`;
    case "type": return `型が合いません（${fb.msg}）。ある部分式は ${fb.actual} 型ですが、そこは ${fb.expected} 型が必要です。`;
    case "hole": return `式が未完成です（穴 ? が ${fb.n} 個残っています。${fb.expected} 型の式で埋めてください）。`;
    case "example": return `テストに失敗しました。${fb.call} は ${fb.expected} を返すべきですが ${fb.actual} を返しました。`;
    case "ok": return "";
  }
}

// NL-rich: structured と「同じ内容」を散文で（スコープ候補も散文で列挙）。
// nl→nl_rich の差＝内容効果、nl_rich→structured の差＝形式効果、を切り分けるための群。
function renderNLRich(fb: Feedback, scope: Scope): string {
  const scopeProse = scope.map((s) => `${s.name}（型 ${showTy(s.ty)}）`).join("、");
  switch (fb.kind) {
    case "parse": return `構文エラー: ${fb.detail}`;
    case "type": return `型が合いません（${fb.msg}）。ある部分式は ${fb.actual} 型ですが、そこは ${fb.expected} 型が必要です。使える組み込みは次のものだけです: ${scopeProse}。この中から選んでください。`;
    case "hole": return `式が未完成です（穴 ? が ${fb.n} 個。${fb.expected} 型の式で埋めてください）。使える組み込みは次のものだけです: ${scopeProse}。`;
    case "example": return `テストに失敗しました。${fb.call} は ${fb.expected} を返すべきですが ${fb.actual} を返しました。`;
    case "ok": return "";
  }
}

// 構造化フィードバック（機械可読 JSON。期待型＋スコープ候補[名前:型]を含む＝Hazel流の中身を構造で）
function renderStructured(fb: Feedback, scope: Scope): string {
  const scopeJson = scope.map((s) => ({ name: s.name, type: showTy(s.ty) }));
  switch (fb.kind) {
    case "parse": return JSON.stringify({ error: "parse_error", detail: fb.detail });
    case "type": return JSON.stringify({ error: "type_mismatch", expected: fb.expected, actual: fb.actual, message: fb.msg, scope: scopeJson });
    case "hole": return JSON.stringify({ error: "incomplete", holes: fb.n, expected_type: fb.expected, scope: scopeJson });
    case "example": return JSON.stringify({ error: "example_failed", call: fb.call, expected: fb.expected, actual: fb.actual });
    case "ok": return "";
  }
}

const render = (fb: Feedback, mode: string, scope: Scope) =>
  mode === "structured" ? renderStructured(fb, scope)
  : mode === "nl_rich" ? renderNLRich(fb, scope)
  : renderNL(fb);

// ───────────────────────── 生成器（モデル or スタンドイン）─────────────────────────

type Gen = (prompt: string, task: Task) => Promise<string>;

function stripWrap(s: string): string {
  s = s.trim().replace(/^```[a-zA-Z]*\s*\n?/, "").replace(/\n?```$/, "").trim();
  return s;
}

function opusGen(client: any, usage: Usage, model: string): Gen {
  return async (prompt) => {
    const tool = { name: "submit_term", description: "Ailex の本体式を1つ提出する。", strict: true,
      input_schema: { type: "object", properties: { term: { type: "string" } }, required: ["term"], additionalProperties: false } };
    const res = await client.messages.create({
      model, max_tokens: 1024, thinking: { type: "disabled" },
      tools: [tool], tool_choice: { type: "tool", name: "submit_term" },
      messages: [{ role: "user", content: prompt }],
    });
    usage.inTok += res.usage?.input_tokens ?? 0; usage.outTok += res.usage?.output_tokens ?? 0;
    const call = res.content.find((b: any) => b.type === "tool_use");
    return stripWrap(call?.input?.term ?? "");
  };
}

// スタンドイン: 1手目はわざと誤答（種類を散らす）、2手目以降は正解。フィードバックには依存しない
// （＝配管検証専用。両 arm で同結果。実験の対比は実モデルでのみ現れる）。
const STANDIN: Record<string, { wrong: string; right: string }> = {
  sq: { wrong: "x", right: "mul(x, x)" },
  normsq: { wrong: "v", right: "dot(v, v)" },                 // 型エラー
  cube: { wrong: "mul(x, x)", right: "mul(x, mul(x, x))" },
  norm: { wrong: "dot(v, v)", right: "sqrt(dot(v, v))" },
  hypot: { wrong: "sqrt(add(mul(a, a), mul(b, b))", right: "sqrt(add(mul(a, a), mul(b, b)))" }, // 構文エラー
  max: { wrong: "a", right: "if(a >= b, a, b)" },
  min: { wrong: "b", right: "if(a >= b, b, a)" },
  relu: { wrong: "x", right: "if(x >= 0.0, x, 0.0)" },
  abs: { wrong: "x", right: "if(x >= 0.0, x, mul(-1.0, x))" },
  sign: { wrong: "?h", right: "if(x >= 0.0, 1.0, -1.0)" },    // 穴が残る
};
const standinGen: Gen = async (prompt, task) =>
  prompt.includes("前回の提出") ? STANDIN[task.name].right : STANDIN[task.name].wrong;

// ───────────────────────── 1本の修復ループ（1 arm × 1 タスク）─────────────────────────

const GRAMMAR = [
  "Ailex という小さな型付き言語で、関数の本体式を1つ書いてください（def や return は不要。式だけ）。",
  "文法:",
  "  関数適用: f(a, b)",
  "  条件分岐: if(cond, then, els)   ← cond は Bool 型",
  "  比較:     a >= b               ← 結果は Bool",
  "  数値リテラル: 0.0, 1.0, -1.0 など",
  "  変数: 引数名をそのまま書く",
  "参考例（別の関数の本体）: ベクトルのノルムなら  sqrt(dot(v, v))",
  "参考例（別の関数の本体）: 大きい方を返すなら    if(a >= b, a, b)",
].join("\n");

// TEACH=min 用: 構文は完全に教えるが、使える関数の名前/型（スコープ）は伏せる。
// 失敗が構文層でなく「関数名/型の当て違い」層で起きるようにする＝構造化フィードバック(スコープ開示)が効く regime。
const GRAMMAR_MIN = [
  "Ailex という式ベースの小さな型付き言語で、関数の本体式を1つ書いてください（def/return 不要・式だけ）。",
  "構文の規則（重要・これ以外の書き方は構文エラー）:",
  "  ・すべての算術は関数呼び出し f(a, b) の形で書く。中置演算子は無い（a * b, a + b, a - b は書けない）。",
  "  ・条件分岐: if(cond, then, els)。比較だけは中置で a >= b（結果は Bool）。",
  "  ・数値リテラル: 0.0, 1.0, -1.0 など。変数は引数名をそのまま。",
  "  ・ラムダ・無名関数・map/fold・リスト内包表記は存在しない。",
  "組み込み関数の名前と型は限られています（自分で新しい関数は定義できない）。",
  "正しい関数名が分からなければ、それらしい名前で呼んでみて、検証結果を見て直してください。",
].join("\n");

interface ArmResult { pass1: boolean; passK: boolean; rounds: number; kinds: string[]; term: string }

async function runArm(task: Task, gen: Gen, mode: string): Promise<ArmResult> {
  const prog0 = parseProg(buildAilex(task, "?h1"));
  const scope = scopeFor(prog0, prog0.fns[0]);
  const scopeList = scope.map((s) => `  ${s.name} : ${showTy(s.ty)}`).join("\n");
  const submit = "本体の式を term に入れて submit_term で提出してください。";
  const base = TEACH === "full"
    ? [GRAMMAR, "", `対象の関数: ${task.fnSig}`, `スコープ内で使えるもの:\n${scopeList}`,
       `仕様: ${task.pySpec}`, `満たすべき例:\n${ailexExamples(task)}`, submit].join("\n")
    : [GRAMMAR_MIN, `対象の関数: ${task.fnSig}`, `仕様: ${task.pySpec}`,
       `満たすべき例:\n${ailexExamples(task)}`, submit].join("\n"); // スコープは伏せる

  let pass1 = false; const kinds: string[] = []; let prev = "";
  let lastFb: Feedback = { kind: "ok" };
  for (let r = 1; r <= ROUNDS; r++) {
    const prompt = r === 1 ? base
      : `${base}\n\n前回の提出: ${prev}\n検証結果: ${render(lastFb, mode, scope)}\nこれを修正した本体の式を提出してください。`;
    const term = await gen(prompt, task); // API エラーは throw（握りつぶさない）
    prev = term;
    const { fb, prog, fn } = evaluate(task, term);
    lastFb = fb; // 次ラウンドのフィードバック
    const hid = fb.kind === "ok" && prog && fn ? ailexRun(prog, fn, task.hiddenT) : false;
    if (r === 1) pass1 = hid;
    if (fb.kind === "ok") return { pass1, passK: hid, rounds: r, kinds, term };
    kinds.push(fb.kind);
  }
  return { pass1, passK: false, rounds: ROUNDS, kinds, term: prev };
}

// ───────────────────────── main ─────────────────────────

async function main() {
  let gens: Record<string, Gen> = {};
  const usage: Record<string, Usage> = {};
  let driver: string, real = false, client: any = null;
  for (const a of ARMS) usage[a] = { inTok: 0, outTok: 0 };
  try {
    if (!process.env.ANTHROPIC_API_KEY) throw new Error("ANTHROPIC_API_KEY 未設定");
    const mod: any = await import("@anthropic-ai/sdk");
    client = new mod.default();
    for (const a of ARMS) gens[a] = opusGen(client, usage[a], MODEL);
    real = true; driver = `実モデル（${MODEL}）`;
  } catch (e: any) {
    for (const a of ARMS) gens[a] = standinGen;
    driver = `スタンドイン（実モデル不可: ${e.message}）— 両 arm 同結果・配管検証のみ`;
  }

  console.log("════════════════════════════════════════════════════════════════════");
  console.log(" Ailex 実験 Q1: 構造化フィードバック vs 自然言語フィードバック");
  console.log(`  駆動: ${driver}`);
  console.log(`  TEACH=${TEACH}  ROUNDS=${ROUNDS}  REPEATS=${REPEATS}  arms=[${ARMS.join(", ")}]  タスク数=${TASKS.length}`);
  console.log("════════════════════════════════════════════════════════════════════");

  if (real) {
    try {
      const r = await client.messages.create({ model: MODEL, max_tokens: 128, thinking: { type: "disabled" },
        tools: [{ name: "submit_term", description: "x", strict: true, input_schema: { type: "object", properties: { term: { type: "string" } }, required: ["term"], additionalProperties: false } }],
        tool_choice: { type: "tool", name: "submit_term" }, messages: [{ role: "user", content: "term に x と入れて提出" }] });
      if (!r.content.find((b: any) => b.type === "tool_use")) throw new Error("tool_use が返らない");
      console.log("  スモーク: OK\n");
    } catch (e: any) { console.error("\n[中止] スモーク失敗: " + e.message); process.exit(1); }
  }

  const agg: Record<string, { p1: number; pk: number; rounds: number; kinds: Record<string, number> }> = {};
  for (const a of ARMS) agg[a] = { p1: 0, pk: 0, rounds: 0, kinds: {} };
  const log: any = { startedAt: new Date().toISOString(), driver, model: MODEL, teach: TEACH, rounds: ROUNDS, repeats: REPEATS, arms: ARMS, runs: [] };
  let N = 0;

  for (let rep = 1; rep <= REPEATS; rep++) {
    for (const task of TASKS) {
      N++;
      const row: any = { rep, task: task.name };
      if (REPEATS === 1) console.log(`● ${task.name}`);
      for (const a of ARMS) {
        const res = await runArm(task, gens[a], a);
        agg[a].p1 += res.pass1 ? 1 : 0; agg[a].pk += res.passK ? 1 : 0; agg[a].rounds += res.rounds;
        for (const k of res.kinds) agg[a].kinds[k] = (agg[a].kinds[k] ?? 0) + 1;
        row[a] = res;
        if (REPEATS === 1)
          console.log(`   ${a.padEnd(10)}: pass@1=${res.pass1 ? "✓" : "✗"} pass@k=${res.passK ? "✓" : "✗"} rounds=${res.rounds}  kinds=[${res.kinds.join(",")}]  → ${res.term}`);
      }
      log.runs.push(row);
    }
  }

  const pct = (x: number) => `${x}/${N} (${(100 * x / N).toFixed(0)}%)`;
  console.log("\n──────────────────────────── 集計 ────────────────────────────");
  console.log(`  runs/arm = ${N}`);
  for (const a of ARMS) {
    const g = agg[a];
    console.log(`  [${a}] pass@1 ${pct(g.p1)}   pass@k ${pct(g.pk)}   平均rounds ${(g.rounds / N).toFixed(2)}   修復要因${JSON.stringify(g.kinds)}   コスト$${costOf(MODEL, usage[a]).toFixed(5)}`);
  }
  const has = (a: string) => ARMS.includes(a);
  if (has("nl") && has("nl_rich") && has("structured")) {
    console.log("\n  ── 交絡分離（pass@k）──");
    console.log(`  内容効果 (nl → nl_rich)        : ${agg.nl.pk} → ${agg.nl_rich.pk}  (Δ${agg.nl_rich.pk - agg.nl.pk >= 0 ? "+" : ""}${agg.nl_rich.pk - agg.nl.pk})  ← スコープ情報を足した効果`);
    console.log(`  形式効果 (nl_rich → structured): ${agg.nl_rich.pk} → ${agg.structured.pk}  (Δ${agg.structured.pk - agg.nl_rich.pk >= 0 ? "+" : ""}${agg.structured.pk - agg.nl_rich.pk})  ← 同じ情報を JSON にした効果`);
    console.log("  解釈: 内容効果が大きく形式効果が小さい → 効くのは『スコープ情報』であって『JSON形式』ではない。");
  } else if (has("nl") && has("structured")) {
    console.log(`\n  差分: pass@k structured−nl = ${agg.structured.pk - agg.nl.pk}   平均rounds nl=${(agg.nl.rounds / N).toFixed(2)} structured=${(agg.structured.rounds / N).toFixed(2)}`);
  }
  console.log("──────────────────────────────────────────────────────────────");

  // フィードバック描画の実例（両形式の違いを目視）: norm に v を提出＝型エラー
  const normTask = TASKS.find((t) => t.name === "norm")!;
  const demoProg = parseProg(buildAilex(normTask, "?h"));
  const demoScope = scopeFor(demoProg, demoProg.fns[0]);
  const demo = evaluate(normTask, "v");
  console.log("\n［参考］同じ検証結果の描画例（norm に v を提出＝型エラー時）:");
  console.log("  nl        : " + renderNL(demo.fb));
  console.log("  nl_rich   : " + renderNLRich(demo.fb, demoScope));
  console.log("  structured: " + renderStructured(demo.fb, demoScope));

  log.summary = agg;
  try { mkdirSync("ailex/logs", { recursive: true }); const fn = `ailex/logs/q1-${new Date().toISOString().replace(/[:.]/g, "-")}.json`; writeFileSync(fn, JSON.stringify(log, null, 2)); console.log(`\n  ログ: ${fn}`); }
  catch (e: any) { console.log(`  （ログ保存スキップ: ${e.message}）`); }
}

main().catch((e) => { console.error("\n[実行エラー] " + (e?.stack || e?.message || e)); process.exit(1); });
