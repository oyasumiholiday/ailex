// Ailex — 最小プロトタイプ
//
// 仕様書 Ailex.md の中核主張を実際に走らせて確かめるための縦割り実装。
//   L1 パーサ → 双方向型検査（ホール対応）→ 構造化フィードバック → eg 実例の評価 → 修復ループ
//
// 実行: node ailex/prototype.ts   (Node 24 の型ストリップで .ts を直接実行)
//
// 検証したい主張:
//   §2 単調型付け可能性 …… ホールは常に well-typed に打ち切れる
//   §5 検証の構造化     …… 検証器の応答が英文でなく L0 ノード帰属の構造化データ
//   §6 セマンティクス   …… eg 評価の実行時観測も同じ構造化形で返る
//   §1 L2 投影          …… 同じ L0 から Python 風テキストを決定的にレンダリング

// ───────────────────────── 型（L0 の型項）─────────────────────────

type Ty =
  | { k: "base"; name: "Int" | "Float" | "Bool" }
  | { k: "vec"; elem: Ty }
  | { k: "fun"; params: Ty[]; ret: Ty };

const tFloat: Ty = { k: "base", name: "Float" };
const tInt: Ty = { k: "base", name: "Int" };
const tBool: Ty = { k: "base", name: "Bool" };

function tyEq(a: Ty, b: Ty): boolean {
  if (a.k !== b.k) return false;
  if (a.k === "base" && b.k === "base") return a.name === b.name;
  if (a.k === "vec" && b.k === "vec") return tyEq(a.elem, b.elem);
  if (a.k === "fun" && b.k === "fun")
    return (
      a.params.length === b.params.length &&
      a.params.every((p, i) => tyEq(p, (b as { params: Ty[] }).params[i])) &&
      tyEq(a.ret, b.ret)
    );
  return false;
}

function showTy(t: Ty): string {
  if (t.k === "base") return t.name;
  if (t.k === "vec") return `Vec ${showTy(t.elem)}`;
  return `(${t.params.map(showTy).join(", ")}) -> ${showTy(t.ret)}`;
}

// ───────────────────────── 項（L0 のノード。id が帰属先）─────────────────────────

type Term =
  | { k: "int"; v: number; id: number }
  | { k: "float"; v: number; id: number }
  | { k: "bool"; v: boolean; id: number }
  | { k: "var"; name: string; id: number }
  | { k: "list"; elems: Term[]; id: number }
  | { k: "app"; head: string; args: Term[]; id: number }
  | { k: "if"; cond: Term; then: Term; els: Term; id: number }
  | { k: "hole"; name: string; id: number };

interface Sig { name: string; ty: Ty }
interface Eg { call: Term; expect: Term }
interface Fn {
  name: string;
  params: { name: string; ty: Ty }[];
  ret: Ty;
  ensures: Term | null;
  egs: Eg[];
  bodyTy: Ty;
  body: Term;
}
interface Program { sigs: Sig[]; fns: Fn[] }

// ───────────────────────── トークナイザ ─────────────────────────

interface Tok { t: string; v: string }

function lex(src: string): Tok[] {
  const toks: Tok[] = [];
  let i = 0;
  const two = ["->", ">="];
  const one = "()[],:=?";
  while (i < src.length) {
    const c = src[i];
    if (c === " " || c === "\n" || c === "\t" || c === "\r") { i++; continue; }
    if (src.startsWith("--", i)) { while (i < src.length && src[i] !== "\n") i++; continue; }
    const t2 = src.slice(i, i + 2);
    if (two.includes(t2)) { toks.push({ t: t2, v: t2 }); i += 2; continue; }
    if (one.includes(c)) { toks.push({ t: c, v: c }); i++; continue; }
    if (/[0-9]/.test(c) || (c === "-" && /[0-9]/.test(src[i + 1]))) {
      let j = c === "-" ? i + 1 : i;
      while (j < src.length && /[0-9.]/.test(src[j])) j++;
      const v = src.slice(i, j);
      toks.push({ t: v.includes(".") ? "float" : "int", v });
      i = j;
      continue;
    }
    if (/[a-zA-Z_]/.test(c)) {
      let j = i;
      while (j < src.length && /[a-zA-Z0-9_]/.test(src[j])) j++;
      toks.push({ t: "ident", v: src.slice(i, j) });
      i = j;
      continue;
    }
    throw new Error(`字句エラー: 予期しない文字 '${c}' @${i}`);
  }
  toks.push({ t: "eof", v: "" });
  return toks;
}

// ───────────────────────── パーサ ─────────────────────────

const KEYWORDS = new Set(["group", "end", "sig", "fn", "ensures", "eg", "body", "true", "false", "if"]);

class Parser {
  toks: Tok[];
  p = 0;
  nextId = 1;
  constructor(toks: Tok[]) { this.toks = toks; }

  peek(): Tok { return this.toks[this.p]; }
  next(): Tok { return this.toks[this.p++]; }
  eat(t: string): Tok {
    const tok = this.next();
    if (tok.t !== t) throw new Error(`構文エラー: '${t}' を期待したが '${tok.v || tok.t}' が来た`);
    return tok;
  }
  id(): number { return this.nextId++; }

  parseProgram(): Program {
    const sigs: Sig[] = [];
    const fns: Fn[] = [];
    while (this.peek().t !== "eof") {
      if (this.peek().v === "group") { sigs.push(...this.parseGroup()); }
      else if (this.peek().v === "fn") { fns.push(this.parseFn()); }
      else throw new Error(`構文エラー: group か fn を期待 (got '${this.peek().v}')`);
    }
    return { sigs, fns };
  }

  parseGroup(): Sig[] {
    this.eat("ident"); // group
    this.eat("ident"); // group 名
    const sigs: Sig[] = [];
    while (this.peek().v !== "end") {
      this.eat("ident"); // sig
      const name = this.eat("ident").v;
      this.eat(":");
      sigs.push({ name, ty: this.parseType() });
    }
    this.eat("ident"); // end
    this.eat("ident"); // group
    return sigs;
  }

  parseType(): Ty {
    if (this.peek().t === "(") {
      this.eat("(");
      const params: Ty[] = [];
      if (this.peek().t !== ")") {
        params.push(this.parseType());
        while (this.peek().t === ",") { this.eat(","); params.push(this.parseType()); }
      }
      this.eat(")");
      this.eat("->");
      return { k: "fun", params, ret: this.parseType() };
    }
    const name = this.eat("ident").v;
    if (name === "Vec") return { k: "vec", elem: this.parseType() };
    if (name === "Int" || name === "Float" || name === "Bool") return { k: "base", name };
    throw new Error(`型エラー: 未知の型 '${name}'`);
  }

  parseFn(): Fn {
    this.eat("ident"); // fn
    const name = this.eat("ident").v;
    this.eat("(");
    const params: { name: string; ty: Ty }[] = [];
    if (this.peek().t !== ")") {
      const pn = this.eat("ident").v; this.eat(":");
      params.push({ name: pn, ty: this.parseType() });
      while (this.peek().t === ",") {
        this.eat(",");
        const n = this.eat("ident").v; this.eat(":");
        params.push({ name: n, ty: this.parseType() });
      }
    }
    this.eat(")");
    this.eat("->");
    const ret = this.parseType();

    let ensures: Term | null = null;
    const egs: Eg[] = [];
    while (this.peek().v === "ensures" || this.peek().v === "eg") {
      if (this.next().v === "ensures") { ensures = this.parseExpr(); }
      else { const call = this.parseExpr(); this.eat("="); egs.push({ call, expect: this.parseExpr() }); }
    }
    this.eat("ident"); // body
    const bodyTy = this.parseType();
    const body = this.parseExpr();
    this.eat("ident"); // end
    this.eat("ident"); // fn 名
    return { name, params, ret, ensures, egs, bodyTy, body };
  }

  // 式: 比較 (>=) が最下位、その上に適用/アトム
  parseExpr(): Term {
    let left = this.parseApp();
    if (this.peek().t === ">=") {
      this.eat(">=");
      const right = this.parseApp();
      return { k: "app", head: ">=", args: [left, right], id: this.id() };
    }
    return left;
  }

  parseApp(): Term {
    const a = this.parseAtom();
    if (a.k === "var" && this.peek().t === "(") {
      this.eat("(");
      const args: Term[] = [];
      if (this.peek().t !== ")") {
        args.push(this.parseExpr());
        while (this.peek().t === ",") { this.eat(","); args.push(this.parseExpr()); }
      }
      this.eat(")");
      return { k: "app", head: a.name, args, id: this.id() };
    }
    return a;
  }

  parseAtom(): Term {
    const tok = this.peek();
    if (tok.t === "float") { this.next(); return { k: "float", v: parseFloat(tok.v), id: this.id() }; }
    if (tok.t === "int") { this.next(); return { k: "int", v: parseInt(tok.v, 10), id: this.id() }; }
    if (tok.v === "true") { this.next(); return { k: "bool", v: true, id: this.id() }; }
    if (tok.v === "false") { this.next(); return { k: "bool", v: false, id: this.id() }; }
    if (tok.v === "if") {
      this.next(); this.eat("(");
      const cond = this.parseExpr(); this.eat(",");
      const then = this.parseExpr(); this.eat(",");
      const els = this.parseExpr(); this.eat(")");
      return { k: "if", cond, then, els, id: this.id() };
    }
    if (tok.t === "?") { this.next(); return { k: "hole", name: this.eat("ident").v, id: this.id() }; }
    if (tok.t === "[") {
      this.next();
      const elems: Term[] = [];
      if (this.peek().t !== "]") {
        elems.push(this.parseExpr());
        while (this.peek().t === ",") { this.eat(","); elems.push(this.parseExpr()); }
      }
      this.eat("]");
      return { k: "list", elems, id: this.id() };
    }
    if (tok.t === "(") { this.next(); const e = this.parseExpr(); this.eat(")"); return e; }
    if (tok.t === "ident" && !KEYWORDS.has(tok.v)) { this.next(); return { k: "var", name: tok.v, id: this.id() }; }
    throw new Error(`構文エラー: 式を期待したが '${tok.v || tok.t}' が来た`);
  }
}

// ───────────────────────── 双方向型検査 ─────────────────────────

type Ctx = Map<string, Ty>;

// ビルトイン（訓練データ不要。仕様と検証器に最初から居る）
const BUILTINS: Sig[] = [
  { name: "dot", ty: { k: "fun", params: [{ k: "vec", elem: tFloat }, { k: "vec", elem: tFloat }], ret: tFloat } },
  { name: "sqrt", ty: { k: "fun", params: [tFloat], ret: tFloat } },
  { name: ">=", ty: { k: "fun", params: [tFloat, tFloat], ret: tBool } },
];

interface HoleInfo { name: string; nodeId: number; expected: Ty; scope: { name: string; ty: Ty }[]; obligations: string[] }
interface TypeError { nodeId: number; expected: Ty; actual: Ty; msg: string }

class Checker {
  globals: Ctx = new Map();
  holes: HoleInfo[] = [];
  errors: TypeError[] = [];
  obligations: string[];

  constructor(prog: Program, current: Fn) {
    for (const s of [...BUILTINS, ...prog.sigs]) this.globals.set(s.name, s.ty);
    for (const f of prog.fns) this.globals.set(f.name, { k: "fun", params: f.params.map((p) => p.ty), ret: f.ret });
    this.obligations = [
      ...(current.ensures ? [showTerm(current.ensures)] : []),
      ...current.egs.map((e) => `${showTerm(e.call)} = ${showTerm(e.expect)}`),
    ];
  }

  lookup(ctx: Ctx, name: string): Ty | undefined { return ctx.get(name) ?? this.globals.get(name); }

  // check: 期待型が既知の位置。ホールはここで構造化フィードバックに化ける（§2④）
  check(term: Term, expected: Ty, ctx: Ctx): void {
    if (term.k === "hole") {
      const scope = [...ctx.entries()].map(([name, ty]) => ({ name, ty }));
      for (const [name, ty] of this.globals) if (ty.k === "fun") scope.push({ name, ty });
      this.holes.push({ name: term.name, nodeId: term.id, expected, scope, obligations: this.obligations });
      return;
    }
    // if は多相なので合成でなく検査規則で扱う：条件は Bool、両枝は期待型
    if (term.k === "if") {
      this.check(term.cond, tBool, ctx);
      this.check(term.then, expected, ctx);
      this.check(term.els, expected, ctx);
      return;
    }
    const actual = this.synth(term, ctx);
    if (actual && !tyEq(actual, expected)) {
      this.errors.push({ nodeId: term.id, expected, actual, msg: "型不一致" });
    }
  }

  // synth: 型を合成できる位置（適用の頭部・リテラル・変数）
  synth(term: Term, ctx: Ctx): Ty | null {
    switch (term.k) {
      case "int": return tInt;
      case "float": return tFloat;
      case "bool": return tBool;
      case "hole": {
        this.holes.push({ name: term.name, nodeId: term.id, expected: { k: "base", name: "Float" }, scope: [], obligations: this.obligations });
        return null;
      }
      case "var": {
        const ty = this.lookup(ctx, term.name);
        if (!ty) { this.errors.push({ nodeId: term.id, expected: tFloat, actual: tFloat, msg: `未束縛変数 '${term.name}'` }); return null; }
        return ty;
      }
      case "list": {
        if (term.elems.length === 0) return { k: "vec", elem: tFloat };
        const elemTy = this.synth(term.elems[0], ctx) ?? tFloat;
        for (const e of term.elems) this.check(e, elemTy, ctx);
        return { k: "vec", elem: elemTy };
      }
      case "app": {
        const fty = this.lookup(ctx, term.head);
        if (!fty || fty.k !== "fun") { this.errors.push({ nodeId: term.id, expected: tFloat, actual: tFloat, msg: `関数でない '${term.head}'` }); return null; }
        term.args.forEach((a, i) => this.check(a, fty.params[i], ctx));
        return fty.ret;
      }
      case "if": {
        this.check(term.cond, tBool, ctx);
        const t = this.synth(term.then, ctx);
        if (t) this.check(term.els, t, ctx);
        return t;
      }
    }
  }
}

function checkFn(prog: Program, fn: Fn): Checker {
  const ck = new Checker(prog, fn);
  const ctx: Ctx = new Map(fn.params.map((p) => [p.name, p.ty]));
  ck.check(fn.body, fn.bodyTy, ctx);
  return ck;
}

// ───────────────────────── 評価器（eg 実例を実際に走らせる）─────────────────────────

type Val = number | boolean | number[];

interface RuntimeObs { nodeId: number; event: string; detail: string }

// タスク固有ビルトインのレジストリ（compare.ts などが add/mul 等を登録する）。
// 型側はプログラムの sig 宣言で拾われる。ここは実行時の実装だけ。
const extraBuiltins = new Map<string, (args: Val[]) => Val>();

function evalTerm(term: Term, env: Map<string, Val>, obs: RuntimeObs[], fns: Map<string, Fn>): Val {
  switch (term.k) {
    case "int": return term.v;
    case "float": return term.v;
    case "bool": return term.v;
    case "var": {
      const v = env.get(term.name);
      if (v === undefined) throw new Error(`評価: 未束縛 '${term.name}'`);
      return v;
    }
    case "list": return term.elems.map((e) => evalTerm(e, env, obs, fns) as number);
    case "if": return evalTerm(term.cond, env, obs, fns) ? evalTerm(term.then, env, obs, fns) : evalTerm(term.els, env, obs, fns);
    case "hole": throw new Error("評価: ホールは評価できない");
    case "app": {
      const args = term.args.map((a) => evalTerm(a, env, obs, fns));
      switch (term.head) {
        case "dot": {
          const a = args[0] as number[], b = args[1] as number[];
          return a.reduce((s, x, i) => s + x * b[i], 0);
        }
        case "sqrt": {
          const x = args[0] as number;
          const r = Math.sqrt(x);
          // §6(c): 静的に締め出せない実行時観測を L0 ノードに帰属して構造化
          if (Number.isNaN(r)) obs.push({ nodeId: term.id, event: "domain", detail: `sqrt(${x}) = NaN（負の入力）` });
          return r;
        }
        case ">=": return (args[0] as number) >= (args[1] as number);
        default: {
          // タスク固有ビルトイン → ユーザ定義関数、の順で解決
          const xb = extraBuiltins.get(term.head);
          if (xb) return xb(args);
          // ユーザ定義関数: 本体を引数束縛のもとで評価
          const fn = fns.get(term.head);
          if (!fn) throw new Error(`評価: 未知の関数 '${term.head}'`);
          const local = new Map<string, Val>(fn.params.map((p, i) => [p.name, args[i]]));
          return evalTerm(fn.body, local, obs, fns);
        }
      }
    }
  }
}

// ───────────────────────── 表示 / L2 投影 ─────────────────────────

function showTerm(t: Term): string {
  switch (t.k) {
    case "int": return String(t.v);
    case "float": return t.v.toFixed(1);
    case "bool": return String(t.v);
    case "var": return t.name;
    case "hole": return `?${t.name}`;
    case "list": return `[${t.elems.map(showTerm).join(", ")}]`;
    case "app":
      if (t.head === ">=") return `${showTerm(t.args[0])} >= ${showTerm(t.args[1])}`;
      return `${t.head}(${t.args.map(showTerm).join(", ")})`;
    case "if": return `if(${showTerm(t.cond)}, ${showTerm(t.then)}, ${showTerm(t.els)})`;
  }
}

// L2 投影: 同じ L0 から Python 風テキストを決定的にレンダリング（§1）
function projectPython(fn: Fn): string {
  const pyTy = (t: Ty): string => t.k === "base" ? t.name.toLowerCase() : t.k === "vec" ? `Vec[${pyTy(t.elem)}]` : "Callable";
  const params = fn.params.map((p) => `${p.name}: ${pyTy(p.ty)}`).join(", ");
  const pyExpr = (t: Term): string =>
    t.k === "if" ? `(${pyExpr(t.then)} if ${pyExpr(t.cond)} else ${pyExpr(t.els)})`
    : t.k === "app" && t.head === ">=" ? `(${pyExpr(t.args[0])} >= ${pyExpr(t.args[1])})`
    : t.k === "app" ? `${t.head}(${t.args.map(pyExpr).join(", ")})`
    : t.k === "float" ? t.v.toString()
    : showTerm(t);
  return `def ${fn.name}(${params}) -> ${pyTy(fn.ret)}:\n    return ${pyExpr(fn.body)}`;
}

// ───────────────────────── 検証器の応答を印字 ─────────────────────────

function reportFeedback(ck: Checker): boolean {
  let clean = true;
  for (const e of ck.errors) {
    clean = false;
    console.log("  ✗ 型検査 → 構造化応答:");
    console.log(`      { node: #${e.nodeId}, error: "${e.msg}", expected: ${showTy(e.expected)}, actual: ${showTy(e.actual)} }`);
  }
  for (const h of ck.holes) {
    clean = false;
    console.log("  ● ホール → 構造化応答:");
    console.log(`      { hole: ${h.name}`);
    console.log(`        node: #${h.nodeId}`);
    console.log(`        expected: ${showTy(h.expected)}`);
    console.log(`        scope: [ ${h.scope.map((s) => `${s.name}: ${showTy(s.ty)}`).join("\n                 ")} ]`);
    console.log(`        obligations: [ ${h.obligations.join("\n                       ")} ] }`);
  }
  return clean;
}

// eg 実例と ensures を実際に走らせ、義務の達成を構造化で返す（§5, §6）
function runObligations(fn: Fn, fns: Map<string, Fn>): boolean {
  let ok = true;
  const obs: RuntimeObs[] = [];
  for (const eg of fn.egs) {
    const got = evalTerm(eg.call, new Map(), obs, fns);
    const want = evalTerm(eg.expect, new Map(), obs, fns);
    const pass = got === want;
    ok = ok && pass;
    console.log(`      ${pass ? "✓" : "✗"} eg  ${showTerm(eg.call)} = ${showTerm(eg.expect)}   （実測 ${got}）`);
    if (fn.ensures) {
      // ret を eg の実測結果に束縛して ensures を評価
      const env = new Map<string, Val>([["ret", got]]);
      const ens = evalTerm(fn.ensures, env, obs, fns);
      console.log(`         ${ens ? "✓" : "✗"} ensures ${showTerm(fn.ensures)}   （ret=${got}）`);
      ok = ok && ens === true;
    }
  }
  for (const o of obs) {
    ok = false;
    console.log(`      ⚠ 実行時観測 → 構造化応答: { node: #${o.nodeId}, event: "${o.event}", detail: "${o.detail}" }`);
  }
  return ok;
}

// ───────────────────────── 修復ループの実演 ─────────────────────────

// パッチ: 対象 fn 内の指定ホールを、フラグメントをパースした項で置換（§4 の簡略版）
function fillHole(fn: Fn, holeName: string, fragment: string): Fn {
  const p = new Parser(lex(fragment));
  p.nextId = 1000; // 差し込みノードは別 id 空間
  const replacement = p.parseExpr();
  const subst = (t: Term): Term => {
    if (t.k === "hole" && t.name === holeName) return replacement;
    if (t.k === "app") return { ...t, args: t.args.map(subst) };
    if (t.k === "list") return { ...t, elems: t.elems.map(subst) };
    return t;
  };
  return { ...fn, body: subst(fn.body) };
}

function typecheckStep(prog: Program, fn: Fn): boolean {
  const withFn: Program = { ...prog, fns: prog.fns.map((f) => (f.name === fn.name ? fn : f)) };
  const ck = checkFn(withFn, fn);
  return reportFeedback(ck);
}

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
  let fn = prog.fns[0];

  console.log("════════════════════════════════════════════════════════════");
  console.log(" Ailex 修復ループ実演 —— fn norm（ベクトルのノルム）");
  console.log("════════════════════════════════════════════════════════════\n");

  console.log("① 生成器はホール付きの well-typed な部分プログラムを出力（§2④）");
  console.log("     body Float = ?h1\n");
  console.log("② 検証器が構造化フィードバックを返す（§5）");
  typecheckStep(prog, fn);

  console.log("\n③ AI が誤った穴埋めを提案: ?h1 := v   （v は Vec Float、期待は Float）");
  const wrong = fillHole(fn, "h1", "v");
  const wrongClean = typecheckStep(prog, wrong);
  console.log(`     → ${wrongClean ? "通過" : "型検査が構造化データで棄却（constrained decoding ならそもそも出力不能）"}`);

  console.log("\n④ AI が正しい穴埋めを提案: ?h1 := sqrt(dot(v, v))");
  fn = fillHole(fn, "h1", "sqrt(dot(v, v))");
  const rightClean = typecheckStep(prog, fn);
  console.log(`     → 型検査 ${rightClean ? "クリーン（ホールも型エラーも無し）" : "失敗"}`);

  console.log("\n⑤ 義務（eg 実例 + ensures）を実際に評価して達成を確認（§5, §6）");
  const fnRegistry = new Map<string, Fn>(prog.fns.map((f) => (f.name === fn.name ? [f.name, fn] : [f.name, f])));
  const verified = runObligations(fn, fnRegistry);

  console.log(`\n⑥ 修復ループ: ${rightClean && verified ? "閉じた ✅（型クリーン かつ 全義務達成）" : "未達 ❌"}`);

  console.log("\n────────────────────────────────────────────────────────────");
  console.log(" 同じ L0 の L2 投影（人間が読む面・読み取り専用・§1）");
  console.log("────────────────────────────────────────────────────────────");
  console.log(projectPython(fn));

  console.log("\n（参考）§6 実行時観測の実演: sqrt に負値が渡る別プログラム");
  const bad = new Parser(lex(`
fn bad (x : Float) -> Float
  eg bad(-1.0) = 0.0
body Float
  sqrt(x)
end bad
`)).parseProgram();
  runObligations(bad.fns[0], new Map(bad.fns.map((f) => [f.name, f])));
}

// 直接実行時のみデモを走らせる（synth.ts から import しても副作用を出さない）
if (process.argv[1] && process.argv[1].endsWith("prototype.ts")) main();

export {
  tFloat, tInt, tBool, tyEq, showTy, lex, Parser, BUILTINS,
  evalTerm, showTerm, Checker, checkFn, extraBuiltins,
};
export type { Ty, Term, Sig, Eg, Fn, Program, Val, RuntimeObs };
