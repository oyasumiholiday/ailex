// Ailex — 比較実験ハーネス（測定版）
//
// 仮説の実測：「Ailex + マスク」 vs 「Python + 事後チェック修復ループ」を、同じモデル・同じ題材で対戦させる。
// 測るのは機能的正解率とコスト（優劣判定ではない）。詳細は README.draft.md の評価指標を参照。
//
// 設計上の要点：
//  ・公開例(publicT)＝プロンプトに見せる＆修復フィードバックに使う。隠しテスト(hiddenT)＝採点のみ・絶対に見せない。
//    → 修復が隠しテストに漏れない（テストリーク防止）。pass@1 と pass@k を分けて報告。
//  ・両サイドに修復ループ。Python のラウンドが何のエラー(構文/実行時/誤答)に消えたかを分類 → マスクが何を消すかを見る。
//  ・Ailex 側の型エラー数は主指標にしない（構造的にゼロ＝循環論法）。
//  ・APIエラーはタスク失敗に化けさせず、起動スモークで先に検出して停止する。
//
// 実行: node ailex/compare.ts
//   環境変数: MODEL / AILEX_MODEL / PY_MODEL（既定 claude-opus-4-8）, ROUNDS（既定3）, REPEATS（既定1）
//   ANTHROPIC_API_KEY + @anthropic-ai/sdk があれば実モデル駆動。無ければスタンドイン（配管検証のみ）。
//
// ⚠ Python サイドはモデル生成コードを python3 サブプロセスで実行する（HumanEval 方式・5秒タイムアウト）。
//    ネットワーク隔離した使い捨て環境で実行すること。

import "./env.ts"; // ailex/.env から ANTHROPIC_API_KEY 等を読む（無ければ何もしない）
import { showTerm } from "./prototype.ts";
import { generate, searchPolicy, claudePolicy } from "./claude.ts";
import type { Policy, Usage } from "./claude.ts";
import { TASKS, buildAilex, pyExamples, ailexRun, parseProg } from "./tasks.ts";
import type { Task } from "./tasks.ts";
import { spawnSync } from "node:child_process";
import { writeFileSync, mkdirSync } from "node:fs";

// ───────────────────────── 設定 ─────────────────────────

const MODEL_AILEX = process.env.AILEX_MODEL || process.env.MODEL || "claude-opus-4-8";
const MODEL_PY = process.env.PY_MODEL || process.env.MODEL || "claude-opus-4-8";
const ROUNDS = Number(process.env.ROUNDS || 3);   // 修復ラウンド上限（両サイド共通）
const REPEATS = Number(process.env.REPEATS || 1); // 反復回数（分散把握用）

const PRICING: Record<string, [number, number]> = { // $/1M [入力, 出力]
  "claude-opus-4-8": [5, 25], "claude-opus-4-7": [5, 25], "claude-sonnet-5": [3, 15],
  "claude-haiku-4-5": [1, 5], "claude-fable-5": [10, 50],
};
const costOf = (model: string, u: Usage) => {
  const [i, o] = PRICING[model] || [5, 25];
  return (u.inTok / 1e6) * i + (u.outTok / 1e6) * o;
};

// 参照解（スタンドイン Python サイド。配管検証用。実モデル時は使わない）
const PY_REFS: Record<string, string> = {
  sq: "def sq(x):\n    return x*x",
  normsq: "def normsq(v):\n    return sum(x*x for x in v)",
  cube: "def cube(x):\n    return x*x*x",
  norm: "import math\ndef norm(v):\n    return math.sqrt(sum(x*x for x in v))",
  hypot: "import math\ndef hypot(a, b):\n    return math.sqrt(a*a + b*b)",
  max: "def max(a, b):\n    return a if a >= b else b",
  min: "def min(a, b):\n    return b if a >= b else a",
  relu: "def relu(x):\n    return x if x >= 0 else 0",
  abs: "def abs(x):\n    return x if x >= 0 else -x",
  sign: "def sign(x):\n    return 1 if x >= 0 else -1",
};

// ───────────────────────── Ailex サイド ─────────────────────────

interface SideResult { pass1: boolean; passK: boolean; rounds: number; term: string; errKinds: string[] }

async function runAilex(task: Task, policy: Policy): Promise<SideResult> {
  const prog = parseProg(buildAilex(task));
  const fn0 = prog.fns[0];
  let pass1 = false, lastTerm = "", lastHid = false, hint: string | undefined;
  const tried: string[] = [];
  for (let r = 1; r <= ROUNDS; r++) {
    const done = await generate(prog, fn0, policy, true, hint); // API エラーはここで throw（握りつぶさない）
    lastTerm = showTerm(done.body);
    const okPub = ailexRun(prog, done, task.publicT);
    const okHid = ailexRun(prog, done, task.hiddenT);
    if (r === 1) pass1 = okHid;
    if (okPub) return { pass1, passK: okHid, rounds: r, term: lastTerm, errKinds: [] };
    lastHid = okHid; tried.push(lastTerm);
    hint = `これらは公開例に不合格: ${tried.join(" / ")}`;
  }
  return { pass1, passK: lastHid, rounds: ROUNDS, term: lastTerm, errKinds: [] };
}

// ───────────────────────── Python サイド ─────────────────────────

function stripFences(s: string): string {
  s = s.trim();
  const m = s.match(/^```[a-zA-Z]*\s*\n([\s\S]*?)\n```$/);
  if (m) return m[1];
  return s.replace(/^```[a-zA-Z]*\s*\n?/, "").replace(/\n?```$/, "");
}

// 返り値 kind: ok | wrong | runtime | syntax
function execPythonTests(fname: string, code: string, tests: [Val[], number][]): { ok: boolean; msg: string; kind: string } {
  const harness = `
${code}

def __run():
    for _a, _e in ${JSON.stringify(tests)}:
        try:
            _g = ${fname}(*_a)
        except Exception as _ex:
            return "RUNTIME " + type(_ex).__name__ + ": " + str(_ex)
        if abs(_g - _e) > 1e-9:
            return "WRONG " + repr(_a) + " got " + repr(_g) + " want " + repr(_e)
    return "PASS"
print(__run())
`;
  const r = spawnSync("python3", ["-c", harness], { timeout: 5000, encoding: "utf8" });
  if (r.error) return { ok: false, msg: `timeout/exec: ${(r.error as any).code ?? r.error.message}`, kind: "runtime" };
  const out = (r.stdout || "").trim();
  if (out.startsWith("PASS")) return { ok: true, msg: "PASS", kind: "ok" };
  if (out.startsWith("WRONG")) return { ok: false, msg: out, kind: "wrong" };
  if (out.startsWith("RUNTIME")) return { ok: false, msg: out, kind: "runtime" };
  return { ok: false, msg: (r.stderr || out || "出力なし").trim().split("\n").slice(-3).join(" "), kind: "syntax" }; // コンパイル/構文エラー等
}

type PyGen = (prompt: string, task: Task) => Promise<string>;

function opusPython(client: any, usage: Usage, model: string): PyGen {
  return async (prompt) => {
    const tool = {
      name: "submit_code", description: "Python の関数定義を提出する。", strict: true,
      input_schema: { type: "object", properties: { code: { type: "string" } }, required: ["code"], additionalProperties: false },
    };
    const res = await client.messages.create({
      model, max_tokens: 2048, thinking: { type: "disabled" },
      tools: [tool], tool_choice: { type: "tool", name: "submit_code" },
      messages: [{ role: "user", content: prompt }],
    });
    usage.inTok += res.usage?.input_tokens ?? 0; usage.outTok += res.usage?.output_tokens ?? 0;
    const call = res.content.find((b: any) => b.type === "tool_use");
    return stripFences(call?.input?.code ?? "");
  };
}

async function runPython(task: Task, gen: PyGen): Promise<SideResult> {
  const base = [
    "Python で次の関数を実装してください。標準ライブラリの import は可。",
    `シグネチャ: def ${task.fname}(...)`,
    `仕様: ${task.pySpec}`,
    `満たすべき例:\n${pyExamples(task)}`,
    "完全な関数定義を code に入れて submit_code で提出してください。",
  ].join("\n");
  let pass1 = false, lastHid = false, lastCode = ""; const errKinds: string[] = [];
  let lastErr = "";
  for (let r = 1; r <= ROUNDS; r++) {
    const prompt = r === 1 ? base : `${base}\n\n前回の実装:\n${lastCode}\n実行結果: ${lastErr}\nこれを修正した完全な関数定義を提出してください。`;
    const code = await gen(prompt, task); // API エラーはここで throw
    const pub = execPythonTests(task.fname, code, task.publicT);
    const hid = execPythonTests(task.fname, code, task.hiddenT);
    if (r === 1) pass1 = hid.ok;
    if (pub.ok) return { pass1, passK: hid.ok, rounds: r, term: "(python)", errKinds };
    lastCode = code; lastErr = pub.msg; lastHid = hid.ok; errKinds.push(pub.kind);
  }
  return { pass1, passK: lastHid, rounds: ROUNDS, term: "(python)", errKinds };
}

// ───────────────────────── 起動スモーク（APIエラーを先に検出）─────────────────────────

async function smoke(client: any): Promise<void> {
  // Ailex 側の形（choose_next: strict enum + 強制 tool_choice）
  const r1 = await client.messages.create({
    model: MODEL_AILEX, max_tokens: 256, thinking: { type: "disabled" },
    tools: [{ name: "choose_next", description: "選ぶ", strict: true, input_schema: { type: "object", properties: { choice: { type: "string", enum: ["a", "b"] } }, required: ["choice"], additionalProperties: false } }],
    tool_choice: { type: "tool", name: "choose_next" },
    messages: [{ role: "user", content: "a か b を1つ選んでください。" }],
  });
  if (!r1.content.find((b: any) => b.type === "tool_use")) throw new Error("smoke(choose_next): tool_use が返らない");
  // Python 側の形（submit_code: strict string）
  const r2 = await client.messages.create({
    model: MODEL_PY, max_tokens: 256, thinking: { type: "disabled" },
    tools: [{ name: "submit_code", description: "提出", strict: true, input_schema: { type: "object", properties: { code: { type: "string" } }, required: ["code"], additionalProperties: false } }],
    tool_choice: { type: "tool", name: "submit_code" },
    messages: [{ role: "user", content: "def f(): return 1 を提出してください。" }],
  });
  if (!r2.content.find((b: any) => b.type === "tool_use")) throw new Error("smoke(submit_code): tool_use が返らない");
}

// ───────────────────────── main ─────────────────────────

async function main() {
  let ailexPolicy: Policy;
  let pyGen: PyGen;
  let driver: string;
  let real = false;
  const aUse: Usage = { inTok: 0, outTok: 0 };
  const pUse: Usage = { inTok: 0, outTok: 0 };
  let client: any = null;

  try {
    if (!process.env.ANTHROPIC_API_KEY) throw new Error("ANTHROPIC_API_KEY 未設定");
    const mod: any = await import("@anthropic-ai/sdk");
    client = new mod.default();
    ailexPolicy = claudePolicy(client, aUse, MODEL_AILEX);
    pyGen = opusPython(client, pUse, MODEL_PY);
    real = true;
    driver = `実モデル（Ailex=${MODEL_AILEX} / Python=${MODEL_PY}）`;
  } catch (e: any) {
    ailexPolicy = searchPolicy;
    pyGen = async (_p, task) => PY_REFS[task.name] ?? "";
    driver = `スタンドイン（実モデル不可: ${e.message}）— 数値は無意味、配管検証のみ`;
  }

  console.log("════════════════════════════════════════════════════════════════════");
  console.log(" Ailex 比較実験（測定版）");
  console.log(`  駆動: ${driver}`);
  console.log(`  ROUNDS=${ROUNDS}  REPEATS=${REPEATS}  タスク数=${TASKS.length}`);
  console.log("════════════════════════════════════════════════════════════════════");

  if (real) {
    try { await smoke(client); console.log("  スモーク: OK（strict enum + 強制 tool_choice が両サイドで通る）\n"); }
    catch (e: any) {
      console.error("\n[中止] 起動スモーク失敗: " + e.message);
      if (String(e.message).includes("authentication")) {
        console.error("  → 認証エラー。ANTHROPIC_API_KEY（または ailex/.env）の鍵を確認してください。");
      } else {
        console.error("  → API のリクエスト形が通っていません。strict + tool_choice の非互換の可能性。");
        console.error("    対処: strict を外す / output_config.format(json_schema) に切替 / モデルを確認。");
      }
      console.error("    （このエラーを『タスク失敗』に化けさせないため、ここで停止します）");
      process.exit(1);
    }
  }

  const log: any = { startedAt: new Date().toISOString(), driver, models: { ailex: MODEL_AILEX, python: MODEL_PY }, rounds: ROUNDS, repeats: REPEATS, runs: [] };
  // 集計
  let aP1 = 0, aPK = 0, pP1 = 0, pPK = 0, aRounds = 0, pRounds = 0, N = 0;
  const pyErr: Record<string, number> = { wrong: 0, runtime: 0, syntax: 0 };
  // タスク別集計（REPEATS>1 の分散把握用）
  const perTask = new Map<string, { aP1: number; aPK: number; pP1: number; pPK: number }>();
  for (const t of TASKS) perTask.set(t.name, { aP1: 0, aPK: 0, pP1: 0, pPK: 0 });

  for (let rep = 1; rep <= REPEATS; rep++) {
    for (const task of TASKS) {
      const a = await runAilex(task, ailexPolicy);
      const p = await runPython(task, pyGen);
      N++;
      aP1 += a.pass1 ? 1 : 0; aPK += a.passK ? 1 : 0; aRounds += a.rounds;
      pP1 += p.pass1 ? 1 : 0; pPK += p.passK ? 1 : 0; pRounds += p.rounds;
      for (const k of p.errKinds) pyErr[k] = (pyErr[k] ?? 0) + 1;
      const pt = perTask.get(task.name)!;
      pt.aP1 += a.pass1 ? 1 : 0; pt.aPK += a.passK ? 1 : 0; pt.pP1 += p.pass1 ? 1 : 0; pt.pPK += p.passK ? 1 : 0;
      log.runs.push({ rep, task: task.name, ailex: a, python: { ...p, term: undefined } });
      if (REPEATS === 1) {
        console.log(`● ${task.name}`);
        console.log(`   Ailex : pass@1=${a.pass1 ? "✓" : "✗"} pass@k=${a.passK ? "✓" : "✗"} rounds=${a.rounds}  → ${a.term}`);
        console.log(`   Python: pass@1=${p.pass1 ? "✓" : "✗"} pass@k=${p.passK ? "✓" : "✗"} rounds=${p.rounds}  err=[${p.errKinds.join(",")}]`);
      }
    }
  }

  const pct = (x: number) => `${x}/${N} (${(100 * x / N).toFixed(0)}%)`;
  const aCost = costOf(MODEL_AILEX, aUse), pCost = costOf(MODEL_PY, pUse);
  log.summary = { N, ailex: { pass1: aP1, passK: aPK, meanRounds: aRounds / N, usage: aUse, cost: aCost }, python: { pass1: pP1, passK: pPK, meanRounds: pRounds / N, usage: pUse, cost: pCost, errorKinds: pyErr } };

  console.log("\n──────────────────────────── 集計 ────────────────────────────");
  console.log(`  runs = ${N}（${TASKS.length} タスク × ${REPEATS} 反復）`);
  if (REPEATS > 1) {
    console.log(`  タスク別 pass@1（${REPEATS}反復中の成功数）:`);
    console.log(`    ${"task".padEnd(8)}  Ailex  Python`);
    for (const [name, s] of perTask)
      console.log(`    ${name.padEnd(8)}  ${String(s.aP1).padStart(2)}/${REPEATS}   ${String(s.pP1).padStart(2)}/${REPEATS}`);
    log.summary_perTask = Object.fromEntries(perTask);
  }
  console.log(`  pass@1     Ailex ${pct(aP1)}   Python ${pct(pP1)}`);
  console.log(`  pass@k     Ailex ${pct(aPK)}   Python ${pct(pPK)}`);
  console.log(`  平均rounds Ailex ${(aRounds / N).toFixed(2)}   Python ${(pRounds / N).toFixed(2)}`);
  console.log(`  トークン   Ailex in=${aUse.inTok} out=${aUse.outTok}   Python in=${pUse.inTok} out=${pUse.outTok}`);
  console.log(`  コスト($)  Ailex ${aCost.toFixed(5)}(${MODEL_AILEX})   Python ${pCost.toFixed(5)}(${MODEL_PY})`);
  console.log(`  Python修復の内訳（マスクが消すもの）: 誤答=${pyErr.wrong} 実行時=${pyErr.runtime} 構文=${pyErr.syntax}`);
  console.log("──────────────────────────────────────────────────────────────");
  console.log("注: Ailex は型/構文エラーで修復を消費しない（構造的に不可）。上の Python 内訳がその差。");
  console.log("    公開例で修復・隠しテストで採点（テストリーク無し）。数値は駆動が実モデルのときのみ有意。");

  try {
    mkdirSync("ailex/logs", { recursive: true });
    const fn = `ailex/logs/compare-${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
    writeFileSync(fn, JSON.stringify(log, null, 2));
    console.log(`\n  ログ: ${fn}`);
  } catch (e: any) { console.log(`  （ログ保存スキップ: ${e.message}）`); }
}

main().catch((e) => { console.error("\n[実行エラー] " + (e?.stack || e?.message || e)); process.exit(1); });
