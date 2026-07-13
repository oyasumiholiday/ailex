// Ailex — タスク台と共有ヘルパ（compare.ts / q1.ts が共有）
//
// 公開例(publicT)＝プロンプトに見せる＆修復フィードバックに使う。
// 隠しテスト(hiddenT)＝採点のみ・絶対に見せない（テストリーク防止）。

import { lex, Parser, evalTerm, extraBuiltins } from "./prototype.ts";
import type { Term, Fn, Program, Val, RuntimeObs } from "./prototype.ts";

// タスク固有ビルトインの実装（型側は各タスクの sig 宣言が担う）
extraBuiltins.set("add", (a) => (a[0] as number) + (a[1] as number));
extraBuiltins.set("mul", (a) => (a[0] as number) * (a[1] as number));

export interface Task {
  name: string; fname: string;
  groupSigs: string;   // group ... end group（未使用なら ""）
  fnSig: string;       // "fn norm (v : Vec Float) -> Float"
  ensures?: string;    // "ret >= 0.0"
  bodyTy: string;      // "Float"
  pySpec: string;      // 自然言語仕様
  publicT: [Val[], number][]; // 公開例
  hiddenT: [Val[], number][]; // 隠しテスト
}

const GMUL = "group n\n  sig mul : (Float, Float) -> Float\nend group";
const GADDMUL = "group n\n  sig add : (Float, Float) -> Float\n  sig mul : (Float, Float) -> Float\nend group";

export const TASKS: Task[] = [
  { name: "sq", fname: "sq", groupSigs: GMUL, fnSig: "fn sq (x : Float) -> Float", bodyTy: "Float",
    pySpec: "x*x を返す。", publicT: [[[2], 4], [[3], 9]], hiddenT: [[[5], 25], [[-4], 16], [[0.5], 0.25]] },
  { name: "normsq", fname: "normsq", groupSigs: "", fnSig: "fn normsq (v : Vec Float) -> Float", bodyTy: "Float",
    pySpec: "ベクトル v（数値のリスト）の二乗ノルム（各要素の二乗和）を返す。",
    publicT: [[[[1, 2, 2]], 9], [[[3, 4]], 25]], hiddenT: [[[[0, 5]], 25], [[[2, 3, 6]], 49], [[[1, 1, 1, 1]], 4]] },
  { name: "cube", fname: "cube", groupSigs: GMUL, fnSig: "fn cube (x : Float) -> Float", bodyTy: "Float",
    pySpec: "x*x*x を返す。", publicT: [[[2], 8], [[3], 27]], hiddenT: [[[-2], -8], [[1], 1], [[4], 64]] },
  { name: "norm", fname: "norm", groupSigs: "", fnSig: "fn norm (v : Vec Float) -> Float", ensures: "ret >= 0.0", bodyTy: "Float",
    pySpec: "ベクトル v のユークリッドノルム sqrt(各要素の二乗和) を返す。",
    publicT: [[[[3, 4]], 5], [[[6, 8]], 10]], hiddenT: [[[[5, 12]], 13], [[[9, 12]], 15], [[[8, 15]], 17]] },
  { name: "hypot", fname: "hypot", groupSigs: GADDMUL, fnSig: "fn hypot (a : Float, b : Float) -> Float", bodyTy: "Float",
    pySpec: "sqrt(a*a + b*b) を返す（直角三角形の斜辺）。",
    publicT: [[[3, 4], 5], [[0, 3], 3]], hiddenT: [[[6, 8], 10], [[5, 12], 13], [[8, 15], 17]] },
  { name: "max", fname: "max", groupSigs: "", fnSig: "fn max (a : Float, b : Float) -> Float", bodyTy: "Float",
    pySpec: "a と b の大きい方を返す。", publicT: [[[3, 4], 4], [[9, 2], 9]], hiddenT: [[[5, 5], 5], [[-1, -4], -1], [[2, 8], 8]] },
  { name: "min", fname: "min", groupSigs: "", fnSig: "fn min (a : Float, b : Float) -> Float", bodyTy: "Float",
    pySpec: "a と b の小さい方を返す。", publicT: [[[3, 4], 3], [[9, 2], 2]], hiddenT: [[[5, 5], 5], [[-1, -4], -4], [[2, 8], 2]] },
  { name: "relu", fname: "relu", groupSigs: "", fnSig: "fn relu (x : Float) -> Float", bodyTy: "Float",
    pySpec: "x が 0 以上なら x、そうでなければ 0 を返す。", publicT: [[[3], 3], [[-0.5], 0]], hiddenT: [[[5], 5], [[-3], 0], [[0.5], 0.5], [[0], 0]] },
  { name: "abs", fname: "abs", groupSigs: GMUL, fnSig: "fn abs (x : Float) -> Float", bodyTy: "Float",
    pySpec: "x の絶対値を返す。", publicT: [[[4], 4], [[-3], 3]], hiddenT: [[[-0.5], 0.5], [[0.5], 0.5], [[2], 2], [[0], 0]] },
  { name: "sign", fname: "sign", groupSigs: "", fnSig: "fn sign (x : Float) -> Float", bodyTy: "Float",
    pySpec: "x が 0 以上なら 1、そうでなければ -1 を返す。", publicT: [[[5], 1], [[-0.2], -1]], hiddenT: [[[0], 1], [[7], 1], [[-3], -1]] },
];

// ───────────────────────── 整形 ─────────────────────────

export const fmtNum = (n: number) => (Number.isInteger(n) ? n.toFixed(1) : String(n));
export const fmtVal = (v: Val): string => Array.isArray(v) ? `[${v.map(fmtNum).join(", ")}]` : fmtNum(v as number);
export const egLine = (fname: string, [args, exp]: [Val[], number]) =>
  `  eg ${fname}(${args.map(fmtVal).join(", ")}) = ${fmtNum(exp)}`;

// L1 ソースを組み立てる。body を渡すとホールの代わりに差し込む（q1 の全項生成用）。
export const buildAilex = (t: Task, body = "?h1") =>
  `${t.groupSigs}\n${t.fnSig}\n${t.ensures ? "  ensures " + t.ensures + "\n" : ""}${t.publicT.map((e) => egLine(t.fname, e)).join("\n")}\nbody ${t.bodyTy}\n  ${body}\nend ${t.fname}`;

export const pyLit = (v: Val): string => Array.isArray(v) ? `[${v.map((x) => String(x)).join(", ")}]` : String(v);
export const pyExamples = (t: Task) => t.publicT.map(([a, e]) => `${t.fname}(${a.map(pyLit).join(", ")}) == ${e}`).join("\n");
export const ailexExamples = (t: Task) => t.publicT.map((e) => egLine(t.fname, e).trim()).join("\n"); // "eg f(..) = .." の列

// ───────────────────────── Ailex 評価 ─────────────────────────

let vid = 20000;
export function valToTerm(v: Val): Term {
  if (Array.isArray(v)) return { k: "list", elems: v.map((n) => ({ k: "float", v: n as number, id: vid++ })), id: vid++ };
  if (typeof v === "number") return { k: "float", v, id: vid++ };
  return { k: "bool", v: v as boolean, id: vid++ };
}

// fn を tests で評価し、最初の不一致を返す（全合格なら null）。
export function ailexFirstFail(prog: Program, fn: Fn, tests: [Val[], number][]): { input: Val[]; expected: number; actual: string } | null {
  const fns = new Map<string, Fn>(prog.fns.map((f) => (f.name === fn.name ? [f.name, fn] : [f.name, f])));
  for (const [args, expected] of tests) {
    const call: Term = { k: "app", head: fn.name, args: args.map(valToTerm), id: vid++ };
    let got: number | string;
    try {
      const g = evalTerm(call, new Map(), [] as RuntimeObs[], fns);
      got = typeof g === "number" ? g : String(g);
      if (typeof g === "number" && Math.abs(g - expected) <= 1e-9) continue;
    } catch (e: any) { got = `error: ${e.message}`; }
    return { input: args, expected, actual: String(got) };
  }
  return null;
}

export const ailexRun = (prog: Program, fn: Fn, tests: [Val[], number][]): boolean => ailexFirstFail(prog, fn, tests) === null;

export const parseProg = (src: string): Program => new Parser(lex(src)).parseProgram();
