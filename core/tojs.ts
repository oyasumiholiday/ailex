// Ailex v0.1 — L0(AST) → JavaScript lowering（SPEC §11）
// 「中間言語」たる所以: 同じ L0 から host へ落として本物に実行する。v0.1 ターゲットは JS。
// 検証: conformance の golden データで「インタプリタと JS 実行が一致」を担保（Go の C→Go 変換と同じ手法）。
//
// 注: Int/Float の区別は実行時に消えるため、`/` の意味論は型検査が刻む bin.nt に依存する。
//     したがって toJs は check() の後（bin.nt が付いた後）に呼ぶこと。

import type { Program, Expr } from "./lang.ts";
import { parseExpr } from "./lang.ts";

const PRELUDE = `const $rt = {
  sqrt: Math.sqrt,
  toFloat: (n) => n,
  toInt: (x) => Math.trunc(x),
  dot: (a, b) => a.reduce((s, x, i) => s + x * b[i], 0),
  sum: (a) => a.reduce((s, x) => s + x, 0),
  strlen: (s) => s.length,
  concat: (a, b) => a + b,
  length: (a) => a.length,
  head: (a) => { if (a.length === 0) throw new Error("head: empty"); return a[0]; },
  tail: (a) => a.slice(1),
  get: (a, i) => { if (i < 0 || i >= a.length) throw new Error("get: oob " + i); return a[i]; },
  append: (a, x) => [...a, x],
  map: (a, f) => Array.isArray(a) ? a.map((x) => f(x)) : (a.has ? { has: true, val: f(a.val) } : { has: false }),
  filter: (a, f) => a.filter((x) => f(x)),
  fold: (a, init, f) => a.reduce((acc, x) => f(acc, x), init),
  split: (s, sep) => s.split(sep),
  join: (a, sep) => a.join(sep),
  contains: (s, t) => s.includes(t),
  substring: (s, i, j) => s.slice(i, j),
  trim: (s) => s.trim(),
  toString: (x) => String(x),
  headOr: (a, d) => (a.length ? a[0] : d),
  getOr: (a, i, d) => (i >= 0 && i < a.length ? a[i] : d),
  some: (x) => ({ has: true, val: x }),
  isSome: (o) => o.has,
  unwrapOr: (o, d) => (o.has ? o.val : d),
  find: (a, f) => { const x = a.find((v) => f(v)); return x === undefined ? { has: false } : { has: true, val: x }; },
  parseInt: (s) => { const t = s.trim(); return /^-?\\d+$/.test(t) ? { has: true, val: Number(t) } : { has: false }; },
  parseFloat: (s) => { const t = s.trim(); const n = Number(t); return t !== "" && Number.isFinite(n) ? { has: true, val: n } : { has: false }; },
  eq: function eq(a, b) { // == の意味論: 構造等価（インタプリタの structEq と一致させる）
    if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => eq(x, b[i]));
    if (a && b && typeof a === "object" && typeof b === "object" && !Array.isArray(a) && !Array.isArray(b)) {
      const ka = Object.keys(a), kb = Object.keys(b);
      return ka.length === kb.length && ka.every((k) => k in b && eq(a[k], b[k]));
    }
    return a === b;
  },
};`;

const POLY = new Set(["length", "get", "head", "tail", "append", "map", "filter", "fold", "toString", "headOr", "getOr", "some", "isSome", "unwrapOr", "find"]);
const STDLIB = new Set(["sqrt", "toFloat", "toInt", "dot", "sum", "strlen", "concat", "split", "join", "contains", "substring", "trim", "parseInt", "parseFloat"]);
const isBuiltin = (n: string) => POLY.has(n) || STDLIB.has(n);

export function exprToJs(e: Expr): string {
  switch (e.k) {
    case "int": return String(e.v);
    case "float": return Number.isInteger(e.v) ? e.v.toFixed(1) : String(e.v);
    case "bool": return String(e.v);
    case "str": return JSON.stringify(e.v);
    case "var": return isBuiltin(e.name) ? `$rt.${e.name}` : e.name; // 組み込みを値として使う場合
    case "list": return `[${e.elems.map(exprToJs).join(", ")}]`;
    case "if": return `(${exprToJs(e.c)} ? ${exprToJs(e.t)} : ${exprToJs(e.e)})`;
    case "let": return `((${e.name}) => ${exprToJs(e.body)})(${exprToJs(e.val)})`;
    case "lam": return `((${e.params.map((p) => p.name).join(", ")}) => ${exprToJs(e.body)})`;
    case "rec": return `({${e.fields.map((f) => `${f.name}: ${exprToJs(f.val)}`).join(", ")}})`;
    case "field": return `${exprToJs(e.obj)}.${e.name}`;
    case "none": return `({has: false})`;
    case "un": return `(${e.op}${exprToJs(e.e)})`;
    case "bin": {
      const l = exprToJs(e.l), r = exprToJs(e.r);
      if (e.op === "/" && e.nt === "Int") return `Math.trunc(${l} / ${r})`;
      if (e.op === "==") return `$rt.eq(${l}, ${r})`;
      if (e.op === "!=") return `(!$rt.eq(${l}, ${r}))`;
      return `(${l} ${e.op} ${r})`;
    }
    case "app": {
      const args = e.args.map(exprToJs).join(", ");
      if (isBuiltin(e.fn)) return `$rt.${e.fn}(${args})`;
      return `${e.fn}(${args})`;
    }
  }
}

// プログラム全体を JS へ。前置 prelude ＋ 各関数を const アロー関数に。
export function toJs(prog: Program): string {
  const defs = prog.fns.map((f) => `const ${f.name} = (${f.params.map((p) => p.name).join(", ")}) => ${exprToJs(f.body)};`);
  return `${PRELUDE}\n${defs.join("\n")}`;
}

// 検証用: プログラム文脈で式文字列を JS 実行し、値を返す。
export function runJs(prog: Program, exprSrc: string): any {
  const body = `${toJs(prog)}\nreturn (${exprToJs(parseExpr(exprSrc))});`;
  return new Function(body)();
}
