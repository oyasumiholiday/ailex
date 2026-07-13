// core/lang.ts
var tInt = { k: "Int" };
var tFloat = { k: "Float" };
var tBool = { k: "Bool" };
var tString = { k: "String" };
var isNum = (t) => t.k === "Int" || t.k === "Float";
function tyEq(a, b) {
  if (a.k !== b.k) return false;
  if (a.k === "List" && b.k === "List") return tyEq(a.elem, b.elem);
  if (a.k === "Option" && b.k === "Option") return tyEq(a.elem, b.elem);
  if (a.k === "Rec" && b.k === "Rec") {
    if (a.fields.length !== b.fields.length) return false;
    return a.fields.every((f) => {
      const g = b.fields.find((x) => x.name === f.name);
      return g && tyEq(f.ty, g.ty);
    });
  }
  if (a.k === "Fun" && b.k === "Fun") return a.params.length === b.params.length && a.params.every((p, i) => tyEq(p, b.params[i])) && tyEq(a.ret, b.ret);
  return a.k === b.k;
}
function showTy(t) {
  switch (t.k) {
    case "List":
      return `List[${showTy(t.elem)}]`;
    case "Option":
      return `Option[${showTy(t.elem)}]`;
    case "Rec":
      return `{${[...t.fields].sort((x, y) => x.name.localeCompare(y.name)).map((f) => `${f.name} : ${showTy(f.ty)}`).join(", ")}}`;
    // 正規形＝名前順
    case "Fun":
      return `(${t.params.map(showTy).join(", ")}) -> ${showTy(t.ret)}`;
    default:
      return t.k;
  }
}
var KEYWORDS = /* @__PURE__ */ new Set(["fn", "end", "body", "let", "in", "if", "requires", "ensures", "eg", "true", "false", "Int", "Float", "Bool", "String", "List", "type", "none"]);
function lex(src) {
  const toks = [];
  let i = 0;
  const two = ["=>", "->", ">=", "<=", "==", "!=", "&&", "||"];
  const one = "()[]{},:=+-*/<>!.";
  while (i < src.length) {
    const c = src[i];
    if (c === " " || c === "	" || c === "\n" || c === "\r") {
      i++;
      continue;
    }
    if (src.startsWith("--", i)) {
      while (i < src.length && src[i] !== "\n") i++;
      continue;
    }
    if (c === '"') {
      let j = i + 1, s = "";
      while (j < src.length && src[j] !== '"') {
        if (src[j] === "\\") {
          const n = src[j + 1];
          s += n === "n" ? "\n" : n === "t" ? "	" : n;
          j += 2;
        } else {
          s += src[j];
          j++;
        }
      }
      if (j >= src.length) throw new ParseErr(`\u672A\u7D42\u7AEF\u306E\u6587\u5B57\u5217`);
      toks.push({ t: "str", v: s });
      i = j + 1;
      continue;
    }
    const t2 = src.slice(i, i + 2);
    if (two.includes(t2)) {
      toks.push({ t: t2, v: t2 });
      i += 2;
      continue;
    }
    if (one.includes(c)) {
      toks.push({ t: c, v: c });
      i++;
      continue;
    }
    if (/[0-9]/.test(c)) {
      let j = i;
      while (j < src.length && /[0-9.]/.test(src[j])) j++;
      const v = src.slice(i, j);
      toks.push({ t: v.includes(".") ? "float" : "int", v });
      i = j;
      continue;
    }
    if (/[A-Za-z_]/.test(c)) {
      let j = i;
      while (j < src.length && /[A-Za-z0-9_]/.test(src[j])) j++;
      toks.push({ t: "ident", v: src.slice(i, j) });
      i = j;
      continue;
    }
    throw new ParseErr(`\u4E88\u671F\u3057\u306A\u3044\u6587\u5B57 '${c}'`);
  }
  toks.push({ t: "eof", v: "" });
  return toks;
}
var ParseErr = class extends Error {
};
var Parser = class {
  // 型エイリアス（透明・宣言は使用に先行）
  constructor(toks) {
    this.p = 0;
    this.nid = 1;
    this.aliases = /* @__PURE__ */ new Map();
    this.toks = toks;
  }
  peek() {
    return this.toks[this.p];
  }
  next() {
    return this.toks[this.p++];
  }
  eat(t) {
    const k = this.next();
    if (k.t !== t) throw new ParseErr(`'${t}' \u3092\u671F\u5F85\u3057\u305F\u304C '${k.v || k.t}'`);
    return k;
  }
  id() {
    return this.nid++;
  }
  program() {
    const fns = [];
    while (this.peek().t !== "eof") {
      if (this.peek().v === "type") {
        this.next();
        const name = this.eat("ident").v;
        this.eat("=");
        this.aliases.set(name, this.type());
      } else fns.push(this.fn());
    }
    return { fns };
  }
  fn() {
    this.eat("ident");
    const name = this.eat("ident").v;
    this.eat("(");
    const params = [];
    if (this.peek().t !== ")") {
      do {
        const n = this.eat("ident").v;
        this.eat(":");
        params.push({ name: n, ty: this.type() });
      } while (this.peek().t === "," && this.next());
    }
    this.eat(")");
    this.eat("->");
    const ret = this.type();
    const contracts = [];
    while (["requires", "ensures", "eg"].includes(this.peek().v)) {
      const k = this.next().v;
      if (k === "eg") {
        const call = this.expr();
        this.eat("=");
        const value = this.expr();
        contracts.push({ kind: "eg", call, value });
      } else contracts.push({ kind: k, expr: this.expr() });
    }
    this.eat("ident");
    const bodyTy = this.type();
    const body = this.expr();
    this.eat("ident");
    this.eat("ident");
    return { name, params, ret, contracts, bodyTy, body };
  }
  type() {
    const t = this.peek();
    if (t.t === "(") {
      this.next();
      const ps = [];
      if (this.peek().t !== ")") {
        do {
          ps.push(this.type());
        } while (this.peek().t === "," && this.next());
      }
      this.eat(")");
      this.eat("->");
      return { k: "Fun", params: ps, ret: this.type() };
    }
    if (t.t === "{") {
      this.next();
      const fields = [];
      if (this.peek().t !== "}") {
        do {
          const n2 = this.eat("ident").v;
          this.eat(":");
          fields.push({ name: n2, ty: this.type() });
        } while (this.peek().t === "," && this.next());
      }
      this.eat("}");
      return { k: "Rec", fields };
    }
    const n = this.eat("ident").v;
    if (n === "List") {
      this.eat("[");
      const e = this.type();
      this.eat("]");
      return { k: "List", elem: e };
    }
    if (n === "Option") {
      this.eat("[");
      const e = this.type();
      this.eat("]");
      return { k: "Option", elem: e };
    }
    if (n === "Int" || n === "Float" || n === "Bool" || n === "String") return { k: n };
    const alias = this.aliases.get(n);
    if (alias) return alias;
    throw new ParseErr(`\u672A\u77E5\u306E\u578B '${n}'\uFF08type ${n} = ... \u306E\u5BA3\u8A00\u306F\u4F7F\u7528\u3088\u308A\u524D\u306B\u7F6E\u304F\uFF09`);
  }
  // expr = let | or   （if は atom で処理）
  expr() {
    if (this.peek().v === "let") {
      this.next();
      const name = this.eat("ident").v;
      this.eat(":");
      const ty = this.type();
      this.eat("=");
      const val = this.expr();
      this.eat(
        "ident"
        /* in */
      );
      const body = this.expr();
      return { k: "let", name, ty, val, body, id: this.id() };
    }
    return this.or();
  }
  or() {
    let l = this.and();
    while (this.peek().t === "||") {
      this.next();
      l = { k: "bin", op: "||", l, r: this.and(), id: this.id() };
    }
    return l;
  }
  and() {
    let l = this.cmp();
    while (this.peek().t === "&&") {
      this.next();
      l = { k: "bin", op: "&&", l, r: this.cmp(), id: this.id() };
    }
    return l;
  }
  cmp() {
    const l = this.add();
    const o = this.peek().t;
    if (["==", "!=", ">=", "<=", ">", "<"].includes(o)) {
      this.next();
      return { k: "bin", op: o, l, r: this.add(), id: this.id() };
    }
    return l;
  }
  add() {
    let l = this.mul();
    while (this.peek().t === "+" || this.peek().t === "-") {
      const o = this.next().t;
      l = { k: "bin", op: o, l, r: this.mul(), id: this.id() };
    }
    return l;
  }
  mul() {
    let l = this.unary();
    while (this.peek().t === "*" || this.peek().t === "/") {
      const o = this.next().t;
      l = { k: "bin", op: o, l, r: this.unary(), id: this.id() };
    }
    return l;
  }
  unary() {
    if (this.peek().t === "-" || this.peek().t === "!") {
      const o = this.next().t;
      return { k: "un", op: o, e: this.unary(), id: this.id() };
    }
    return this.appl();
  }
  appl() {
    let a = this.atom();
    if (a.k === "var" && this.peek().t === "(") {
      this.next();
      const args = [];
      if (this.peek().t !== ")") {
        do {
          args.push(this.expr());
        } while (this.peek().t === "," && this.next());
      }
      this.eat(")");
      a = { k: "app", fn: a.name, args, id: this.id() };
    }
    while (this.peek().t === ".") {
      this.next();
      a = { k: "field", obj: a, name: this.eat("ident").v, id: this.id() };
    }
    return a;
  }
  atom() {
    const t = this.peek();
    if (t.t === "int") {
      this.next();
      return { k: "int", v: parseInt(t.v, 10), id: this.id() };
    }
    if (t.t === "float") {
      this.next();
      return { k: "float", v: parseFloat(t.v), id: this.id() };
    }
    if (t.t === "str") {
      this.next();
      return { k: "str", v: t.v, id: this.id() };
    }
    if (t.v === "true") {
      this.next();
      return { k: "bool", v: true, id: this.id() };
    }
    if (t.v === "false") {
      this.next();
      return { k: "bool", v: false, id: this.id() };
    }
    if (t.v === "if") {
      this.next();
      this.eat("(");
      const c = this.expr();
      this.eat(",");
      const th = this.expr();
      this.eat(",");
      const e = this.expr();
      this.eat(")");
      return { k: "if", c, t: th, e, id: this.id() };
    }
    if (t.v === "fn") {
      this.next();
      this.eat("(");
      const params = [];
      if (this.peek().t !== ")") {
        do {
          const n = this.eat("ident").v;
          let ty;
          if (this.peek().t === ":") {
            this.next();
            ty = this.type();
          }
          params.push({ name: n, ty });
        } while (this.peek().t === "," && this.next());
      }
      this.eat(")");
      this.eat("=>");
      return { k: "lam", params, body: this.expr(), id: this.id() };
    }
    if (t.t === "[") {
      this.next();
      const elems = [];
      if (this.peek().t !== "]") {
        do {
          elems.push(this.expr());
        } while (this.peek().t === "," && this.next());
      }
      this.eat("]");
      return { k: "list", elems, id: this.id() };
    }
    if (t.t === "ident" && t.v === "none") {
      this.next();
      return { k: "none", id: this.id() };
    }
    if (t.t === "{") {
      this.next();
      const fields = [];
      if (this.peek().t !== "}") {
        do {
          const n = this.eat("ident").v;
          this.eat("=");
          fields.push({ name: n, val: this.expr() });
        } while (this.peek().t === "," && this.next());
      }
      this.eat("}");
      return { k: "rec", fields, id: this.id() };
    }
    if (t.t === "(") {
      this.next();
      const e = this.expr();
      this.eat(")");
      return e;
    }
    if (t.t === "ident" && !KEYWORDS.has(t.v)) {
      this.next();
      return { k: "var", name: t.v, id: this.id() };
    }
    throw new ParseErr(`\u5F0F\u3092\u671F\u5F85\u3057\u305F\u304C '${t.v || t.t}'`);
  }
};
function parseProgram(src) {
  return new Parser(lex(src)).program();
}
function parseExpr(src) {
  const p = new Parser(lex(src));
  const e = p.expr();
  return e;
}
function structEq(a, b) {
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => structEq(x, b[i]));
  if (a && b && typeof a === "object" && typeof b === "object" && !Array.isArray(a) && !Array.isArray(b)) {
    const ka = Object.keys(a), kb = Object.keys(b);
    return ka.length === kb.length && ka.every((k) => k in b && structEq(a[k], b[k]));
  }
  return a === b;
}
function valEq(a, b) {
  if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) <= 1e-9;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => valEq(x, b[i]));
  if (a && b && typeof a === "object" && typeof b === "object" && !Array.isArray(a) && !Array.isArray(b)) {
    const ka = Object.keys(a), kb = Object.keys(b);
    return ka.length === kb.length && ka.every((k) => k in b && valEq(a[k], b[k]));
  }
  return a === b;
}
var listFloat = { k: "List", elem: tFloat };
var STDLIB = {
  // 数値
  sqrt: { ty: { k: "Fun", params: [tFloat], ret: tFloat }, run: (a) => Math.sqrt(a[0]) },
  toFloat: { ty: { k: "Fun", params: [tInt], ret: tFloat }, run: (a) => a[0] },
  toInt: { ty: { k: "Fun", params: [tFloat], ret: tInt }, run: (a) => Math.trunc(a[0]) },
  // リスト（具体型）
  dot: { ty: { k: "Fun", params: [listFloat, listFloat], ret: tFloat }, run: (a) => a[0].reduce((s, x, i) => s + x * a[1][i], 0) },
  sum: { ty: { k: "Fun", params: [listFloat], ret: tFloat }, run: (a) => a[0].reduce((s, x) => s + x, 0) },
  // 文字列
  strlen: { ty: { k: "Fun", params: [tString], ret: tInt }, run: (a) => a[0].length },
  concat: { ty: { k: "Fun", params: [tString, tString], ret: tString }, run: (a) => a[0] + a[1] },
  split: { ty: { k: "Fun", params: [tString, tString], ret: { k: "List", elem: tString } }, run: (a) => a[0].split(a[1]) },
  join: { ty: { k: "Fun", params: [{ k: "List", elem: tString }, tString], ret: tString }, run: (a) => a[0].join(a[1]) },
  contains: { ty: { k: "Fun", params: [tString, tString], ret: tBool }, run: (a) => a[0].includes(a[1]) },
  substring: { ty: { k: "Fun", params: [tString, tInt, tInt], ret: tString }, run: (a) => a[0].slice(a[1], a[2]) },
  trim: { ty: { k: "Fun", params: [tString], ret: tString }, run: (a) => a[0].trim() },
  // v0.5: 失敗しうる変換は Option を返す
  parseInt: { ty: { k: "Fun", params: [tString], ret: { k: "Option", elem: tInt } }, run: (a) => {
    const s = a[0].trim();
    return /^-?\d+$/.test(s) ? { has: true, val: Number(s) } : { has: false };
  } },
  parseFloat: { ty: { k: "Fun", params: [tString], ret: { k: "Option", elem: tFloat } }, run: (a) => {
    const s = a[0].trim();
    const n = Number(s);
    return s !== "" && Number.isFinite(n) ? { has: true, val: n } : { has: false };
  } }
};
var POLY = /* @__PURE__ */ new Set(["length", "get", "head", "tail", "append", "map", "filter", "fold", "toString", "headOr", "getOr", "some", "isSome", "unwrapOr", "find"]);
var RT = {
  sqrt: (a) => Math.sqrt(a[0]),
  toFloat: (a) => a[0],
  toInt: (a) => Math.trunc(a[0]),
  dot: (a) => a[0].reduce((s, x, i) => s + x * a[1][i], 0),
  sum: (a) => a[0].reduce((s, x) => s + x, 0),
  strlen: (a) => a[0].length,
  concat: (a) => a[0] + a[1],
  length: (a) => a[0].length,
  head: (a) => {
    const x = a[0];
    if (!x.length) throw new RuntimeErr("head: \u7A7A\u30EA\u30B9\u30C8");
    return x[0];
  },
  tail: (a) => a[0].slice(1),
  get: (a) => {
    const x = a[0], i = a[1];
    if (i < 0 || i >= x.length) throw new RuntimeErr(`get: \u7BC4\u56F2\u5916 ${i}`);
    return x[i];
  },
  append: (a) => [...a[0], a[1]],
  map: (a) => {
    const x = a[0], f = a[1];
    if (Array.isArray(x)) return x.map((v) => f([v]));
    return x.has ? { has: true, val: f([x.val]) } : { has: false };
  },
  filter: (a) => a[0].filter((x) => a[1]([x])),
  fold: (a) => a[0].reduce((acc, x) => a[2]([acc, x]), a[1]),
  // v0.4: 文字列と安全な既定値つき取得
  split: (a) => a[0].split(a[1]),
  join: (a) => a[0].join(a[1]),
  contains: (a) => a[0].includes(a[1]),
  substring: (a) => a[0].slice(a[1], a[2]),
  trim: (a) => a[0].trim(),
  toString: (a) => String(a[0]),
  headOr: (a) => {
    const x = a[0];
    return x.length ? x[0] : a[1];
  },
  getOr: (a) => {
    const x = a[0], i = a[1];
    return i >= 0 && i < x.length ? x[i] : a[2];
  },
  // v0.5: Option（実行時表現は {has: true, val} / {has: false}）
  some: (a) => ({ has: true, val: a[0] }),
  isSome: (a) => a[0].has,
  unwrapOr: (a) => {
    const o = a[0];
    return o.has ? o.val : a[1];
  },
  find: (a) => {
    const x = a[0].find((v) => a[1]([v]));
    return x === void 0 ? { has: false } : { has: true, val: x };
  },
  parseInt: (a) => {
    const s = a[0].trim();
    return /^-?\d+$/.test(s) ? { has: true, val: Number(s) } : { has: false };
  },
  parseFloat: (a) => {
    const s = a[0].trim();
    const n = Number(s);
    return s !== "" && Number.isFinite(n) ? { has: true, val: n } : { has: false };
  }
};
function hasFun(t) {
  return t.k === "Fun" || (t.k === "List" || t.k === "Option") && hasFun(t.elem);
}
var Checker = class {
  constructor(prog) {
    this.errors = [];
    this.globals = /* @__PURE__ */ new Map();
    for (const [n, b] of Object.entries(STDLIB)) this.globals.set(n, b.ty);
    for (const f of prog.fns) this.globals.set(f.name, { k: "Fun", params: f.params.map((p) => p.ty), ret: f.ret });
  }
  scopeOf(ctx) {
    return [...ctx, ...this.globals].map(([name, ty]) => ({ name, type: showTy(ty) }));
  }
  err(d) {
    this.errors.push(d);
  }
  synth(e, ctx) {
    switch (e.k) {
      case "int":
        return tInt;
      case "float":
        return tFloat;
      case "bool":
        return tBool;
      case "str":
        return tString;
      case "var": {
        const t = ctx.get(e.name) ?? this.globals.get(e.name);
        if (!t) {
          this.err({ code: "unbound", name: e.name, scope: this.scopeOf(ctx) });
          return null;
        }
        return t;
      }
      case "lam": {
        if (e.params.some((p) => !p.ty)) {
          this.err({ code: "type_mismatch", at: e.id, expected: "\u578B\u6CE8\u91C8\u3064\u304D\u30E9\u30E0\u30C0\uFF08\u3053\u306E\u4F4D\u7F6E\u3067\u306F\u5F15\u6570\u578B\u3092\u6587\u8108\u304B\u3089\u6C7A\u3081\u3089\u308C\u306A\u3044\uFF09", actual: "\u6CE8\u91C8\u306A\u3057\u30E9\u30E0\u30C0", scope: this.scopeOf(ctx) });
          return null;
        }
        const c2 = new Map(ctx);
        for (const p of e.params) c2.set(p.name, p.ty);
        const r = this.synth(e.body, c2);
        return r ? { k: "Fun", params: e.params.map((p) => p.ty), ret: r } : null;
      }
      case "none": {
        this.err({ code: "type_mismatch", at: e.id, expected: "Option[T]\uFF08let \u306E\u6CE8\u91C8\u3084 if \u306E\u3082\u3046\u4E00\u65B9\u306E\u679D\u306A\u3069\u3001\u6587\u8108\u304B\u3089\u578B\u304C\u8981\u308B\uFF09", actual: "none", scope: this.scopeOf(ctx) });
        return null;
      }
      case "rec": {
        const fields = [];
        for (const f of e.fields) {
          const t = this.synth(f.val, ctx);
          if (!t) return null;
          fields.push({ name: f.name, ty: t });
        }
        return { k: "Rec", fields };
      }
      case "field": {
        const t = this.synth(e.obj, ctx);
        if (!t) return null;
        if (t.k !== "Rec") {
          this.err({ code: "type_mismatch", at: e.id, expected: "{..}(\u30EC\u30B3\u30FC\u30C9)", actual: showTy(t), scope: this.scopeOf(ctx) });
          return null;
        }
        const f = t.fields.find((x) => x.name === e.name);
        if (!f) {
          this.err({ code: "unknown_field", at: e.id, name: e.name, fields: t.fields.map((x) => ({ name: x.name, type: showTy(x.ty) })) });
          return null;
        }
        return f.ty;
      }
      case "app": {
        if (POLY.has(e.fn)) return this.synthPoly(e, ctx);
        const ft = ctx.get(e.fn) ?? this.globals.get(e.fn);
        if (!ft || ft.k !== "Fun") {
          this.err({ code: "not_a_function", name: e.fn, scope: this.scopeOf(ctx) });
          return null;
        }
        e.args.forEach((a, i) => ft.params[i] && this.check(a, ft.params[i], ctx));
        return ft.ret;
      }
      case "un": {
        if (e.op === "!") {
          this.check(e.e, tBool, ctx);
          return tBool;
        }
        const t = this.synth(e.e, ctx);
        if (t && !isNum(t)) this.err({ code: "type_mismatch", at: e.id, expected: "Int|Float", actual: showTy(t), scope: this.scopeOf(ctx) });
        return t;
      }
      case "bin":
        return this.synthBin(e, ctx);
      case "if":
      case "let":
      case "list": {
        if (e.k === "if") {
          this.check(e.c, tBool, ctx);
          const t = this.synth(e.t, ctx);
          if (t) this.check(e.e, t, ctx);
          return t;
        }
        if (e.k === "let") {
          const s = e.ty;
          this.check(e.val, s, ctx);
          const c2 = new Map(ctx);
          c2.set(e.name, s);
          return this.synth(e.body, c2);
        }
        if (e.elems.length === 0) {
          this.err({ code: "type_mismatch", at: e.id, expected: "List[?]", actual: "\u7A7A\u30EA\u30B9\u30C8(\u578B\u4E0D\u5B9A)", scope: this.scopeOf(ctx) });
          return null;
        }
        const et = this.synth(e.elems[0], ctx);
        if (et) e.elems.forEach((x) => this.check(x, et, ctx));
        return et ? { k: "List", elem: et } : null;
      }
    }
  }
  // 多相組み込みの型付け（引数のリスト型から要素型を推す）
  synthPoly(e, ctx) {
    const listArg = () => {
      const t = this.synth(e.args[0], ctx);
      if (t && t.k !== "List") {
        this.err({ code: "type_mismatch", at: e.id, expected: "List[?]", actual: showTy(t), scope: this.scopeOf(ctx) });
        return null;
      }
      return t;
    };
    switch (e.fn) {
      case "length": {
        listArg();
        return tInt;
      }
      case "head": {
        const t = listArg();
        return t && t.k === "List" ? t.elem : null;
      }
      case "tail": {
        const t = listArg();
        return t;
      }
      case "get": {
        const t = listArg();
        this.check(e.args[1], tInt, ctx);
        return t && t.k === "List" ? t.elem : null;
      }
      case "append": {
        const t = listArg();
        if (t && t.k === "List") this.check(e.args[1], t.elem, ctx);
        return t;
      }
      case "map": {
        const t0 = this.synth(e.args[0], ctx);
        const f = e.args[1];
        if (t0 && t0.k !== "List" && t0.k !== "Option") {
          this.err({ code: "type_mismatch", at: e.id, expected: "List[?] \u304B Option[?]", actual: showTy(t0), scope: this.scopeOf(ctx) });
          return null;
        }
        const wrap = (u) => t0 && t0.k === "Option" ? { k: "Option", elem: u } : { k: "List", elem: u };
        const elem = t0 && (t0.k === "List" || t0.k === "Option") ? t0.elem : null;
        if (elem && f?.k === "lam" && f.params.length === 1) {
          const p = f.params[0];
          if (p.ty && !tyEq(p.ty, elem)) this.err({ code: "type_mismatch", at: e.id, expected: showTy(elem), actual: showTy(p.ty), scope: this.scopeOf(ctx) });
          const c2 = new Map(ctx);
          c2.set(p.name, p.ty ?? elem);
          const u = this.synth(f.body, c2);
          return u ? wrap(u) : null;
        }
        const ft = this.synth(f, ctx);
        if (!ft) return null;
        if (ft.k !== "Fun" || ft.params.length !== 1) {
          this.err({ code: "type_mismatch", at: e.id, expected: "(T) -> U", actual: showTy(ft), scope: this.scopeOf(ctx) });
          return null;
        }
        if (elem && !tyEq(ft.params[0], elem)) this.err({ code: "type_mismatch", at: e.id, expected: `(${showTy(elem)}) -> U`, actual: showTy(ft), scope: this.scopeOf(ctx) });
        return wrap(ft.ret);
      }
      case "filter": {
        const t = listArg();
        const f = e.args[1];
        if (t && t.k === "List" && f?.k === "lam" && f.params.length === 1) {
          const p = f.params[0];
          if (p.ty && !tyEq(p.ty, t.elem)) this.err({ code: "type_mismatch", at: e.id, expected: showTy(t.elem), actual: showTy(p.ty), scope: this.scopeOf(ctx) });
          const c2 = new Map(ctx);
          c2.set(p.name, p.ty ?? t.elem);
          this.check(f.body, tBool, c2);
          return t;
        }
        const ft = this.synth(f, ctx);
        if (t && t.k === "List" && ft && ft.k === "Fun") {
          if (!tyEq(ft.params[0], t.elem) || ft.ret.k !== "Bool") this.err({ code: "type_mismatch", at: e.id, expected: `(${showTy(t.elem)}) -> Bool`, actual: showTy(ft), scope: this.scopeOf(ctx) });
        }
        return t;
      }
      case "fold": {
        const t = listArg();
        const init = this.synth(e.args[1], ctx);
        const f = e.args[2];
        if (init && t && t.k === "List" && f?.k === "lam" && f.params.length === 2) {
          const [pa, px] = f.params;
          if (pa.ty && !tyEq(pa.ty, init)) this.err({ code: "type_mismatch", at: e.id, expected: showTy(init), actual: showTy(pa.ty), scope: this.scopeOf(ctx) });
          if (px.ty && !tyEq(px.ty, t.elem)) this.err({ code: "type_mismatch", at: e.id, expected: showTy(t.elem), actual: showTy(px.ty), scope: this.scopeOf(ctx) });
          const c2 = new Map(ctx);
          c2.set(pa.name, pa.ty ?? init);
          c2.set(px.name, px.ty ?? t.elem);
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
      case "toString": {
        const t = this.synth(e.args[0], ctx);
        if (t && hasFun(t)) this.err({ code: "type_mismatch", at: e.id, expected: "Int|Float|Bool|String", actual: showTy(t), scope: this.scopeOf(ctx) });
        return tString;
      }
      case "headOr": {
        const t = listArg();
        if (t && t.k === "List") {
          this.check(e.args[1], t.elem, ctx);
          return t.elem;
        }
        return null;
      }
      case "getOr": {
        const t = listArg();
        this.check(e.args[1], tInt, ctx);
        if (t && t.k === "List") {
          this.check(e.args[2], t.elem, ctx);
          return t.elem;
        }
        return null;
      }
      case "some": {
        const t = this.synth(e.args[0], ctx);
        return t ? { k: "Option", elem: t } : null;
      }
      case "isSome": {
        const t = this.synth(e.args[0], ctx);
        if (t && t.k !== "Option") this.err({ code: "type_mismatch", at: e.id, expected: "Option[T]", actual: showTy(t), scope: this.scopeOf(ctx) });
        return tBool;
      }
      case "unwrapOr": {
        const t = this.synth(e.args[0], ctx);
        if (t && t.k !== "Option") {
          this.err({ code: "type_mismatch", at: e.id, expected: "Option[T]", actual: showTy(t), scope: this.scopeOf(ctx) });
          return null;
        }
        if (t && t.k === "Option") {
          this.check(e.args[1], t.elem, ctx);
          return t.elem;
        }
        return null;
      }
      case "find": {
        const t = listArg();
        const f = e.args[1];
        if (t && t.k === "List" && f?.k === "lam" && f.params.length === 1) {
          const p = f.params[0];
          if (p.ty && !tyEq(p.ty, t.elem)) this.err({ code: "type_mismatch", at: e.id, expected: showTy(t.elem), actual: showTy(p.ty), scope: this.scopeOf(ctx) });
          const c2 = new Map(ctx);
          c2.set(p.name, p.ty ?? t.elem);
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
  synthBin(e, ctx) {
    const { op } = e;
    if (op === "&&" || op === "||") {
      this.check(e.l, tBool, ctx);
      this.check(e.r, tBool, ctx);
      return tBool;
    }
    if (op === "==" || op === "!=") {
      const lt2 = this.synth(e.l, ctx);
      if (lt2) this.check(e.r, lt2, ctx);
      return tBool;
    }
    if ([">", ">=", "<", "<="].includes(op)) {
      const lt2 = this.synth(e.l, ctx);
      if (lt2) {
        if (!isNum(lt2)) this.err({ code: "type_mismatch", at: e.id, expected: "Int|Float", actual: showTy(lt2), scope: this.scopeOf(ctx) });
        this.check(e.r, lt2, ctx);
      }
      return tBool;
    }
    const lt = this.synth(e.l, ctx);
    if (lt) {
      const strPlus = op === "+" && lt.k === "String";
      if (!isNum(lt) && !strPlus) this.err({ code: "type_mismatch", at: e.id, expected: op === "+" ? "Int|Float|String" : "Int|Float", actual: showTy(lt), scope: this.scopeOf(ctx) });
      this.check(e.r, lt, ctx);
      e.nt = lt.k;
    }
    return lt;
  }
  check(e, want, ctx) {
    if (e.k === "if") {
      this.check(e.c, tBool, ctx);
      this.check(e.t, want, ctx);
      this.check(e.e, want, ctx);
      return;
    }
    if (e.k === "none") {
      if (want.k !== "Option") this.err({ code: "type_mismatch", at: e.id, expected: showTy(want), actual: "none\uFF08Option[T]\uFF09", scope: this.scopeOf(ctx) });
      return;
    }
    if (e.k === "list") {
      if (want.k !== "List") {
        this.err({ code: "type_mismatch", at: e.id, expected: showTy(want), actual: "\u30EA\u30B9\u30C8", scope: this.scopeOf(ctx) });
        return;
      }
      for (const x of e.elems) this.check(x, want.elem, ctx);
      return;
    }
    if (e.k === "app" && e.fn === "fold") {
      const t0 = this.synth(e.args[0], ctx);
      if (t0 && t0.k !== "List") this.err({ code: "type_mismatch", at: e.id, expected: "List[?]", actual: showTy(t0), scope: this.scopeOf(ctx) });
      this.check(e.args[1], want, ctx);
      const f = e.args[2];
      if (t0 && t0.k === "List" && f?.k === "lam" && f.params.length === 2) {
        const [pa, px] = f.params;
        if (pa.ty && !tyEq(pa.ty, want)) this.err({ code: "type_mismatch", at: e.id, expected: showTy(want), actual: showTy(pa.ty), scope: this.scopeOf(ctx) });
        if (px.ty && !tyEq(px.ty, t0.elem)) this.err({ code: "type_mismatch", at: e.id, expected: showTy(t0.elem), actual: showTy(px.ty), scope: this.scopeOf(ctx) });
        const c2 = new Map(ctx);
        c2.set(pa.name, pa.ty ?? want);
        c2.set(px.name, px.ty ?? t0.elem);
        this.check(f.body, want, c2);
        return;
      }
      if (f) this.check(f, { k: "Fun", params: [want, t0 && t0.k === "List" ? t0.elem : want], ret: want }, ctx);
      return;
    }
    if (e.k === "lam") {
      if (want.k !== "Fun") {
        this.err({ code: "type_mismatch", at: e.id, expected: showTy(want), actual: "\u95A2\u6570", scope: this.scopeOf(ctx) });
        return;
      }
      if (e.params.length !== want.params.length) {
        this.err({ code: "type_mismatch", at: e.id, expected: showTy(want), actual: `${e.params.length}\u5F15\u6570\u306E\u95A2\u6570`, scope: this.scopeOf(ctx) });
        return;
      }
      const c2 = new Map(ctx);
      e.params.forEach((p, i) => {
        const w = want.params[i];
        if (p.ty && !tyEq(p.ty, w)) this.err({ code: "type_mismatch", at: e.id, expected: showTy(w), actual: showTy(p.ty), scope: this.scopeOf(ctx) });
        c2.set(p.name, p.ty ?? w);
      });
      this.check(e.body, want.ret, c2);
      return;
    }
    if (e.k === "rec") {
      if (want.k !== "Rec") {
        this.err({ code: "type_mismatch", at: e.id, expected: showTy(want), actual: "{..}(\u30EC\u30B3\u30FC\u30C9)", scope: this.scopeOf(ctx) });
        return;
      }
      const wantNames = new Set(want.fields.map((f) => f.name)), gotNames = new Set(e.fields.map((f) => f.name));
      const missing = want.fields.filter((f) => !gotNames.has(f.name)).map((f) => f.name);
      const extra = e.fields.filter((f) => !wantNames.has(f.name)).map((f) => f.name);
      if (missing.length || extra.length) {
        this.err({ code: "type_mismatch", at: e.id, expected: showTy(want), actual: `{${[...gotNames].sort().join(", ")}}${missing.length ? ` (\u4E0D\u8DB3: ${missing.join(",")})` : ""}${extra.length ? ` (\u4F59\u5206: ${extra.join(",")})` : ""}`, scope: this.scopeOf(ctx) });
        return;
      }
      for (const f of e.fields) this.check(f.val, want.fields.find((x) => x.name === f.name).ty, ctx);
      return;
    }
    if (e.k === "let") {
      this.check(e.val, e.ty, ctx);
      const c2 = new Map(ctx);
      c2.set(e.name, e.ty);
      this.check(e.body, want, c2);
      return;
    }
    if (e.k === "list") {
      if (want.k !== "List") {
        this.err({ code: "type_mismatch", at: e.id, expected: showTy(want), actual: "List[..]", scope: this.scopeOf(ctx) });
        return;
      }
      e.elems.forEach((x) => this.check(x, want.elem, ctx));
      return;
    }
    const got = this.synth(e, ctx);
    if (got && !tyEq(got, want)) this.err({ code: "type_mismatch", at: e.id, expected: showTy(want), actual: showTy(got), scope: this.scopeOf(ctx) });
  }
  checkFn(f) {
    const ctx = new Map(f.params.map((p) => [p.name, p.ty]));
    if (!tyEq(f.bodyTy, f.ret)) this.err({ code: "type_mismatch", at: f.body.id, expected: showTy(f.ret), actual: showTy(f.bodyTy) + "(body\u6CE8\u91C8)", scope: this.scopeOf(ctx) });
    this.check(f.body, f.ret, ctx);
    for (const c of f.contracts) {
      if (c.kind === "ensures" && c.expr) {
        const c2 = new Map(ctx);
        c2.set("ret", f.ret);
        this.check(c.expr, tBool, c2);
      }
      if (c.kind === "requires" && c.expr) this.check(c.expr, tBool, ctx);
      if (c.kind === "eg" && c.call && c.value) {
        const t = this.synth(c.call, ctx);
        if (t) this.check(c.value, t, ctx);
      }
    }
  }
};
function check(prog) {
  const ck = new Checker(prog);
  for (const f of prog.fns) ck.checkFn(f);
  return { ok: ck.errors.length === 0, errors: ck.errors };
}
var RuntimeErr = class extends Error {
};
function evalExpr(e, env, gv) {
  switch (e.k) {
    case "int":
    case "float":
      return e.v;
    case "bool":
      return e.v;
    case "str":
      return e.v;
    case "var": {
      const v = env.get(e.name) ?? gv.get(e.name);
      if (v === void 0) throw new RuntimeErr(`\u672A\u675F\u7E1B '${e.name}'`);
      return v;
    }
    case "lam":
      return (args) => {
        const e2 = new Map(env);
        e.params.forEach((p, i) => e2.set(p.name, args[i]));
        return evalExpr(e.body, e2, gv);
      };
    case "none":
      return { has: false };
    case "rec": {
      const o = {};
      for (const f of e.fields) o[f.name] = evalExpr(f.val, env, gv);
      return o;
    }
    case "field": {
      const o = evalExpr(e.obj, env, gv);
      return o[e.name];
    }
    case "list":
      return e.elems.map((x) => evalExpr(x, env, gv));
    case "if":
      return evalExpr(e.c, env, gv) ? evalExpr(e.t, env, gv) : evalExpr(e.e, env, gv);
    case "let": {
      const v = evalExpr(e.val, env, gv);
      const e2 = new Map(env);
      e2.set(e.name, v);
      return evalExpr(e.body, e2, gv);
    }
    case "un": {
      const v = evalExpr(e.e, env, gv);
      return e.op === "!" ? !v : -v;
    }
    case "bin":
      return evalBin(e.op, evalExpr(e.l, env, gv), evalExpr(e.r, env, gv), e);
    case "app": {
      const fv = env.get(e.fn) ?? gv.get(e.fn);
      if (typeof fv !== "function") throw new RuntimeErr(`\u547C\u3073\u51FA\u305B\u306A\u3044 '${e.fn}'`);
      return fv(e.args.map((a) => evalExpr(a, env, gv)));
    }
  }
}
function buildGV(prog) {
  const gv = new Map(Object.entries(RT));
  for (const f of prog.fns) gv.set(f.name, (args) => {
    const env = /* @__PURE__ */ new Map();
    f.params.forEach((p, i) => env.set(p.name, args[i]));
    return evalExpr(f.body, env, gv);
  });
  return gv;
}
function evalBin(op, l, r, e) {
  switch (op) {
    case "+":
      return l + r;
    // Int/Float の加算 or String 連結（型検査済み）
    case "-":
      return l - r;
    case "*":
      return l * r;
    case "/": {
      if (r === 0) throw new RuntimeErr("0 \u9664\u7B97");
      const q = l / r;
      return e.nt === "Int" ? Math.trunc(q) : q;
    }
    // 型注釈で Int/Float 除算を決める
    case "&&":
      return l && r;
    case "||":
      return l || r;
    case "==":
      return structEq(l, r);
    case "!=":
      return !structEq(l, r);
    case ">":
      return l > r;
    case ">=":
      return l >= r;
    case "<":
      return l < r;
    case "<=":
      return l <= r;
  }
  throw new RuntimeErr(`\u672A\u77E5\u306E\u6F14\u7B97\u5B50 ${op}`);
}
function runContracts(prog) {
  const gv = buildGV(prog);
  const out = [];
  for (const f of prog.fns) for (const c of f.contracts) {
    if (c.kind !== "eg" || !c.call || !c.value) continue;
    let got, want;
    try {
      got = evalExpr(c.call, /* @__PURE__ */ new Map(), gv);
      want = evalExpr(c.value, /* @__PURE__ */ new Map(), gv);
    } catch (ex) {
      out.push({ code: "contract", kind: "eg", call: showExpr(c.call), expected: showExpr(c.value), actual: `error: ${ex.message}` });
      continue;
    }
    if (!valEq(got, want)) {
      out.push({ code: "contract", kind: "eg", call: showExpr(c.call), expected: JSON.stringify(want), actual: JSON.stringify(got) });
      continue;
    }
    for (const c2 of f.contracts) if (c2.kind === "ensures" && c2.expr) {
      const env = /* @__PURE__ */ new Map([["ret", got]]);
      let ens;
      try {
        ens = evalExpr(c2.expr, env, gv);
      } catch {
        ens = false;
      }
      if (ens !== true) out.push({ code: "contract", kind: "ensures", call: showExpr(c.call), expected: showExpr(c2.expr), actual: "false" });
    }
  }
  return out;
}
function showExpr(e) {
  switch (e.k) {
    case "int":
      return String(e.v);
    case "float":
      return e.v.toFixed(1);
    case "bool":
      return String(e.v);
    case "str":
      return JSON.stringify(e.v);
    case "var":
      return e.name;
    case "list":
      return `[${e.elems.map(showExpr).join(", ")}]`;
    case "if":
      return `if(${showExpr(e.c)}, ${showExpr(e.t)}, ${showExpr(e.e)})`;
    case "let":
      return `let ${e.name}: ${showTy(e.ty)} = ${showExpr(e.val)} in ${showExpr(e.body)}`;
    case "app":
      return `${e.fn}(${e.args.map(showExpr).join(", ")})`;
    case "rec":
      return `{${[...e.fields].sort((x, y) => x.name.localeCompare(y.name)).map((f) => `${f.name} = ${showExpr(f.val)}`).join(", ")}}`;
    // 正規形＝名前順
    case "field":
      return `${showExpr(e.obj)}.${e.name}`;
    case "none":
      return "none";
    case "lam":
      return `fn (${e.params.map((p) => p.ty ? `${p.name} : ${showTy(p.ty)}` : p.name).join(", ")}) => ${showExpr(e.body)}`;
    case "bin":
      return `${showExpr(e.l)} ${e.op} ${showExpr(e.r)}`;
    case "un":
      return `${e.op}${showExpr(e.e)}`;
  }
}
function evalInProgram(prog, exprSrc) {
  return evalExpr(parseExpr(exprSrc), /* @__PURE__ */ new Map(), buildGV(prog));
}
function showProgram(prog) {
  return prog.fns.map((f) => {
    const params = f.params.map((p) => `${p.name} : ${showTy(p.ty)}`).join(", ");
    const cs = f.contracts.map((c) => c.kind === "eg" ? `  eg ${showExpr(c.call)} = ${showExpr(c.value)}` : `  ${c.kind} ${showExpr(c.expr)}`).join("\n");
    return `fn ${f.name} (${params}) -> ${showTy(f.ret)}
${cs ? cs + "\n" : ""}body ${showTy(f.bodyTy)}
  ${showExpr(f.body)}
end ${f.name}`;
  }).join("\n\n");
}

// core/tojs.ts
var PRELUDE = `const $rt = {
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
  eq: function eq(a, b) { // == \u306E\u610F\u5473\u8AD6: \u69CB\u9020\u7B49\u4FA1\uFF08\u30A4\u30F3\u30BF\u30D7\u30EA\u30BF\u306E structEq \u3068\u4E00\u81F4\u3055\u305B\u308B\uFF09
    if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => eq(x, b[i]));
    if (a && b && typeof a === "object" && typeof b === "object" && !Array.isArray(a) && !Array.isArray(b)) {
      const ka = Object.keys(a), kb = Object.keys(b);
      return ka.length === kb.length && ka.every((k) => k in b && eq(a[k], b[k]));
    }
    return a === b;
  },
};`;
var POLY2 = /* @__PURE__ */ new Set(["length", "get", "head", "tail", "append", "map", "filter", "fold", "toString", "headOr", "getOr", "some", "isSome", "unwrapOr", "find"]);
var STDLIB2 = /* @__PURE__ */ new Set(["sqrt", "toFloat", "toInt", "dot", "sum", "strlen", "concat", "split", "join", "contains", "substring", "trim", "parseInt", "parseFloat"]);
var isBuiltin = (n) => POLY2.has(n) || STDLIB2.has(n);
function exprToJs(e) {
  switch (e.k) {
    case "int":
      return String(e.v);
    case "float":
      return Number.isInteger(e.v) ? e.v.toFixed(1) : String(e.v);
    case "bool":
      return String(e.v);
    case "str":
      return JSON.stringify(e.v);
    case "var":
      return isBuiltin(e.name) ? `$rt.${e.name}` : e.name;
    // 組み込みを値として使う場合
    case "list":
      return `[${e.elems.map(exprToJs).join(", ")}]`;
    case "if":
      return `(${exprToJs(e.c)} ? ${exprToJs(e.t)} : ${exprToJs(e.e)})`;
    case "let":
      return `((${e.name}) => ${exprToJs(e.body)})(${exprToJs(e.val)})`;
    case "lam":
      return `((${e.params.map((p) => p.name).join(", ")}) => ${exprToJs(e.body)})`;
    case "rec":
      return `({${e.fields.map((f) => `${f.name}: ${exprToJs(f.val)}`).join(", ")}})`;
    case "field":
      return `${exprToJs(e.obj)}.${e.name}`;
    case "none":
      return `({has: false})`;
    case "un":
      return `(${e.op}${exprToJs(e.e)})`;
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
function toJs(prog) {
  const defs = prog.fns.map((f) => `const ${f.name} = (${f.params.map((p) => p.name).join(", ")}) => ${exprToJs(f.body)};`);
  return `${PRELUDE}
${defs.join("\n")}`;
}
function runJs(prog, exprSrc) {
  const body = `${toJs(prog)}
return (${exprToJs(parseExpr(exprSrc))});`;
  return new Function(body)();
}
export {
  check,
  evalInProgram,
  parseProgram,
  runContracts,
  runJs,
  showExpr,
  showProgram,
  toJs,
  valEq
};
