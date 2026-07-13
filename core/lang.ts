// Ailex v0.1 コア — reference 実装（tree-walking）
// SPEC.md 準拠。旧 prototype.ts とは別系統（新設計: List[T]・中置演算子・let・stdlib暗黙・診断)。
// この段階(Step 1)の実装範囲: Int/Float/Bool、中置演算子、if、let、関数、契約(eg/ensures)、
//   数値 stdlib(sqrt/toFloat/toInt)。String/List/その他stdlibは後続の機能ステップで追加。
// 診断は SPEC §9 の構造化スキーマ。英文にしない。

// ───────────────────────── 型 ─────────────────────────

export type Ty =
  | { k: "Int" } | { k: "Float" } | { k: "Bool" } | { k: "String" }
  | { k: "List"; elem: Ty }
  | { k: "Option"; elem: Ty }                          // 安全な不在（v0.5）
  | { k: "Rec"; fields: { name: string; ty: Ty }[] }   // 構造的レコード（v0.3）
  | { k: "Fun"; params: Ty[]; ret: Ty };

export const tInt: Ty = { k: "Int" }, tFloat: Ty = { k: "Float" }, tBool: Ty = { k: "Bool" }, tString: Ty = { k: "String" };
export const isNum = (t: Ty) => t.k === "Int" || t.k === "Float";

export function tyEq(a: Ty, b: Ty): boolean {
  if (a.k !== b.k) return false;
  if (a.k === "List" && b.k === "List") return tyEq(a.elem, b.elem);
  if (a.k === "Option" && b.k === "Option") return tyEq(a.elem, b.elem);
  if (a.k === "Rec" && b.k === "Rec") { // 構造的・順序不問
    if (a.fields.length !== b.fields.length) return false;
    return a.fields.every((f) => { const g = (b as any).fields.find((x: any) => x.name === f.name); return g && tyEq(f.ty, g.ty); });
  }
  if (a.k === "Fun" && b.k === "Fun") return a.params.length === (b as any).params.length
    && a.params.every((p, i) => tyEq(p, (b as any).params[i])) && tyEq(a.ret, (b as any).ret);
  return a.k === b.k; // 基本型
}
export function showTy(t: Ty): string {
  switch (t.k) {
    case "List": return `List[${showTy(t.elem)}]`;
    case "Option": return `Option[${showTy(t.elem)}]`;
    case "Rec": return `{${[...t.fields].sort((x, y) => x.name.localeCompare(y.name)).map((f) => `${f.name} : ${showTy(f.ty)}`).join(", ")}}`; // 正規形＝名前順
    case "Fun": return `(${t.params.map(showTy).join(", ")}) -> ${showTy(t.ret)}`;
    default: return t.k;
  }
}

// ───────────────────────── AST ─────────────────────────

export type Expr =
  | { k: "int"; v: number; id: number }
  | { k: "float"; v: number; id: number }
  | { k: "bool"; v: boolean; id: number }
  | { k: "str"; v: string; id: number }
  | { k: "var"; name: string; id: number }
  | { k: "list"; elems: Expr[]; id: number }
  | { k: "if"; c: Expr; t: Expr; e: Expr; id: number }
  | { k: "let"; name: string; ty: Ty; val: Expr; body: Expr; id: number }
  | { k: "app"; fn: string; args: Expr[]; id: number }
  | { k: "rec"; fields: { name: string; val: Expr }[]; id: number }          // レコードリテラル {x = e, ...}（v0.3）
  | { k: "none"; id: number }                                                // Option の不在値（v0.5・check 位置でのみ型が付く）
  | { k: "field"; obj: Expr; name: string; id: number }                      // フィールドアクセス e.name（v0.3）
  | { k: "lam"; params: { name: string; ty?: Ty }[]; body: Expr; id: number } // 無名関数 fn (x) => e。型注釈は任意（check位置で推論・v0.3.2）
  | { k: "bin"; op: string; l: Expr; r: Expr; id: number; nt?: string } // nt: 算術の型注釈(Int/Float)。/ の意味論に使う
  | { k: "un"; op: string; e: Expr; id: number };

export interface Contract { kind: "requires" | "ensures" | "eg"; expr?: Expr; call?: Expr; value?: Expr }
export interface Fn { name: string; params: { name: string; ty: Ty }[]; ret: Ty; contracts: Contract[]; bodyTy: Ty; body: Expr }
export interface Program { fns: Fn[] }

// ───────────────────────── 字句 ─────────────────────────

interface Tok { t: string; v: string }
const KEYWORDS = new Set(["fn", "end", "body", "let", "in", "if", "requires", "ensures", "eg", "true", "false", "Int", "Float", "Bool", "String", "List", "type", "none"]);

export function lex(src: string): Tok[] {
  const toks: Tok[] = []; let i = 0;
  const two = ["=>", "->", ">=", "<=", "==", "!=", "&&", "||"];
  const one = "()[]{},:=+-*/<>!.";
  while (i < src.length) {
    const c = src[i];
    if (c === " " || c === "\t" || c === "\n" || c === "\r") { i++; continue; }
    if (src.startsWith("--", i)) { while (i < src.length && src[i] !== "\n") i++; continue; }
    if (c === '"') { // 文字列
      let j = i + 1, s = "";
      while (j < src.length && src[j] !== '"') {
        if (src[j] === "\\") { const n = src[j + 1]; s += n === "n" ? "\n" : n === "t" ? "\t" : n; j += 2; }
        else { s += src[j]; j++; }
      }
      if (j >= src.length) throw new ParseErr(`未終端の文字列`);
      toks.push({ t: "str", v: s }); i = j + 1; continue;
    }
    const t2 = src.slice(i, i + 2);
    if (two.includes(t2)) { toks.push({ t: t2, v: t2 }); i += 2; continue; }
    if (one.includes(c)) { toks.push({ t: c, v: c }); i++; continue; }
    if (/[0-9]/.test(c)) {
      let j = i; while (j < src.length && /[0-9.]/.test(src[j])) j++;
      const v = src.slice(i, j); toks.push({ t: v.includes(".") ? "float" : "int", v }); i = j; continue;
    }
    if (/[A-Za-z_]/.test(c)) {
      let j = i; while (j < src.length && /[A-Za-z0-9_]/.test(src[j])) j++;
      toks.push({ t: "ident", v: src.slice(i, j) }); i = j; continue;
    }
    throw new ParseErr(`予期しない文字 '${c}'`);
  }
  toks.push({ t: "eof", v: "" });
  return toks;
}

// ───────────────────────── パーサ（再帰下降＋優先順位）─────────────────────────

export class ParseErr extends Error {}

class Parser {
  p = 0; nid = 1; toks: Tok[];
  aliases = new Map<string, Ty>(); // 型エイリアス（透明・宣言は使用に先行）
  constructor(toks: Tok[]) { this.toks = toks; }
  peek() { return this.toks[this.p]; }
  next() { return this.toks[this.p++]; }
  eat(t: string) { const k = this.next(); if (k.t !== t) throw new ParseErr(`'${t}' を期待したが '${k.v || k.t}'`); return k; }
  id() { return this.nid++; }

  program(): Program {
    const fns: Fn[] = [];
    while (this.peek().t !== "eof") {
      if (this.peek().v === "type") { // type Name = Ty
        this.next(); const name = this.eat("ident").v; this.eat("=");
        this.aliases.set(name, this.type());
      } else fns.push(this.fn());
    }
    return { fns };
  }

  fn(): Fn {
    this.eat("ident"); // fn
    const name = this.eat("ident").v;
    this.eat("("); const params: { name: string; ty: Ty }[] = [];
    if (this.peek().t !== ")") { do { const n = this.eat("ident").v; this.eat(":"); params.push({ name: n, ty: this.type() }); } while (this.peek().t === "," && this.next()); }
    this.eat(")"); this.eat("->"); const ret = this.type();
    const contracts: Contract[] = [];
    while (["requires", "ensures", "eg"].includes(this.peek().v)) {
      const k = this.next().v;
      if (k === "eg") { const call = this.expr(); this.eat("="); const value = this.expr(); contracts.push({ kind: "eg", call, value }); }
      else contracts.push({ kind: k as any, expr: this.expr() });
    }
    this.eat("ident"); // body
    const bodyTy = this.type(); const body = this.expr();
    this.eat("ident"); // end
    this.eat("ident"); // name
    return { name, params, ret, contracts, bodyTy, body };
  }

  type(): Ty {
    const t = this.peek();
    if (t.t === "(") { this.next(); const ps: Ty[] = []; if (this.peek().t !== ")") { do { ps.push(this.type()); } while (this.peek().t === "," && this.next()); } this.eat(")"); this.eat("->"); return { k: "Fun", params: ps, ret: this.type() }; }
    if (t.t === "{") { // レコード型 {x : T, y : U}
      this.next(); const fields: { name: string; ty: Ty }[] = [];
      if (this.peek().t !== "}") { do { const n = this.eat("ident").v; this.eat(":"); fields.push({ name: n, ty: this.type() }); } while (this.peek().t === "," && this.next()); }
      this.eat("}"); return { k: "Rec", fields };
    }
    const n = this.eat("ident").v;
    if (n === "List") { this.eat("["); const e = this.type(); this.eat("]"); return { k: "List", elem: e }; }
    if (n === "Option") { this.eat("["); const e = this.type(); this.eat("]"); return { k: "Option", elem: e }; }
    if (n === "Int" || n === "Float" || n === "Bool" || n === "String") return { k: n } as Ty;
    const alias = this.aliases.get(n);
    if (alias) return alias; // 透明（展開）
    throw new ParseErr(`未知の型 '${n}'（type ${n} = ... の宣言は使用より前に置く）`);
  }

  // expr = let | or   （if は atom で処理）
  expr(): Expr {
    if (this.peek().v === "let") {
      this.next(); const name = this.eat("ident").v; this.eat(":"); const ty = this.type();
      this.eat("="); const val = this.expr(); this.eat("ident" /* in */);
      const body = this.expr(); return { k: "let", name, ty, val, body, id: this.id() };
    }
    return this.or();
  }
  or(): Expr { let l = this.and(); while (this.peek().t === "||") { this.next(); l = { k: "bin", op: "||", l, r: this.and(), id: this.id() }; } return l; }
  and(): Expr { let l = this.cmp(); while (this.peek().t === "&&") { this.next(); l = { k: "bin", op: "&&", l, r: this.cmp(), id: this.id() }; } return l; }
  cmp(): Expr { const l = this.add(); const o = this.peek().t; if (["==", "!=", ">=", "<=", ">", "<"].includes(o)) { this.next(); return { k: "bin", op: o, l, r: this.add(), id: this.id() }; } return l; }
  add(): Expr { let l = this.mul(); while (this.peek().t === "+" || this.peek().t === "-") { const o = this.next().t; l = { k: "bin", op: o, l, r: this.mul(), id: this.id() }; } return l; }
  mul(): Expr { let l = this.unary(); while (this.peek().t === "*" || this.peek().t === "/") { const o = this.next().t; l = { k: "bin", op: o, l, r: this.unary(), id: this.id() }; } return l; }
  unary(): Expr { if (this.peek().t === "-" || this.peek().t === "!") { const o = this.next().t; return { k: "un", op: o, e: this.unary(), id: this.id() }; } return this.appl(); }
  appl(): Expr {
    let a = this.atom();
    if (a.k === "var" && this.peek().t === "(") { this.next(); const args: Expr[] = []; if (this.peek().t !== ")") { do { args.push(this.expr()); } while (this.peek().t === "," && this.next()); } this.eat(")"); a = { k: "app", fn: a.name, args, id: this.id() }; }
    while (this.peek().t === ".") { this.next(); a = { k: "field", obj: a, name: this.eat("ident").v, id: this.id() }; } // 後置 .field 連鎖
    return a;
  }
  atom(): Expr {
    const t = this.peek();
    if (t.t === "int") { this.next(); return { k: "int", v: parseInt(t.v, 10), id: this.id() }; }
    if (t.t === "float") { this.next(); return { k: "float", v: parseFloat(t.v), id: this.id() }; }
    if (t.t === "str") { this.next(); return { k: "str", v: t.v, id: this.id() }; }
    if (t.v === "true") { this.next(); return { k: "bool", v: true, id: this.id() }; }
    if (t.v === "false") { this.next(); return { k: "bool", v: false, id: this.id() }; }
    if (t.v === "if") { this.next(); this.eat("("); const c = this.expr(); this.eat(","); const th = this.expr(); this.eat(","); const e = this.expr(); this.eat(")"); return { k: "if", c, t: th, e, id: this.id() }; }
    if (t.v === "fn") { // 無名関数 fn (x, ...) => e （型注釈は任意: fn (x : T) => e も可）
      this.next(); this.eat("("); const params: { name: string; ty?: Ty }[] = [];
      if (this.peek().t !== ")") {
        do {
          const n = this.eat("ident").v;
          let ty: Ty | undefined;
          if (this.peek().t === ":") { this.next(); ty = this.type(); }
          params.push({ name: n, ty });
        } while (this.peek().t === "," && this.next());
      }
      this.eat(")"); this.eat("=>"); return { k: "lam", params, body: this.expr(), id: this.id() };
    }
    if (t.t === "[") { this.next(); const elems: Expr[] = []; if (this.peek().t !== "]") { do { elems.push(this.expr()); } while (this.peek().t === "," && this.next()); } this.eat("]"); return { k: "list", elems, id: this.id() }; }
    if (t.t === "ident" && t.v === "none") { this.next(); return { k: "none", id: this.id() }; }
    if (t.t === "{") { // レコードリテラル {x = e, y = e}
      this.next(); const fields: { name: string; val: Expr }[] = [];
      if (this.peek().t !== "}") { do { const n = this.eat("ident").v; this.eat("="); fields.push({ name: n, val: this.expr() }); } while (this.peek().t === "," && this.next()); }
      this.eat("}"); return { k: "rec", fields, id: this.id() };
    }
    if (t.t === "(") { this.next(); const e = this.expr(); this.eat(")"); return e; }
    if (t.t === "ident" && !KEYWORDS.has(t.v)) { this.next(); return { k: "var", name: t.v, id: this.id() }; }
    throw new ParseErr(`式を期待したが '${t.v || t.t}'`);
  }
}

export function parseProgram(src: string): Program { return new Parser(lex(src)).program(); }
export function parseExpr(src: string): Expr { const p = new Parser(lex(src)); const e = p.expr(); return e; }

// ───────────────────────── 標準ライブラリ ─────────────────────────

export type VFun = (args: Val[]) => Val;                 // 実行時の関数値（第一級・v0.2）
type Val = number | boolean | string | VFun | Val[] | { [field: string]: Val }; // レコードは素のオブジェクト（v0.3）

// 言語の == / != の意味論: 構造等価（数値は厳密・リスト/レコードは深い比較・関数は参照）
export function structEq(a: Val, b: Val): boolean {
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => structEq(x, b[i]));
  if (a && b && typeof a === "object" && typeof b === "object" && !Array.isArray(a) && !Array.isArray(b)) {
    const ka = Object.keys(a), kb = Object.keys(b);
    return ka.length === kb.length && ka.every((k) => k in (b as any) && structEq((a as any)[k], (b as any)[k]));
  }
  return a === b;
}

// 値の深い等価（契約 eg の判定用。数値は許容誤差 1e-9、リスト/レコードは構造で比較）
export function valEq(a: Val, b: Val): boolean {
  if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) <= 1e-9;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => valEq(x, b[i]));
  if (a && b && typeof a === "object" && typeof b === "object" && !Array.isArray(a) && !Array.isArray(b)) {
    const ka = Object.keys(a), kb = Object.keys(b);
    return ka.length === kb.length && ka.every((k) => k in (b as any) && valEq((a as any)[k], (b as any)[k]));
  }
  return a === b;
}
interface Builtin { ty: Ty; run: (a: Val[]) => Val }
const listFloat: Ty = { k: "List", elem: tFloat };
export const STDLIB: Record<string, Builtin> = {
  // 数値
  sqrt: { ty: { k: "Fun", params: [tFloat], ret: tFloat }, run: (a) => Math.sqrt(a[0] as number) },
  toFloat: { ty: { k: "Fun", params: [tInt], ret: tFloat }, run: (a) => a[0] as number },
  toInt: { ty: { k: "Fun", params: [tFloat], ret: tInt }, run: (a) => Math.trunc(a[0] as number) },
  // リスト（具体型）
  dot: { ty: { k: "Fun", params: [listFloat, listFloat], ret: tFloat }, run: (a) => (a[0] as number[]).reduce((s, x, i) => s + x * (a[1] as number[])[i], 0) },
  sum: { ty: { k: "Fun", params: [listFloat], ret: tFloat }, run: (a) => (a[0] as number[]).reduce((s, x) => s + x, 0) },
  // 文字列
  strlen: { ty: { k: "Fun", params: [tString], ret: tInt }, run: (a) => (a[0] as string).length },
  concat: { ty: { k: "Fun", params: [tString, tString], ret: tString }, run: (a) => (a[0] as string) + (a[1] as string) },
  split: { ty: { k: "Fun", params: [tString, tString], ret: { k: "List", elem: tString } }, run: (a) => (a[0] as string).split(a[1] as string) },
  join: { ty: { k: "Fun", params: [{ k: "List", elem: tString }, tString], ret: tString }, run: (a) => (a[0] as string[]).join(a[1] as string) },
  contains: { ty: { k: "Fun", params: [tString, tString], ret: tBool }, run: (a) => (a[0] as string).includes(a[1] as string) },
  substring: { ty: { k: "Fun", params: [tString, tInt, tInt], ret: tString }, run: (a) => (a[0] as string).slice(a[1] as number, a[2] as number) },
  trim: { ty: { k: "Fun", params: [tString], ret: tString }, run: (a) => (a[0] as string).trim() },
  // v0.5: 失敗しうる変換は Option を返す
  parseInt: { ty: { k: "Fun", params: [tString], ret: { k: "Option", elem: tInt } }, run: (a) => { const s = (a[0] as string).trim(); return /^-?\d+$/.test(s) ? { has: true, val: Number(s) } : { has: false }; } },
  parseFloat: { ty: { k: "Fun", params: [tString], ret: { k: "Option", elem: tFloat } }, run: (a) => { const s = (a[0] as string).trim(); const n = Number(s); return s !== "" && Number.isFinite(n) ? { has: true, val: n } : { has: false }; } },
};

// 多相な組み込み（Go の len/append 方式・型システムに乗せず特別扱い）。map/filter/fold は高階(v0.2)。
// toString/headOr/getOr は v0.4。some/isSome/unwrapOr/find は v0.5（Option）。
const POLY = new Set(["length", "get", "head", "tail", "append", "map", "filter", "fold", "toString", "headOr", "getOr", "some", "isSome", "unwrapOr", "find"]);

// 実行時の組み込み（VFun）。関数値として渡せるよう名前→VFun で持つ。
const RT: Record<string, VFun> = {
  sqrt: (a) => Math.sqrt(a[0] as number),
  toFloat: (a) => a[0] as number,
  toInt: (a) => Math.trunc(a[0] as number),
  dot: (a) => (a[0] as number[]).reduce((s, x, i) => s + x * (a[1] as number[])[i], 0),
  sum: (a) => (a[0] as number[]).reduce((s, x) => s + x, 0),
  strlen: (a) => (a[0] as string).length,
  concat: (a) => (a[0] as string) + (a[1] as string),
  length: (a) => (a[0] as Val[]).length,
  head: (a) => { const x = a[0] as Val[]; if (!x.length) throw new RuntimeErr("head: 空リスト"); return x[0]; },
  tail: (a) => (a[0] as Val[]).slice(1),
  get: (a) => { const x = a[0] as Val[], i = a[1] as number; if (i < 0 || i >= x.length) throw new RuntimeErr(`get: 範囲外 ${i}`); return x[i]; },
  append: (a) => [...(a[0] as Val[]), a[1]],
  map: (a) => { // List か Option（型検査済みなので 'has' での実行時判別は安全）
    const x = a[0] as any, f = a[1] as VFun;
    if (Array.isArray(x)) return x.map((v: Val) => f([v]));
    return x.has ? { has: true, val: f([x.val]) } : { has: false };
  },
  filter: (a) => (a[0] as Val[]).filter((x) => (a[1] as VFun)([x]) as boolean),
  fold: (a) => (a[0] as Val[]).reduce((acc, x) => (a[2] as VFun)([acc, x]), a[1]),
  // v0.4: 文字列と安全な既定値つき取得
  split: (a) => (a[0] as string).split(a[1] as string),
  join: (a) => (a[0] as string[]).join(a[1] as string),
  contains: (a) => (a[0] as string).includes(a[1] as string),
  substring: (a) => (a[0] as string).slice(a[1] as number, a[2] as number),
  trim: (a) => (a[0] as string).trim(),
  toString: (a) => String(a[0]),
  headOr: (a) => { const x = a[0] as Val[]; return x.length ? x[0] : a[1]; },
  getOr: (a) => { const x = a[0] as Val[], i = a[1] as number; return i >= 0 && i < x.length ? x[i] : a[2]; },
  // v0.5: Option（実行時表現は {has: true, val} / {has: false}）
  some: (a) => ({ has: true, val: a[0] }),
  isSome: (a) => (a[0] as { has: boolean }).has,
  unwrapOr: (a) => { const o = a[0] as { has: boolean; val?: Val }; return o.has ? o.val! : a[1]; },
  find: (a) => { const x = (a[0] as Val[]).find((v) => (a[1] as VFun)([v]) as boolean); return x === undefined ? { has: false } : { has: true, val: x }; },
  parseInt: (a) => { const s = (a[0] as string).trim(); return /^-?\d+$/.test(s) ? { has: true, val: Number(s) } : { has: false }; },
  parseFloat: (a) => { const s = (a[0] as string).trim(); const n = Number(s); return s !== "" && Number.isFinite(n) ? { has: true, val: n } : { has: false }; },
};

// ───────────────────────── 診断（SPEC §9）─────────────────────────

export type Diag =
  | { code: "parse"; detail: string }
  | { code: "unbound"; name: string; scope: { name: string; type: string }[] }
  | { code: "not_a_function"; name: string; scope: { name: string; type: string }[] }
  | { code: "type_mismatch"; at: number; expected: string; actual: string; scope: { name: string; type: string }[] }
  | { code: "higher_order_unsupported"; at: number; detail: string } // v0.1: 関数値は未サポート(健全性のため型検査で禁止・v0.2で正式化)
  | { code: "unknown_field"; at: number; name: string; fields: { name: string; type: string }[] } // レコードに無いフィールド（使える一覧を開示）
  | { code: "contract"; kind: string; call: string; expected: string; actual: string };

// 型が関数型を含むか（v0.1 は関数値を値位置に許さない）
function hasFun(t: Ty): boolean { return t.k === "Fun" || ((t.k === "List" || t.k === "Option") && hasFun(t.elem)); }

// ───────────────────────── 型検査（双方向・SPEC §5）─────────────────────────

type Ctx = Map<string, Ty>;
class Checker {
  errors: Diag[] = [];
  globals: Ctx = new Map();
  constructor(prog: Program) {
    for (const [n, b] of Object.entries(STDLIB)) this.globals.set(n, b.ty);
    for (const f of prog.fns) this.globals.set(f.name, { k: "Fun", params: f.params.map((p) => p.ty), ret: f.ret });
  }
  scopeOf(ctx: Ctx) { return [...ctx, ...this.globals].map(([name, ty]) => ({ name, type: showTy(ty) })); }
  err(d: Diag) { this.errors.push(d); }

  synth(e: Expr, ctx: Ctx): Ty | null {
    switch (e.k) {
      case "int": return tInt; case "float": return tFloat; case "bool": return tBool; case "str": return tString;
      case "var": {
        const t = ctx.get(e.name) ?? this.globals.get(e.name);
        if (!t) { this.err({ code: "unbound", name: e.name, scope: this.scopeOf(ctx) }); return null; }
        return t;
      }
      case "lam": {
        // synth 位置では引数型を推論できないので注釈必須（check 位置では省略可）
        if (e.params.some((p) => !p.ty)) {
          this.err({ code: "type_mismatch", at: e.id, expected: "型注釈つきラムダ（この位置では引数型を文脈から決められない）", actual: "注釈なしラムダ", scope: this.scopeOf(ctx) });
          return null;
        }
        const c2 = new Map(ctx); for (const p of e.params) c2.set(p.name, p.ty!);
        const r = this.synth(e.body, c2);
        return r ? { k: "Fun", params: e.params.map((p) => p.ty!), ret: r } : null;
      }
      case "none": { // 文脈なしでは型が決まらない
        this.err({ code: "type_mismatch", at: e.id, expected: "Option[T]（let の注釈や if のもう一方の枝など、文脈から型が要る）", actual: "none", scope: this.scopeOf(ctx) });
        return null;
      }
      case "rec": {
        const fields: { name: string; ty: Ty }[] = [];
        for (const f of e.fields) { const t = this.synth(f.val, ctx); if (!t) return null; fields.push({ name: f.name, ty: t }); }
        return { k: "Rec", fields };
      }
      case "field": {
        const t = this.synth(e.obj, ctx);
        if (!t) return null;
        if (t.k !== "Rec") { this.err({ code: "type_mismatch", at: e.id, expected: "{..}(レコード)", actual: showTy(t), scope: this.scopeOf(ctx) }); return null; }
        const f = t.fields.find((x) => x.name === e.name);
        if (!f) { this.err({ code: "unknown_field", at: e.id, name: e.name, fields: t.fields.map((x) => ({ name: x.name, type: showTy(x.ty) })) }); return null; }
        return f.ty;
      }
      case "app": {
        if (POLY.has(e.fn)) return this.synthPoly(e, ctx);
        const ft = ctx.get(e.fn) ?? this.globals.get(e.fn);
        if (!ft || ft.k !== "Fun") { this.err({ code: "not_a_function", name: e.fn, scope: this.scopeOf(ctx) }); return null; }
        e.args.forEach((a, i) => ft.params[i] && this.check(a, ft.params[i], ctx));
        return ft.ret;
      }
      case "un": {
        if (e.op === "!") { this.check(e.e, tBool, ctx); return tBool; }
        const t = this.synth(e.e, ctx); if (t && !isNum(t)) this.err({ code: "type_mismatch", at: e.id, expected: "Int|Float", actual: showTy(t), scope: this.scopeOf(ctx) }); return t;
      }
      case "bin": return this.synthBin(e, ctx);
      case "if": case "let": case "list": { // eslint 用: lam は上で処理済
        // これらは本来 check 位置。synth 要求時は then/val から推す（簡易）。
        if (e.k === "if") { this.check(e.c, tBool, ctx); const t = this.synth(e.t, ctx); if (t) this.check(e.e, t, ctx); return t; }
        if (e.k === "let") { const s = e.ty; this.check(e.val, s, ctx); const c2 = new Map(ctx); c2.set(e.name, s); return this.synth(e.body, c2); }
        // list synth
        if (e.elems.length === 0) { this.err({ code: "type_mismatch", at: e.id, expected: "List[?]", actual: "空リスト(型不定)", scope: this.scopeOf(ctx) }); return null; }
        const et = this.synth(e.elems[0], ctx); if (et) e.elems.forEach((x) => this.check(x, et, ctx)); return et ? { k: "List", elem: et } : null;
      }
    }
  }
  // 多相組み込みの型付け（引数のリスト型から要素型を推す）
  synthPoly(e: Expr & { k: "app" }, ctx: Ctx): Ty | null {
    const listArg = (): Ty | null => {
      const t = this.synth(e.args[0], ctx);
      if (t && t.k !== "List") { this.err({ code: "type_mismatch", at: e.id, expected: "List[?]", actual: showTy(t), scope: this.scopeOf(ctx) }); return null; }
      return t;
    };
    switch (e.fn) {
      case "length": { listArg(); return tInt; }
      case "head": { const t = listArg(); return t && t.k === "List" ? t.elem : null; }
      case "tail": { const t = listArg(); return t; }
      case "get": { const t = listArg(); this.check(e.args[1], tInt, ctx); return t && t.k === "List" ? t.elem : null; }
      case "append": { const t = listArg(); if (t && t.k === "List") this.check(e.args[1], t.elem, ctx); return t; }
      case "map": { // (List[T], (T)->U) -> List[U]  /  (Option[T], (T)->U) -> Option[U]（v0.5.2・A3実測: 両モデルが map を Option に使った）
        const t0 = this.synth(e.args[0], ctx); const f = e.args[1];
        if (t0 && t0.k !== "List" && t0.k !== "Option") { this.err({ code: "type_mismatch", at: e.id, expected: "List[?] か Option[?]", actual: showTy(t0), scope: this.scopeOf(ctx) }); return null; }
        const wrap = (u: Ty): Ty => (t0 && t0.k === "Option" ? { k: "Option", elem: u } : { k: "List", elem: u });
        const elem = t0 && (t0.k === "List" || t0.k === "Option") ? t0.elem : null;
        if (elem && f?.k === "lam" && f.params.length === 1) {
          const p = f.params[0];
          if (p.ty && !tyEq(p.ty, elem)) this.err({ code: "type_mismatch", at: e.id, expected: showTy(elem), actual: showTy(p.ty), scope: this.scopeOf(ctx) });
          const c2 = new Map(ctx); c2.set(p.name, p.ty ?? elem);
          const u = this.synth(f.body, c2);
          return u ? wrap(u) : null;
        }
        const ft = this.synth(f, ctx); // 関数名などラムダ以外
        if (!ft) return null;
        if (ft.k !== "Fun" || ft.params.length !== 1) { this.err({ code: "type_mismatch", at: e.id, expected: "(T) -> U", actual: showTy(ft), scope: this.scopeOf(ctx) }); return null; }
        if (elem && !tyEq(ft.params[0], elem)) this.err({ code: "type_mismatch", at: e.id, expected: `(${showTy(elem)}) -> U`, actual: showTy(ft), scope: this.scopeOf(ctx) });
        return wrap(ft.ret);
      }
      case "filter": { // (List[T], (T) -> Bool) -> List[T]。ラムダは check 位置
        const t = listArg(); const f = e.args[1];
        if (t && t.k === "List" && f?.k === "lam" && f.params.length === 1) {
          const p = f.params[0];
          if (p.ty && !tyEq(p.ty, t.elem)) this.err({ code: "type_mismatch", at: e.id, expected: showTy(t.elem), actual: showTy(p.ty), scope: this.scopeOf(ctx) });
          const c2 = new Map(ctx); c2.set(p.name, p.ty ?? t.elem);
          this.check(f.body, tBool, c2);
          return t;
        }
        const ft = this.synth(f, ctx);
        if (t && t.k === "List" && ft && ft.k === "Fun") {
          if (!tyEq(ft.params[0], t.elem) || ft.ret.k !== "Bool") this.err({ code: "type_mismatch", at: e.id, expected: `(${showTy(t.elem)}) -> Bool`, actual: showTy(ft), scope: this.scopeOf(ctx) });
        }
        return t;
      }
      case "fold": { // (List[T], U, (U, T) -> U) -> U。ラムダは check 位置（acc=初期値の型・x=要素型）
        const t = listArg(); const init = this.synth(e.args[1], ctx); const f = e.args[2];
        if (init && t && t.k === "List" && f?.k === "lam" && f.params.length === 2) {
          const [pa, px] = f.params;
          if (pa.ty && !tyEq(pa.ty, init)) this.err({ code: "type_mismatch", at: e.id, expected: showTy(init), actual: showTy(pa.ty), scope: this.scopeOf(ctx) });
          if (px.ty && !tyEq(px.ty, t.elem)) this.err({ code: "type_mismatch", at: e.id, expected: showTy(t.elem), actual: showTy(px.ty), scope: this.scopeOf(ctx) });
          const c2 = new Map(ctx); c2.set(pa.name, pa.ty ?? init); c2.set(px.name, px.ty ?? t.elem);
          this.check(f.body, init, c2);
          return init;
        }
        const ft = this.synth(f, ctx);
        if (init && t && t.k === "List" && ft) {
          if (ft.k !== "Fun" || ft.params.length !== 2 || !tyEq(ft.params[0], init) || !tyEq(ft.params[1], t.elem) || !tyEq(ft.ret, init))
            this.err({ code: "type_mismatch", at: e.id, expected: `(${showTy(init)}, ${showTy(t.elem)}) -> ${showTy(init)}`, actual: showTy(ft), scope: this.scopeOf(ctx) });
        }
        return init;
      }
      case "toString": { // (Int|Float|Bool|String) -> String（関数型は不可）
        const t = this.synth(e.args[0], ctx);
        if (t && hasFun(t)) this.err({ code: "type_mismatch", at: e.id, expected: "Int|Float|Bool|String", actual: showTy(t), scope: this.scopeOf(ctx) });
        return tString;
      }
      case "headOr": { // (List[T], T) -> T（空なら既定値）
        const t = listArg();
        if (t && t.k === "List") { this.check(e.args[1], t.elem, ctx); return t.elem; }
        return null;
      }
      case "getOr": { // (List[T], Int, T) -> T（範囲外なら既定値）
        const t = listArg();
        this.check(e.args[1], tInt, ctx);
        if (t && t.k === "List") { this.check(e.args[2], t.elem, ctx); return t.elem; }
        return null;
      }
      case "some": { // (T) -> Option[T]
        const t = this.synth(e.args[0], ctx);
        return t ? { k: "Option", elem: t } : null;
      }
      case "isSome": { // (Option[T]) -> Bool
        const t = this.synth(e.args[0], ctx);
        if (t && t.k !== "Option") this.err({ code: "type_mismatch", at: e.id, expected: "Option[T]", actual: showTy(t), scope: this.scopeOf(ctx) });
        return tBool;
      }
      case "unwrapOr": { // (Option[T], T) -> T
        const t = this.synth(e.args[0], ctx);
        if (t && t.k !== "Option") { this.err({ code: "type_mismatch", at: e.id, expected: "Option[T]", actual: showTy(t), scope: this.scopeOf(ctx) }); return null; }
        if (t && t.k === "Option") { this.check(e.args[1], t.elem, ctx); return t.elem; }
        return null;
      }
      case "find": { // (List[T], (T) -> Bool) -> Option[T]。ラムダは check 位置（filter と同型）
        const t = listArg(); const f = e.args[1];
        if (t && t.k === "List" && f?.k === "lam" && f.params.length === 1) {
          const p = f.params[0];
          if (p.ty && !tyEq(p.ty, t.elem)) this.err({ code: "type_mismatch", at: e.id, expected: showTy(t.elem), actual: showTy(p.ty), scope: this.scopeOf(ctx) });
          const c2 = new Map(ctx); c2.set(p.name, p.ty ?? t.elem);
          this.check(f.body, tBool, c2);
          return { k: "Option", elem: t.elem };
        }
        const ft = this.synth(f, ctx);
        if (t && t.k === "List" && ft && ft.k === "Fun") {
          if (!tyEq(ft.params[0], t.elem) || ft.ret.k !== "Bool") this.err({ code: "type_mismatch", at: e.id, expected: `(${showTy(t.elem)}) -> Bool`, actual: showTy(ft), scope: this.scopeOf(ctx) });
        }
        return t && t.k === "List" ? { k: "Option", elem: t.elem } : null;
      }
    }
    return null;
  }
  synthBin(e: Expr & { k: "bin" }, ctx: Ctx): Ty | null {
    const { op } = e;
    if (op === "&&" || op === "||") { this.check(e.l, tBool, ctx); this.check(e.r, tBool, ctx); return tBool; }
    if (op === "==" || op === "!=") { const lt = this.synth(e.l, ctx); if (lt) this.check(e.r, lt, ctx); return tBool; }
    if ([">", ">=", "<", "<="].includes(op)) { const lt = this.synth(e.l, ctx); if (lt) { if (!isNum(lt)) this.err({ code: "type_mismatch", at: e.id, expected: "Int|Float", actual: showTy(lt), scope: this.scopeOf(ctx) }); this.check(e.r, lt, ctx); } return tBool; }
    // 算術 + - * /（+ だけは String 連結も可・v0.5.1 dogfood第5R: concat 4重ネストの解消。モデルの事前分布とも一致）
    const lt = this.synth(e.l, ctx);
    if (lt) {
      const strPlus = op === "+" && lt.k === "String";
      if (!isNum(lt) && !strPlus) this.err({ code: "type_mismatch", at: e.id, expected: op === "+" ? "Int|Float|String" : "Int|Float", actual: showTy(lt), scope: this.scopeOf(ctx) });
      this.check(e.r, lt, ctx); e.nt = lt.k as any; // / の意味論用に型を刻む
    }
    return lt;
  }
  check(e: Expr, want: Ty, ctx: Ctx): void {
    if (e.k === "if") { this.check(e.c, tBool, ctx); this.check(e.t, want, ctx); this.check(e.e, want, ctx); return; }
    if (e.k === "none") { // none は check 位置でのみ型が付く（双方向・typed hole と同じ扱い）
      if (want.k !== "Option") this.err({ code: "type_mismatch", at: e.id, expected: showTy(want), actual: "none（Option[T]）", scope: this.scopeOf(ctx) });
      return;
    }
    if (e.k === "list") { // check 位置のリストは要素を期待要素型で検査（空リスト [] もここで型が付く・v0.5.1）
      if (want.k !== "List") { this.err({ code: "type_mismatch", at: e.id, expected: showTy(want), actual: "リスト", scope: this.scopeOf(ctx) }); return; }
      for (const x of e.elems) this.check(x, want.elem, ctx);
      return;
    }
    if (e.k === "app" && e.fn === "fold") { // check 位置の fold: 期待型 → 初期値 → ラムダ引数へ伝播（v0.5.1・dogfood第5R）
      const t0 = this.synth(e.args[0], ctx);
      if (t0 && t0.k !== "List") this.err({ code: "type_mismatch", at: e.id, expected: "List[?]", actual: showTy(t0), scope: this.scopeOf(ctx) });
      this.check(e.args[1], want, ctx); // 初期値（[] や none もここで型が付く）
      const f = e.args[2];
      if (t0 && t0.k === "List" && f?.k === "lam" && f.params.length === 2) {
        const [pa, px] = f.params;
        if (pa.ty && !tyEq(pa.ty, want)) this.err({ code: "type_mismatch", at: e.id, expected: showTy(want), actual: showTy(pa.ty), scope: this.scopeOf(ctx) });
        if (px.ty && !tyEq(px.ty, t0.elem)) this.err({ code: "type_mismatch", at: e.id, expected: showTy(t0.elem), actual: showTy(px.ty), scope: this.scopeOf(ctx) });
        const c2 = new Map(ctx); c2.set(pa.name, pa.ty ?? want); c2.set(px.name, px.ty ?? t0.elem);
        this.check(f.body, want, c2);
        return;
      }
      if (f) this.check(f, { k: "Fun", params: [want, t0 && t0.k === "List" ? t0.elem : want], ret: want }, ctx);
      return;
    }
    if (e.k === "lam") { // check 位置: 引数型は期待型から取る（双方向）。注釈があれば整合を検査
      if (want.k !== "Fun") { this.err({ code: "type_mismatch", at: e.id, expected: showTy(want), actual: "関数", scope: this.scopeOf(ctx) }); return; }
      if (e.params.length !== want.params.length) { this.err({ code: "type_mismatch", at: e.id, expected: showTy(want), actual: `${e.params.length}引数の関数`, scope: this.scopeOf(ctx) }); return; }
      const c2 = new Map(ctx);
      e.params.forEach((p, i) => {
        const w = want.params[i];
        if (p.ty && !tyEq(p.ty, w)) this.err({ code: "type_mismatch", at: e.id, expected: showTy(w), actual: showTy(p.ty), scope: this.scopeOf(ctx) });
        c2.set(p.name, p.ty ?? w);
      });
      this.check(e.body, want.ret, c2); return;
    }
    if (e.k === "rec") {
      if (want.k !== "Rec") { this.err({ code: "type_mismatch", at: e.id, expected: showTy(want), actual: "{..}(レコード)", scope: this.scopeOf(ctx) }); return; }
      const wantNames = new Set(want.fields.map((f) => f.name)), gotNames = new Set(e.fields.map((f) => f.name));
      const missing = want.fields.filter((f) => !gotNames.has(f.name)).map((f) => f.name);
      const extra = e.fields.filter((f) => !wantNames.has(f.name)).map((f) => f.name);
      if (missing.length || extra.length) { this.err({ code: "type_mismatch", at: e.id, expected: showTy(want), actual: `{${[...gotNames].sort().join(", ")}}${missing.length ? ` (不足: ${missing.join(",")})` : ""}${extra.length ? ` (余分: ${extra.join(",")})` : ""}`, scope: this.scopeOf(ctx) }); return; }
      for (const f of e.fields) this.check(f.val, want.fields.find((x) => x.name === f.name)!.ty, ctx);
      return;
    }
    if (e.k === "let") { this.check(e.val, e.ty, ctx); const c2 = new Map(ctx); c2.set(e.name, e.ty); this.check(e.body, want, c2); return; }
    if (e.k === "list") { if (want.k !== "List") { this.err({ code: "type_mismatch", at: e.id, expected: showTy(want), actual: "List[..]", scope: this.scopeOf(ctx) }); return; } e.elems.forEach((x) => this.check(x, want.elem, ctx)); return; }
    const got = this.synth(e, ctx);
    if (got && !tyEq(got, want)) this.err({ code: "type_mismatch", at: e.id, expected: showTy(want), actual: showTy(got), scope: this.scopeOf(ctx) });
  }
  checkFn(f: Fn) {
    const ctx: Ctx = new Map(f.params.map((p) => [p.name, p.ty]));
    if (!tyEq(f.bodyTy, f.ret)) this.err({ code: "type_mismatch", at: f.body.id, expected: showTy(f.ret), actual: showTy(f.bodyTy) + "(body注釈)", scope: this.scopeOf(ctx) });
    this.check(f.body, f.ret, ctx);
    for (const c of f.contracts) {
      if (c.kind === "ensures" && c.expr) { const c2 = new Map(ctx); c2.set("ret", f.ret); this.check(c.expr, tBool, c2); }
      if (c.kind === "requires" && c.expr) this.check(c.expr, tBool, ctx);
      if (c.kind === "eg" && c.call && c.value) { const t = this.synth(c.call, ctx); if (t) this.check(c.value, t, ctx); }
    }
  }
}

export function check(prog: Program): { ok: boolean; errors: Diag[] } {
  const ck = new Checker(prog); for (const f of prog.fns) ck.checkFn(f); return { ok: ck.errors.length === 0, errors: ck.errors };
}

// ───────────────────────── 評価（SPEC §6）─────────────────────────

export class RuntimeErr extends Error {}

// gv: グローバル値環境（名前→VFun。組み込みRT＋ユーザ関数のクロージャ）。関数を第一級値として扱う。
export function evalExpr(e: Expr, env: Map<string, Val>, gv: Map<string, VFun>): Val {
  switch (e.k) {
    case "int": case "float": return e.v; case "bool": return e.v; case "str": return e.v;
    case "var": { const v = env.get(e.name) ?? gv.get(e.name); if (v === undefined) throw new RuntimeErr(`未束縛 '${e.name}'`); return v; }
    case "lam": return (args: Val[]) => { const e2 = new Map(env); e.params.forEach((p, i) => e2.set(p.name, args[i])); return evalExpr(e.body, e2, gv); };
    case "none": return { has: false };
    case "rec": { const o: { [k: string]: Val } = {}; for (const f of e.fields) o[f.name] = evalExpr(f.val, env, gv); return o; }
    case "field": { const o = evalExpr(e.obj, env, gv) as { [k: string]: Val }; return o[e.name]; }
    case "list": return e.elems.map((x) => evalExpr(x, env, gv));
    case "if": return evalExpr(e.c, env, gv) ? evalExpr(e.t, env, gv) : evalExpr(e.e, env, gv);
    case "let": { const v = evalExpr(e.val, env, gv); const e2 = new Map(env); e2.set(e.name, v); return evalExpr(e.body, e2, gv); }
    case "un": { const v = evalExpr(e.e, env, gv); return e.op === "!" ? !(v as boolean) : -(v as number); }
    case "bin": return evalBin(e.op, evalExpr(e.l, env, gv), evalExpr(e.r, env, gv), e);
    case "app": {
      const fv = env.get(e.fn) ?? gv.get(e.fn);
      if (typeof fv !== "function") throw new RuntimeErr(`呼び出せない '${e.fn}'`);
      return (fv as VFun)(e.args.map((a) => evalExpr(a, env, gv)));
    }
  }
}

// プログラムのグローバル値環境を作る（組み込み＋ユーザ関数をクロージャに）
export function buildGV(prog: Program): Map<string, VFun> {
  const gv = new Map<string, VFun>(Object.entries(RT));
  for (const f of prog.fns) gv.set(f.name, (args: Val[]) => {
    const env = new Map<string, Val>(); f.params.forEach((p, i) => env.set(p.name, args[i]));
    return evalExpr(f.body, env, gv);
  });
  return gv;
}
function evalBin(op: string, l: Val, r: Val, e: Expr): Val {
  switch (op) {
    case "+": return (l as any) + (r as any); // Int/Float の加算 or String 連結（型検査済み）
    case "-": return (l as number) - (r as number);
    case "*": return (l as number) * (r as number);
    case "/": { if ((r as number) === 0) throw new RuntimeErr("0 除算"); const q = (l as number) / (r as number); return (e as any).nt === "Int" ? Math.trunc(q) : q; } // 型注釈で Int/Float 除算を決める
    case "&&": return (l as boolean) && (r as boolean); case "||": return (l as boolean) || (r as boolean);
    case "==": return structEq(l, r); case "!=": return !structEq(l, r);
    case ">": return (l as number) > (r as number); case ">=": return (l as number) >= (r as number);
    case "<": return (l as number) < (r as number); case "<=": return (l as number) <= (r as number);
  }
  throw new RuntimeErr(`未知の演算子 ${op}`);
}

// 契約(eg/ensures)を実行して違反を返す（型検査を通った後に呼ぶ）
export function runContracts(prog: Program): Diag[] {
  const gv = buildGV(prog);
  const out: Diag[] = [];
  for (const f of prog.fns) for (const c of f.contracts) {
    if (c.kind !== "eg" || !c.call || !c.value) continue;
    let got: Val, want: Val;
    try { got = evalExpr(c.call, new Map(), gv); want = evalExpr(c.value, new Map(), gv); }
    catch (ex: any) { out.push({ code: "contract", kind: "eg", call: showExpr(c.call), expected: showExpr(c.value), actual: `error: ${ex.message}` }); continue; }
    if (!valEq(got, want)) { out.push({ code: "contract", kind: "eg", call: showExpr(c.call), expected: JSON.stringify(want), actual: JSON.stringify(got) }); continue; }
    // ensures を ret=got で検査
    for (const c2 of f.contracts) if (c2.kind === "ensures" && c2.expr) {
      const env = new Map<string, Val>([["ret", got]]);
      let ens: Val; try { ens = evalExpr(c2.expr, env, gv); } catch { ens = false; }
      if (ens !== true) out.push({ code: "contract", kind: "ensures", call: showExpr(c.call), expected: showExpr(c2.expr), actual: "false" });
    }
  }
  return out;
}

// ───────────────────────── L2 投影（人間向け表示）─────────────────────────

export function showExpr(e: Expr): string {
  switch (e.k) {
    case "int": return String(e.v); case "float": return e.v.toFixed(1); case "bool": return String(e.v); case "str": return JSON.stringify(e.v);
    case "var": return e.name; case "list": return `[${e.elems.map(showExpr).join(", ")}]`;
    case "if": return `if(${showExpr(e.c)}, ${showExpr(e.t)}, ${showExpr(e.e)})`;
    case "let": return `let ${e.name}: ${showTy(e.ty)} = ${showExpr(e.val)} in ${showExpr(e.body)}`;
    case "app": return `${e.fn}(${e.args.map(showExpr).join(", ")})`;
    case "rec": return `{${[...e.fields].sort((x, y) => x.name.localeCompare(y.name)).map((f) => `${f.name} = ${showExpr(f.val)}`).join(", ")}}`; // 正規形＝名前順
    case "field": return `${showExpr(e.obj)}.${e.name}`;
    case "none": return "none";
    case "lam": return `fn (${e.params.map((p) => p.ty ? `${p.name} : ${showTy(p.ty)}` : p.name).join(", ")}) => ${showExpr(e.body)}`;
    case "bin": return `${showExpr(e.l)} ${e.op} ${showExpr(e.r)}`;
    case "un": return `${e.op}${showExpr(e.e)}`;
  }
}

// テスト/CLI 用: プログラム文脈で式文字列を評価
export function evalInProgram(prog: Program, exprSrc: string): Val {
  return evalExpr(parseExpr(exprSrc), new Map(), buildGV(prog));
}

// 多相組み込みの表示用シグネチャ（scope 出力用）
export const POLY_SIGS: Record<string, string> = {
  length: "(List[T]) -> Int", get: "(List[T], Int) -> T", head: "(List[T]) -> T",
  tail: "(List[T]) -> List[T]", append: "(List[T], T) -> List[T]",
  toString: "(Int|Float|Bool|String) -> String", headOr: "(List[T], T) -> T", getOr: "(List[T], Int, T) -> T",
  some: "(T) -> Option[T]", isSome: "(Option[T]) -> Bool", unwrapOr: "(Option[T], T) -> T", find: "(List[T], (T) -> Bool) -> Option[T]",
  map: "(List[T], (T) -> U) -> List[U]", filter: "(List[T], (T) -> Bool) -> List[T]",
  fold: "(List[T], U, (U, T) -> U) -> U",
};

// 正規形プリンタ（L1 canonical form・fmt コマンド用）
export function showProgram(prog: Program): string {
  return prog.fns.map((f) => {
    const params = f.params.map((p) => `${p.name} : ${showTy(p.ty)}`).join(", ");
    const cs = f.contracts.map((c) => c.kind === "eg"
      ? `  eg ${showExpr(c.call!)} = ${showExpr(c.value!)}`
      : `  ${c.kind} ${showExpr(c.expr!)}`).join("\n");
    return `fn ${f.name} (${params}) -> ${showTy(f.ret)}\n${cs ? cs + "\n" : ""}body ${showTy(f.bodyTy)}\n  ${showExpr(f.body)}\nend ${f.name}`;
  }).join("\n\n");
}
