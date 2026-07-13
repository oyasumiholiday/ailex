// Ailex — AI 生成実験（新コア v0.3.1 版）
// 問い: 育った Ailex（レコード・HOF・エイリアス込み）を、モデルは「早見表だけ」(in-context)でどれだけ書けるか。
// 方式: 関数の本体式を書かせる。検査は言語ネイティブの構造化診断(check)＋公開契約(eg)。採点は隠しテスト。
//       修復フィードバック=構造化診断そのまま（scope/fields の開示は言語側の標準機能）。
//
// 実行: node ailex/core/aigen.ts
//   MODEL（既定 claude-haiku-4-5）, ROUNDS（既定 3）, REPEATS（既定 1）
//   鍵は ailex/.env か ANTHROPIC_API_KEY。無ければスタンドイン（配管検証のみ）。

import "../env.ts";
import { parseProgram, check, runContracts, evalInProgram, valEq } from "./lang.ts";
import { writeFileSync, mkdirSync } from "node:fs";

const MODEL = process.env.MODEL || "claude-haiku-4-5";
const ROUNDS = Number(process.env.ROUNDS || 3);
const REPEATS = Number(process.env.REPEATS || 1);
const PRICING: Record<string, [number, number]> = {
  "claude-opus-4-8": [5, 25], "claude-sonnet-5": [3, 15], "claude-haiku-4-5": [1, 5], "claude-fable-5": [10, 50],
};
interface Usage { inTok: number; outTok: number }
const costOf = (m: string, u: Usage) => { const [i, o] = PRICING[m] || [5, 25]; return u.inTok / 1e6 * i + u.outTok / 1e6 * o; };

// ───────────────────────── 言語の早見表（in-context 学習の全て）─────────────────────────

// v0.5.1 の早見表（PRIMER.md の圧縮版。A3 以降の実験はこれを使用）
const PRIMER = `Ailex という小さな型付き言語の「関数の本体（式1つ）」を書いてください。早見表（これが言語の全てです）:
- 型: Int, Float, Bool, String, List[T], Option[T], レコード {x : Float, y : Float}, 関数 (T) -> U。Int と Float は混在不可（toFloat/toInt で変換）
- リテラル: 1 / 1.0 / true / "s" / リスト [1.0, 2.0] / レコード {x = 1.0, y = 2.0}
- フィールド: p.x（連鎖可）
- 演算子: + - * /（/ は Int で切り捨て。+ は String の連結にも使える）、== != > >= < <=（== はリスト/レコードも深く比較）、&& || !
- 分岐は式: if(cond, then, else)
- 束縛: let x : T = 式 in 式
- 無名関数: fn (x) => x * 2.0（引数の型注釈は任意）
- 組み込み: sqrt(Float)->Float, toFloat, toInt / length, get(v,i), head, tail, append, headOr(v,d), getOr(v,i,d) /
  map(v, f)（List にも Option にも効く）, filter(v, 述語), fold(v, 初期値, fn (acc, x) => ...)（初期値に [] や none も可） / dot, sum /
  strlen, concat, split(s,sep), join(xs,sep), contains, substring(s,i,j), trim, toString /
  Option: some(x), none, isSome(o), unwrapOr(o, 既定値), find(v, 述語)->Option[T], parseInt(s)->Option[Int], parseFloat(s)->Option[Float]
- 失敗しうる操作（find/parseInt/parseFloat）は Option を返す。none は型が文脈から分かる位置でだけ書ける。
- return や文は無い。本体は式1つ。`;

// PRIMER_LANG=en で英語正典（PRIMER.en.md）を教材に使う（英語ドキュメントの実効性検証用）
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const PRIMER_EN = (() => {
  try { return "You are writing the body (a single expression) of an Ailex function.\n" +
    readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "PRIMER.en.md"), "utf8"); }
  catch { return PRIMER; }
})();
const ACTIVE_PRIMER = process.env.PRIMER_LANG === "en" ? PRIMER_EN : PRIMER;

// ───────────────────────── タスク（8問・v0.3 の機能を使わないと解けない構成）─────────────────────────

interface Task {
  name: string;
  header: string;              // type エイリアス＋fn シグネチャ＋契約＋"body Ty"（ここに本体を差し込む）
  fname: string;
  spec: string;                // 自然言語仕様
  hidden: [string, number | boolean | string][]; // [式, 期待値]（モデルに見せない）
}

const T = (name: string, fname: string, header: string, spec: string, hidden: Task["hidden"]): Task => ({ name, fname, header, spec, hidden });

const TASKS: Task[] = [
  T("scale", "scale",
    `fn scale (v : List[Float], k : Float) -> List[Float]\n  eg scale([1.0, 2.0], 10.0) = [10.0, 20.0]\nbody List[Float]`,
    "リスト v の各要素を k 倍したリストを返す。",
    [["get(scale([3.0, 4.0], 2.0), 1)", 8], ["length(scale([], 5.0))", 0]]),
  T("countNeg", "countNeg",
    `fn countNeg (v : List[Float]) -> Int\n  eg countNeg([1.0, -2.0, -3.0]) = 2\nbody Int`,
    "リスト v の中の負の数（0 未満）の個数を返す。",
    [["countNeg([-1.0, -2.0, -3.0])", 3], ["countNeg([5.0])", 0], ["countNeg([0.0])", 0]]),
  T("product", "product",
    `fn product (v : List[Int]) -> Int\n  eg product([2, 3, 4]) = 24\nbody Int`,
    "リスト v の全要素の積を返す。空リストは 1。",
    [["product([5, 6])", 30], ["product([])", 1]]),
  T("dist", "dist",
    `type Point = {x : Float, y : Float}\nfn dist (p : Point, q : Point) -> Float\n  ensures ret >= 0.0\n  eg dist({x = 0.0, y = 0.0}, {x = 3.0, y = 4.0}) = 5.0\nbody Float`,
    "2点 p, q のユークリッド距離を返す。",
    [["dist({x = 1.0, y = 1.0}, {x = 4.0, y = 5.0})", 5], ["dist({x = 2.0, y = 2.0}, {x = 2.0, y = 2.0})", 0]]),
  T("midpoint", "midpoint",
    `type Point = {x : Float, y : Float}\nfn midpoint (p : Point, q : Point) -> Point\n  eg midpoint({x = 0.0, y = 0.0}, {x = 4.0, y = 6.0}) = {x = 2.0, y = 3.0}\nbody Point`,
    "2点 p, q の中点（座標ごとの平均）をレコードで返す。",
    [["midpoint({x = 2.0, y = 0.0}, {x = 4.0, y = 10.0}).x", 3], ["midpoint({x = 2.0, y = 0.0}, {x = 4.0, y = 10.0}).y", 5]]),
  T("catTotal", "catTotal",
    `type Expense = {amount : Float, cat : String}\nfn catTotal (es : List[Expense], c : String) -> Float\n  eg catTotal([{amount = 3.0, cat = "food"}, {amount = 9.0, cat = "food"}, {amount = 12.0, cat = "edu"}], "food") = 12.0\nbody Float`,
    "支出レコードのリスト es から、カテゴリが c のものだけの金額合計を返す。",
    [[`catTotal([{amount = 5.0, cat = "a"}, {amount = 7.0, cat = "b"}], "b")`, 7], [`catTotal([], "x")`, 0]]),
  T("clampAll", "clampAll",
    `fn clampAll (v : List[Float], lo : Float, hi : Float) -> List[Float]\n  eg clampAll([-1.0, 5.0, 99.0], 0.0, 10.0) = [0.0, 5.0, 10.0]\nbody List[Float]`,
    "リスト v の各要素を [lo, hi] の範囲に収めたリストを返す（lo 未満は lo、hi 超は hi）。",
    [["get(clampAll([12.0], 0.0, 10.0), 0)", 10], ["get(clampAll([-5.0, 3.0], 0.0, 10.0), 0)", 0]]),
  T("maxAmount", "maxAmount",
    `type Expense = {amount : Float, cat : String}\nfn maxAmount (es : List[Expense]) -> Float\n  eg maxAmount([{amount = 3.0, cat = "a"}, {amount = 12.0, cat = "b"}, {amount = 7.0, cat = "c"}]) = 12.0\nbody Float`,
    "支出レコードのリスト es の中で最大の金額を返す。空リストは 0.0。",
    [[`maxAmount([{amount = 2.0, cat = "x"}])`, 2], [`maxAmount([])`, 0]]),

  // ── A3 で追加（v0.4/v0.5 の機能を要する 8 問）──
  T("safeDiv", "safeDiv",
    `fn safeDiv (a : Int, b : Int) -> Option[Int]\n  eg safeDiv(10, 2) = some(5)\n  eg safeDiv(1, 0) = none\nbody Option[Int]`,
    "a を b で割った商（切り捨て）を返す。b が 0 なら none。",
    [["unwrapOr(safeDiv(9, 2), -1)", 4], ["isSome(safeDiv(3, 0))", false]]),
  T("sumParsed", "sumParsed",
    `fn sumParsed (ss : List[String]) -> Int\n  eg sumParsed(["10", "x", "20"]) = 30\nbody Int`,
    "文字列のリストのうち、整数として読めるものだけを合計する（読めないものは無視）。",
    [[`sumParsed(["1", "2", "3"])`, 6], [`sumParsed(["a", "b"])`, 0], [`sumParsed([])`, 0]]),
  T("nameFirstBig", "nameFirstBig",
    `type Expense = {amount : Float, cat : String}\nfn nameFirstBig (es : List[Expense], lim : Float) -> String\n  eg nameFirstBig([{amount = 3.0, cat = "food"}, {amount = 200.0, cat = "travel"}], 100.0) = "travel"\n  eg nameFirstBig([{amount = 3.0, cat = "food"}], 100.0) = "none"\nbody String`,
    `金額が lim を超える最初の支出のカテゴリ名を返す。無ければ "none" を返す。`,
    [[`nameFirstBig([{amount = 150.0, cat = "a"}, {amount = 300.0, cat = "b"}], 100.0)`, "a"], [`nameFirstBig([], 5.0)`, "none"]]),
  T("initials", "initials",
    `fn initials (s : String) -> String\n  eg initials("ai native language") = "anl"\nbody String`,
    "空白区切りの各単語の先頭1文字を連結して返す。",
    [[`initials("hello world")`, "hw"], [`initials("x")`, "x"]]),
  T("moveBy", "moveBy",
    `type Point = {x : Float, y : Float}\nfn moveBy (p : Point, dx : Float, dy : Float) -> Point\n  eg moveBy({x = 1.0, y = 2.0}, 10.0, 0.5) = {x = 11.0, y = 2.5}\nbody Point`,
    "点 p を (dx, dy) だけ平行移動した新しい点を返す。",
    [["moveBy({x = 0.0, y = 0.0}, 3.0, 4.0).x", 3], ["moveBy({x = 1.0, y = 1.0}, 0.0, -1.0).y", 0]]),
  T("countCat", "countCat",
    `type Expense = {amount : Float, cat : String}\nfn countCat (es : List[Expense], c : String) -> Int\n  eg countCat([{amount = 1.0, cat = "a"}, {amount = 2.0, cat = "b"}, {amount = 3.0, cat = "a"}], "a") = 2\nbody Int`,
    "カテゴリが c である支出の個数を返す。",
    [[`countCat([{amount = 1.0, cat = "x"}], "y")`, 0], [`countCat([], "z")`, 0]]),
  T("labelAll", "labelAll",
    `fn labelAll (ns : List[Int]) -> List[String]\n  eg labelAll([1, 2]) = ["#1", "#2"]\nbody List[String]`,
    `各整数 n を "#" + n の文字列に変換したリストを返す。`,
    [[`get(labelAll([7]), 0)`, "#7"], [`length(labelAll([]))`, 0]]),
  T("bestScore", "bestScore",
    `type Student = {name : String, score : Int}\nfn bestScore (ss : List[Student]) -> Option[Student]\n  eg bestScore([{name = "a", score = 1}, {name = "b", score = 9}]) = some({name = "b", score = 9})\n  eg bestScore([]) = none\nbody Option[Student]`,
    "最高得点の学生を返す。空リストなら none。",
    [[`unwrapOr(bestScore([{name = "x", score = 5}]), {name = "?", score = 0}).name`, "x"], [`isSome(bestScore([]))`, false]]),
];

const buildSrc = (t: Task, body: string) => `${t.header}\n  ${body}\nend ${t.fname}`;

// ───────────────────────── 検証（言語ネイティブの構造化診断をそのまま使う）─────────────────────────

function verify(t: Task, body: string): { stage: "parse" | "type" | "contract" | "ok"; feedback: string; hiddenPass: boolean } {
  const src = buildSrc(t, body);
  let prog;
  try { prog = parseProgram(src); }
  catch (e: any) { return { stage: "parse", feedback: JSON.stringify({ ok: false, errors: [{ code: "parse", detail: e.message }] }), hiddenPass: false }; }
  const r = check(prog);
  if (!r.ok) return { stage: "type", feedback: JSON.stringify({ ok: false, errors: r.errors.slice(0, 2) }), hiddenPass: false };
  const viol = runContracts(prog);
  const hiddenPass = t.hidden.every(([expr, want]) => { try { return valEq(evalInProgram(prog!, expr), want as any); } catch { return false; } });
  if (viol.length) return { stage: "contract", feedback: JSON.stringify({ ok: false, errors: viol }), hiddenPass };
  return { stage: "ok", feedback: "", hiddenPass };
}

// ───────────────────────── 生成（実モデル or スタンドイン）─────────────────────────

type Gen = (prompt: string, t: Task) => Promise<string>;
const strip = (s: string) => s.trim().replace(/^```[a-zA-Z]*\s*\n?/, "").replace(/\n?```$/, "").trim();

function opusGen(client: any, usage: Usage): Gen {
  return async (prompt) => {
    const tool = { name: "submit_body", description: "Ailex の関数本体（式1つ）を提出する。", strict: true,
      input_schema: { type: "object", properties: { body: { type: "string" } }, required: ["body"], additionalProperties: false } };
    const res = await client.messages.create({
      model: MODEL, max_tokens: 1024, thinking: { type: "disabled" },
      tools: [tool], tool_choice: { type: "tool", name: "submit_body" },
      messages: [{ role: "user", content: prompt }],
    });
    usage.inTok += res.usage?.input_tokens ?? 0; usage.outTok += res.usage?.output_tokens ?? 0;
    return strip(res.content.find((b: any) => b.type === "tool_use")?.input?.body ?? "");
  };
}

// スタンドイン: 1手目わざと誤り（種類を散らす）→2手目正解。配管検証専用。
const STANDIN: Record<string, [string, string]> = {
  scale: ["map(v, fn (x : Float) => x + k)", "map(v, fn (x : Float) => x * k)"],
  countNeg: ["length(filter(v, fn (x : Float) => x < 0.0)", "length(filter(v, fn (x : Float) => x < 0.0))"],
  product: ["fold(v, 0, fn (a : Int, x : Int) => a * x)", "fold(v, 1, fn (a : Int, x : Int) => a * x)"],
  dist: ["p.x - q.x", "sqrt((p.x - q.x) * (p.x - q.x) + (p.y - q.y) * (p.y - q.y))"],
  midpoint: ["{x = p.x, y = p.y}", "{x = (p.x + q.x) / 2.0, y = (p.y + q.y) / 2.0}"],
  catTotal: ["sum(map(es, fn (e : Expense) => e.amount))", `fold(filter(es, fn (e : Expense) => e.cat == c), 0.0, fn (a : Float, e : Expense) => a + e.amount)`],
  clampAll: ["map(v, fn (x : Float) => x)", "map(v, fn (x : Float) => if(x < lo, lo, if(x > hi, hi, x)))"],
  maxAmount: ["fold(es, 0.0, fn (a : Float, e : Expense) => e.amount)", "fold(es, 0.0, fn (a : Float, e : Expense) => if(e.amount > a, e.amount, a))"],
  safeDiv: ["a / b", "if(b == 0, none, some(a / b))"],
  sumParsed: ["fold(ss, 0, fn (a, s) => a + unwrapOr(parseInt(s), -1))", "fold(ss, 0, fn (a, s) => a + unwrapOr(parseInt(s), 0))"],
  nameFirstBig: [`unwrapOr(find(es, fn (e) => e.amount > lim), {amount = 0.0, cat = "none"}).amount`, `unwrapOr(find(es, fn (e) => e.amount > lim), {amount = 0.0, cat = "none"}).cat`],
  initials: [`join(map(split(s, " "), fn (w) => w), "")`, `join(map(split(s, " "), fn (w) => substring(w, 0, 1)), "")`],
  moveBy: ["{x = p.x, y = p.y}", "{x = p.x + dx, y = p.y + dy}"],
  countCat: [`length(filter(es, fn (e) => e.amount > 0.0))`, `length(filter(es, fn (e) => e.cat == c))`],
  labelAll: [`map(ns, fn (n) => toString(n))`, `map(ns, fn (n) => "#" + toString(n))`],
  bestScore: ["find(ss, fn (s) => s.score > 0)", "fold(ss, none, fn (acc, s) => if(isSome(acc), if(s.score > unwrapOr(acc, s).score, some(s), acc), some(s)))"],
};
const standinGen: Gen = async (prompt, t) => STANDIN[t.name][prompt.includes("前回の提出") ? 1 : 0];

// ───────────────────────── main ─────────────────────────

async function main() {
  let gen: Gen, driver: string, real = false, client: any = null;
  const usage: Usage = { inTok: 0, outTok: 0 };
  try {
    if (!process.env.ANTHROPIC_API_KEY) throw new Error("ANTHROPIC_API_KEY 未設定");
    const mod: any = await import("@anthropic-ai/sdk");
    client = new mod.default();
    gen = opusGen(client, usage); real = true; driver = `実モデル（${MODEL}）`;
  } catch (e: any) { gen = standinGen; driver = `スタンドイン（実モデル不可: ${e.message}）— 配管検証のみ`; }

  console.log("════════════════════════════════════════════════════════════════════");
  console.log(" Ailex AI生成実験（新コア v0.3.1）: 早見表だけでモデルは Ailex を書けるか");
  console.log(`  駆動: ${driver}  ROUNDS=${ROUNDS}  REPEATS=${REPEATS}  タスク=${TASKS.length}`);
  console.log("════════════════════════════════════════════════════════════════════");

  if (real) { // スモーク
    try {
      const r = await client.messages.create({ model: MODEL, max_tokens: 128, thinking: { type: "disabled" },
        tools: [{ name: "submit_body", description: "x", strict: true, input_schema: { type: "object", properties: { body: { type: "string" } }, required: ["body"], additionalProperties: false } }],
        tool_choice: { type: "tool", name: "submit_body" }, messages: [{ role: "user", content: "body に x と入れて提出" }] });
      if (!r.content.find((b: any) => b.type === "tool_use")) throw new Error("tool_use が返らない");
      console.log("  スモーク: OK\n");
    } catch (e: any) {
      console.error("\n[中止] スモーク失敗: " + e.message);
      if (String(e.message).includes("authentication")) console.error("  → 鍵を確認（ailex/.env）。ローテーション済みなら新しい鍵に差し替えてください。");
      process.exit(1);
    }
  }

  let p1 = 0, pk = 0, roundsSum = 0, N = 0;
  const kinds: Record<string, number> = {};
  const log: any = { startedAt: new Date().toISOString(), driver, model: MODEL, rounds: ROUNDS, repeats: REPEATS, runs: [] };

  for (let rep = 1; rep <= REPEATS; rep++) {
    for (const t of TASKS) {
      N++;
      const base = [ACTIVE_PRIMER, "", `課題: ${t.spec}`, "この関数の本体（式1つ）を書きます:", t.header, `end ${t.fname}`, "本体の式だけを submit_body で提出してください。"].join("\n");
      let prev = "", fb = "", pass1 = false, passK = false, r = 1, kindTrail: string[] = [];
      const attempts: { r: number; body: string; stage: string; feedback?: string }[] = []; // 全試行を記録（構文つまずきの分析用）
      for (; r <= ROUNDS; r++) {
        const prompt = r === 1 ? base : `${base}\n\n前回の提出: ${prev}\n検証結果(構造化診断): ${fb}\n修正した本体の式を提出してください。`;
        const body = await gen(prompt, t);
        prev = body;
        const v = verify(t, body);
        attempts.push({ r, body, stage: v.stage, feedback: v.stage === "ok" ? undefined : v.feedback });
        if (r === 1) pass1 = v.stage === "ok" && v.hiddenPass;
        if (v.stage === "ok") { passK = v.hiddenPass; break; }
        kindTrail.push(v.stage); kinds[v.stage] = (kinds[v.stage] ?? 0) + 1;
        fb = v.feedback;
      }
      p1 += pass1 ? 1 : 0; pk += passK ? 1 : 0; roundsSum += Math.min(r, ROUNDS);
      log.runs.push({ rep, task: t.name, pass1, passK, rounds: Math.min(r, ROUNDS), kinds: kindTrail, attempts });
      if (REPEATS === 1) console.log(`● ${t.name.padEnd(9)} pass@1=${pass1 ? "✓" : "✗"} pass@k=${passK ? "✓" : "✗"} rounds=${Math.min(r, ROUNDS)} kinds=[${kindTrail.join(",")}]\n   → ${prev}`);
    }
  }

  const pct = (x: number) => `${x}/${N} (${(100 * x / N).toFixed(0)}%)`;
  console.log("\n──────────────────────────── 集計 ────────────────────────────");
  console.log(`  pass@1 ${pct(p1)}   pass@k ${pct(pk)}   平均rounds ${(roundsSum / N).toFixed(2)}`);
  console.log(`  修復要因 ${JSON.stringify(kinds)}   トークン in=${usage.inTok} out=${usage.outTok}   コスト$${costOf(MODEL, usage).toFixed(5)}`);
  console.log("──────────────────────────────────────────────────────────────");
  console.log("注: 採点は隠しテスト（モデルに見せない）。修復は構造化診断＋公開 eg のみ。数値は実モデル時のみ有意。");

  log.summary = { N, p1, pk, meanRounds: roundsSum / N, kinds, usage, cost: costOf(MODEL, usage) };
  try { mkdirSync("ailex/logs", { recursive: true }); const fn = `ailex/logs/aigen-${new Date().toISOString().replace(/[:.]/g, "-")}.json`; writeFileSync(fn, JSON.stringify(log, null, 2)); console.log(`  ログ: ${fn}`); } catch {}
}

main().catch((e) => { console.error("\n[実行エラー] " + (e?.stack || e?.message || e)); process.exit(1); });
