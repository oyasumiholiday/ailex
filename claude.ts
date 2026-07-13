// Ailex — 列挙器を Claude Opus に差し替える
//
// synth.ts は「型が許容集合を計算できる」ことを、訓練データ無しの列挙器で実証した。
// ここでは列挙器を LLM（Claude Opus 4.8）に差し替え、逐次マスク（Hazel 流）で生成を駆動する。
//
// 実行: node ailex/claude.ts   （ANTHROPIC_API_KEY と @anthropic-ai/sdk があれば実 Opus を駆動）
//
// Claude API はロジットを公開しないので、logit masking はできない。代わりに
//   ・各ホールの許容集合を型検査器が計算し（マスク）
//   ・それを strict な enum ツール入力として Opus に渡す
//   ・structured output（strict tool use）が「返り値は enum のどれか」を保証する
// これが Claude における honest な constrained decoding：型エラーな選択は enum に存在せず、
// モデルは物理的にそれを出力できない（§2）。列挙の代わりに Opus の学習済み事前分布で選ぶ。

import "./env.ts"; // ailex/.env から ANTHROPIC_API_KEY 等を読む（無ければ何もしない）
import { lex, Parser, showTy, showTerm, tyEq, evalTerm, checkFn, tFloat, tInt, tBool } from "./prototype.ts";
import type { Ty, Term, Fn, Program, Val, RuntimeObs } from "./prototype.ts";
import { scopeFor } from "./synth.ts";
import type { Scope } from "./synth.ts";

// ───────────────────────── 逐次マスク：ホール1つ分の許容選択肢 ─────────────────────────

let nid = 9000;
const id = () => nid++;
const freshHole = (): Term => { const n = id(); return { k: "hole", name: `g${n}`, id: n }; };

// Choice は「この選択肢が開くホールの期待型（opens）」を持つ。マスク刈り込みを一様に行うため。
interface Choice { label: string; opens: Ty[]; build: () => Term }

const FLOAT_LITS = [-1.0, 0.0, 1.0]; // 固定パレット（任意定数でなく＝pure-enum マスクとの妥協）
const INT_LITS = [0, 1];

// 型 goal のホールを埋める許容選択肢（＝この一手のマスク・刈り込み前）。型検査器から計算できる。
function choicesFor(goal: Ty, scope: Scope): Choice[] {
  const cs: Choice[] = [];
  // 変数
  for (const { name, ty } of scope)
    if (ty.k !== "fun" && tyEq(ty, goal)) cs.push({ label: name, opens: [], build: () => ({ k: "var", name, id: id() }) });
  // 数値リテラル（小パレット）
  if (goal.k === "base" && goal.name === "Float")
    for (const n of FLOAT_LITS) cs.push({ label: n.toFixed(1), opens: [], build: () => ({ k: "float", v: n, id: id() }) });
  if (goal.k === "base" && goal.name === "Int")
    for (const n of INT_LITS) cs.push({ label: String(n), opens: [], build: () => ({ k: "int", v: n, id: id() }) });
  // 適用
  for (const { name, ty } of scope)
    if (ty.k === "fun" && tyEq(ty.ret, goal)) {
      const params = (ty as { params: Ty[] }).params;
      cs.push({ label: `${name}(…)`, opens: params, build: () => ({ k: "app", head: name, args: params.map(() => freshHole()), id: id() }) });
    }
  // if（多相：条件 Bool、両枝 goal）
  cs.push({ label: "if(…)", opens: [tBool, goal, goal], build: () => ({ k: "if", cond: freshHole(), then: freshHole(), els: freshHole(), id: id() }) });
  return cs;
}

// 型 goal の項が scope 内に depth 以内で構成可能か（例は無視・純粋に型の充足可能性）。
// 注: if は両枝が goal 型なので、goal が他手段で充足できない限り if も助けにならない → if は数えない。
function typeFillable(goal: Ty, scope: Scope, depth: number): boolean {
  for (const { ty } of scope) if (ty.k !== "fun" && tyEq(ty, goal)) return true;
  if (goal.k === "base" && (goal.name === "Float" || goal.name === "Int")) return true; // リテラルで充足可
  if (depth <= 0) return false;
  for (const { ty } of scope)
    if (ty.k === "fun" && tyEq(ty.ret, goal) && (ty as { params: Ty[] }).params.every((p) => typeFillable(p, scope, depth - 1)))
      return true;
  return false;
}

// マスク＝許容集合を、行き止まり（開くホールの型が充足不能）を除いて提示する。
// これが typed-hole 補完オラクルの正しい挙動：選んでも完成できない手はそもそも見せない。
function maskFor(goal: Ty, scope: Scope): Choice[] {
  return choicesFor(goal, scope).filter((c) => c.opens.every((t) => typeFillable(t, scope, 4)));
}

function fillHole(term: Term, holeName: string, replacement: Term): Term {
  if (term.k === "hole" && term.name === holeName) return replacement;
  if (term.k === "app") return { ...term, args: term.args.map((a) => fillHole(a, holeName, replacement)) };
  if (term.k === "list") return { ...term, elems: term.elems.map((e) => fillHole(e, holeName, replacement)) };
  if (term.k === "if") return { ...term, cond: fillHole(term.cond, holeName, replacement), then: fillHole(term.then, holeName, replacement), els: fillHole(term.els, holeName, replacement) };
  return term;
}

interface HoleView { name: string; expected: Ty; obligations: string[] }

function holesOf(prog: Program, fn: Fn, body: Term): HoleView[] {
  const withFn: Program = { ...prog, fns: prog.fns.map((f) => (f.name === fn.name ? { ...fn, body } : f)) };
  return checkFn(withFn, { ...fn, body }).holes.map((h) => ({ name: h.name, expected: h.expected, obligations: h.obligations }));
}

// ───────────────────────── 義務（eg 実例 + ensures）の評価 ─────────────────────────

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
  return obs.length === 0;
}

// ───────────────────────── ポリシー：どの選択肢を選ぶか ─────────────────────────

interface PolicyCtx { prog: Program; fn: Fn; body: Term; hole: HoleView; choices: Choice[]; scope: Scope; hint?: string }
type Policy = (ctx: PolicyCtx) => Promise<number>;

// スタンドイン：到達可能性で探索する内蔵ソルバ（API 不在時に harness を走らせるため）。
// 実 LLM はこの探索を学習済み事前分布に置き換える。
function reachable(prog: Program, fn: Fn, body: Term, depth: number): boolean {
  const holes = holesOf(prog, fn, body);
  if (holes.length === 0) return passesExamples(prog, fn, body);
  if (depth <= 0) return false;
  const h = holes[0];
  for (const c of maskFor(h.expected, scopeFor(prog, fn)))
    if (reachable(prog, fn, fillHole(body, h.name, c.build()), depth - 1)) return true;
  return false;
}

// 反復深化：最も浅い解に繋がる選択肢を選ぶ（貪欲な深追いで巨大項に迷い込むのを防ぐ）。
const searchPolicy: Policy = async (ctx) => {
  for (let d = 0; d <= 9; d++)
    for (let i = 0; i < ctx.choices.length; i++)
      if (reachable(ctx.prog, ctx.fn, fillHole(ctx.body, ctx.hole.name, ctx.choices[i].build()), d)) return i;
  return 0;
};

// 実 Claude Opus 4.8：strict enum のツール入力で「返り値は許容集合のどれか」を API が保証する。
interface Usage { inTok: number; outTok: number }
function claudePolicy(client: any, usage?: Usage, model = "claude-opus-4-8"): Policy {
  return async (ctx) => {
    const labels = ctx.choices.map((c) => c.label);
    const scopeDesc = ctx.scope.map((s) => `  ${s.name} : ${showTy(s.ty)}`).join("\n");
    const prompt = [
      "あなたは Ailex（型付き言語）の穴を埋めています。目標はホールを、型を保ちつつ実例を満たすように埋めること。",
      `\n埋めるホールの期待型: ${showTy(ctx.hole.expected)}`,
      `満たすべき義務（契約と実例）:\n  ${ctx.hole.obligations.join("\n  ")}`,
      `スコープ内の変数・関数:\n${scopeDesc}`,
      `現在の本体（? がホール）: ${showTerm(ctx.body)}`,
      ctx.hint ? `\n【前回までの失敗】${ctx.hint}\n別の道を選んでください。` : "",
      "\nこのホールを開始する構成子を choose_next ツールで1つ選んでください。",
      "選択肢は型的に許容されるものだけです（どれを選んでも型エラーにはなりません）。実例を満たす道に繋がるものを選んでください。",
    ].join("\n");

    const tool = {
      name: "choose_next",
      description: "現在のホールを埋める構成子を1つ選ぶ。",
      strict: true,
      input_schema: {
        type: "object",
        properties: { choice: { type: "string", enum: labels } },
        required: ["choice"],
        additionalProperties: false,
      },
    };

    const res = await client.messages.create({
      model,
      max_tokens: 1024,
      thinking: { type: "disabled" },
      tools: [tool],
      tool_choice: { type: "tool", name: "choose_next" },
      messages: [{ role: "user", content: prompt }],
    });
    if (usage) { usage.inTok += res.usage?.input_tokens ?? 0; usage.outTok += res.usage?.output_tokens ?? 0; }
    const call = res.content.find((b: any) => b.type === "tool_use");
    const picked = call?.input?.choice;
    const idx = labels.indexOf(picked);
    return idx >= 0 ? idx : 0; // strict enum なので常に一致するはず
  };
}

// ───────────────────────── 逐次生成ループ ─────────────────────────

async function generate(prog: Program, fn0: Fn, policy: Policy, quiet = false, hint?: string): Promise<Fn> {
  const say = (s: string) => { if (!quiet) console.log(s); };
  let body = fn0.body;
  for (let step = 1; step <= 40; step++) {
    const holes = holesOf(prog, fn0, body);
    if (holes.length === 0) break;
    const h = holes[0];
    const scope = scopeFor(prog, fn0);
    const choices = maskFor(h.expected, scope);
    if (choices.length === 0) { say(`  手${step}: ホール ?${h.name} : ${showTy(h.expected)} — 許容集合が空（この経路は行き止まり）`); break; }
    const mask = choices.map((c) => c.label);
    say(`  手${step}: ホール ?${h.name} : ${showTy(h.expected)}`);
    say(`     マスク（型検査器が計算した許容集合・Opus はこの enum 内しか出力できない）: [ ${mask.join("  ")} ]`);
    const idx = await policy({ prog, fn: fn0, body, hole: h, choices, scope, hint });
    say(`     ポリシーの選択: ${mask[idx]}`);
    body = fillHole(body, h.name, choices[idx].build());
    say(`     → 本体: ${showTerm(body)}\n`);
  }
  return { ...fn0, body };
}

// ───────────────────────── main ─────────────────────────

async function main() {
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
  const fn0 = prog.fns[0];

  console.log("════════════════════════════════════════════════════════════");
  console.log(" Ailex: 列挙器を Claude Opus に差し替えた逐次生成");
  console.log(" 各手でマスク（許容集合）を出し、その enum 内でモデルが選ぶ");
  console.log("════════════════════════════════════════════════════════════\n");

  // 実 Opus を試み、SDK/鍵/接続が無ければスタンドインへフォールバック（正直に明示）
  let policy: Policy;
  let driver: string;
  try {
    const key = process.env.ANTHROPIC_API_KEY;
    if (!key) throw new Error("ANTHROPIC_API_KEY 未設定");
    const mod: any = await import("@anthropic-ai/sdk");
    const Anthropic = mod.default;
    policy = claudePolicy(new Anthropic());
    driver = "Claude Opus 4.8（strict enum ツール使用・実 API）";
  } catch (e: any) {
    policy = searchPolicy;
    driver = `内蔵ソルバ（スタンドイン）— 実 Opus 不可: ${e.message}`;
  }
  console.log(`駆動ポリシー: ${driver}\n`);

  const done = await generate(prog, fn0, policy);

  console.log("────────────────────────────────────────────────────────────");
  console.log(`生成結果: ${showTerm(done.body)}`);
  const ok = passesExamples(prog, fn0, done.body);
  console.log(`型: クリーン（ホール無し）／ 実例 eg norm([3,4])=5 と ensures ret>=0: ${ok ? "達成 ✅" : "未達 ❌"}`);
  console.log("────────────────────────────────────────────────────────────");
  console.log("要点: マスクは型検査器が各手で計算する（§2）。strict enum ツール使用により、");
  console.log("      Opus の出力はそのマスク内に API レベルで拘束される＝型エラーは表現不可能。");
  console.log("      logit masking（ロジット非公開のため不可）の代わりに、structured output で同じ保証を得る。");
}

// 直接実行時のみデモを走らせる（compare.ts から import しても副作用を出さない）
if (process.argv[1] && process.argv[1].endsWith("claude.ts")) main();

export { generate, maskFor, fillHole, passesExamples, searchPolicy, claudePolicy };
export type { Policy, Choice, Usage };
