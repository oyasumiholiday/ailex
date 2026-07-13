// Ailex v0.1 — conformance テスト群（golden tests）＋ランナー
// 実在の言語の教訓: 機能を足す前にテストの器を持ち、緑を保ちながら言語を育てる。
// 各ケース: Ailex ソース → 期待する {検査結果 / 診断コード / 評価値 / 契約結果}。
// 実行: node ailex/core/conformance.ts

import { parseProgram, check, runContracts, evalInProgram, ParseErr } from "./lang.ts";
import { runJs } from "./tojs.ts";

interface Case {
  name: string;
  src: string;
  check?: "ok" | string;              // 期待する型検査結果（"ok" or 診断コード）
  parseErr?: boolean;                 // パースエラーを期待
  evals?: [string, number | boolean | string][]; // [式, 期待値]（型検査 ok のとき評価）
  contracts?: "ok" | "fail";          // eg/ensures 契約の結果
}

const F = (body: string, sig = "fn f (x : Float) -> Float", bt = "Float") =>
  `${sig}\nbody ${bt}\n  ${body}\nend f`;

const CASES: Case[] = [
  // ── 算術・型 ──
  { name: "int arithmetic", src: `fn f (x : Int) -> Int\nbody Int\n  x * x + 1\nend f`, check: "ok", evals: [["f(3)", 10], ["f(0)", 1]] },
  { name: "float arithmetic", src: F("x * x"), check: "ok", evals: [["f(3.0)", 9], ["f(0.5)", 0.25]] },
  { name: "int/float no mix", src: `fn f (x : Int) -> Int\nbody Int\n  x + 1.0\nend f`, check: "type_mismatch" },
  { name: "int division truncates", src: `fn f (x : Int) -> Int\nbody Int\n  x / 2\nend f`, check: "ok", evals: [["f(7)", 3]] },
  { name: "float division", src: F("x / 2.0"), check: "ok", evals: [["f(7.0)", 3.5]] },

  // ── if / bool / 比較 ──
  { name: "if + comparison", src: F("if(x >= 0.0, x, 0.0)"), check: "ok", evals: [["f(3.0)", 3], ["f(-2.0)", 0]] },
  { name: "if branch type must match", src: `fn f (x : Int) -> Int\nbody Int\n  if(x >= 0, x, 1.0)\nend f`, check: "type_mismatch" },
  { name: "bool ops", src: `fn g (a : Bool, b : Bool) -> Bool\nbody Bool\n  a && (b || !a)\nend g`, check: "ok", evals: [["g(true, true)", true], ["g(true, false)", false]] },
  { name: "comparison yields Bool", src: `fn ge (a : Float, b : Float) -> Bool\nbody Bool\n  a >= b\nend ge`, check: "ok", evals: [["ge(3.0, 2.0)", true], ["ge(1.0, 5.0)", false]] },

  // ── let ──
  { name: "let binding", src: `fn f (a : Float, b : Float, k : Float) -> Float\nbody Float\n  let s : Float = a + b in s * k\nend f`, check: "ok", evals: [["f(2.0, 3.0, 10.0)", 50]] },
  { name: "let type mismatch", src: `fn f (x : Float) -> Float\nbody Float\n  let n : Int = x in x\nend f`, check: "type_mismatch" },

  // ── 関数呼び出し・stdlib ──
  { name: "call stdlib sqrt", src: `fn norm2 (a : Float, b : Float) -> Float\nbody Float\n  sqrt(a * a + b * b)\nend norm2`, check: "ok", evals: [["norm2(3.0, 4.0)", 5], ["norm2(6.0, 8.0)", 10]] },
  { name: "user function call", src: `fn sq (x : Float) -> Float\nbody Float\n  x * x\nend sq\nfn quad (x : Float) -> Float\nbody Float\n  sq(sq(x))\nend quad`, check: "ok", evals: [["quad(2.0)", 16]] },
  { name: "toFloat / toInt", src: `fn f (n : Int) -> Float\nbody Float\n  toFloat(n) / 2.0\nend f`, check: "ok", evals: [["f(7)", 3.5]] },
  { name: "unbound variable", src: F("y + x"), check: "unbound" },
  { name: "wrong arg type", src: `fn f (x : Int) -> Float\nbody Float\n  sqrt(x)\nend f`, check: "type_mismatch" },

  // ── パース ──
  { name: "parse error missing paren", src: `fn f (x : Float) -> Float\nbody Float\n  sqrt(x\nend f`, parseErr: true },

  // ── List[T] ──
  { name: "list literal + length", src: `fn f (v : List[Float]) -> Int\nbody Int\n  length(v)\nend f`, check: "ok", evals: [["f([1.0, 2.0, 3.0])", 3], ["f([])", 0]] },
  { name: "list head/tail/get", src: `fn h (v : List[Int]) -> Int\nbody Int\n  get(v, 1)\nend h`, check: "ok", evals: [["h([10, 20, 30])", 20]] },
  { name: "list append", src: `fn a (v : List[Int], x : Int) -> List[Int]\nbody List[Int]\n  append(v, x)\nend a`, check: "ok", evals: [["length(a([1, 2], 3))", 3]] },
  { name: "dot / sum stdlib", src: `fn nsq (v : List[Float]) -> Float\nbody Float\n  dot(v, v)\nend nsq`, check: "ok", evals: [["nsq([3.0, 4.0])", 25], ["sum([1.0, 2.0, 2.0])", 5]] },
  { name: "length on non-list errors", src: `fn f (x : Int) -> Int\nbody Int\n  length(x)\nend f`, check: "type_mismatch" },
  { name: "append wrong elem type", src: `fn f (v : List[Int]) -> List[Int]\nbody List[Int]\n  append(v, 1.0)\nend f`, check: "type_mismatch" },
  { name: "heterogeneous list errors", src: `fn f () -> Int\nbody Int\n  length([1, 2.0])\nend f`, check: "type_mismatch" },

  // ── dogfood で判明: 再帰・前方参照は動く（両バックエンド）。ここで固定する ──
  { name: "recursion (factorial)", src: `fn fact (n : Int) -> Int\nbody Int\n  if(n <= 1, 1, n * fact(n - 1))\nend fact`, check: "ok", evals: [["fact(5)", 120], ["fact(0)", 1]] },
  { name: "forward reference", src: `fn a (x : Int) -> Int\nbody Int\n  b(x) + 1\nend a\nfn b (x : Int) -> Int\nbody Int\n  x\nend b`, check: "ok", evals: [["a(3)", 4]] },

  // ── 高階関数（v0.2）: ラムダ・関数値・map/filter/fold ──
  { name: "hof: fn-typed param + fn as value", src: `fn ap (f : (Float) -> Float, x : Float) -> Float\nbody Float\n  f(x)\nend ap\nfn dbl (x : Float) -> Float\nbody Float\n  x * 2.0\nend dbl`, check: "ok", evals: [["ap(dbl, 3.0)", 6]] },
  { name: "lambda + map", src: `fn sc (v : List[Float], k : Float) -> List[Float]\nbody List[Float]\n  map(v, fn (x : Float) => x * k)\nend sc`, check: "ok", evals: [["get(sc([1.0, 2.0, 3.0], 10.0), 1)", 20], ["length(sc([1.0], 2.0))", 1]] },
  { name: "fold (sum ints)", src: `fn total (v : List[Int]) -> Int\nbody Int\n  fold(v, 0, fn (acc : Int, x : Int) => acc + x)\nend total`, check: "ok", evals: [["total([1, 2, 3, 4])", 10], ["total([])", 0]] },
  { name: "filter", src: `fn pos (v : List[Float]) -> List[Float]\nbody List[Float]\n  filter(v, fn (x : Float) => x >= 0.0)\nend pos`, check: "ok", evals: [["length(pos([-1.0, 2.0, -3.0, 4.0]))", 2]] },
  { name: "map result type checked", src: `fn f (v : List[Float]) -> List[Float]\nbody List[Float]\n  map(v, fn (x : Float) => x >= 0.0)\nend f`, check: "type_mismatch" },
  { name: "map lambda param type mismatch", src: `fn f (v : List[Int]) -> List[Int]\nbody List[Int]\n  map(v, fn (x : Float) => x)\nend f`, check: "type_mismatch" },

  // ── Record（v0.3）──
  { name: "record literal + field access", src: `fn f () -> Float\nbody Float\n  let p : {x : Float, y : Float} = {x = 3.0, y = 4.0} in p.x + p.y\nend f`, check: "ok", evals: [["f()", 7]] },
  { name: "record as param and return", src: `fn mk (x : Float, y : Float) -> {x : Float, y : Float}\nbody {x : Float, y : Float}\n  {x = x, y = y}\nend mk\nfn dist (p : {x : Float, y : Float}, q : {x : Float, y : Float}) -> Float\n  eg dist(mk(0.0, 0.0), mk(3.0, 4.0)) = 5.0\nbody Float\n  sqrt((p.x - q.x) * (p.x - q.x) + (p.y - q.y) * (p.y - q.y))\nend dist`, check: "ok", contracts: "ok", evals: [["dist(mk(0.0, 0.0), mk(6.0, 8.0))", 10]] },
  { name: "nested record", src: `fn f (c : {center : {x : Float, y : Float}, r : Float}) -> Float\nbody Float\n  c.center.x + c.r\nend f`, check: "ok", evals: [["f({center = {x = 1.0, y = 2.0}, r = 10.0})", 11]] },
  { name: "record field order-insensitive", src: `fn f (p : {x : Float, y : Float}) -> Float\nbody Float\n  p.x\nend f`, check: "ok", evals: [["f({y = 2.0, x = 1.0})", 1]] },
  { name: "record field type mismatch", src: `fn f () -> Float\nbody Float\n  let p : {x : Float} = {x = 1} in p.x\nend f`, check: "type_mismatch" },
  { name: "unknown field", src: `fn f (p : {x : Float, y : Float}) -> Float\nbody Float\n  p.z\nend f`, check: "unknown_field" },
  { name: "missing field in literal", src: `fn f () -> Float\nbody Float\n  let p : {x : Float, y : Float} = {x = 1.0} in p.x\nend f`, check: "type_mismatch" },
  { name: "field access on non-record", src: `fn f (x : Float) -> Float\nbody Float\n  x.y\nend f`, check: "type_mismatch" },
  { name: "map over records", src: `fn xs (ps : List[{x : Float, y : Float}]) -> List[Float]\nbody List[Float]\n  map(ps, fn (p : {x : Float, y : Float}) => p.x)\nend xs`, check: "ok", evals: [["get(xs([{x = 1.0, y = 9.0}, {x = 2.0, y = 8.0}]), 1)", 2]] },
  { name: "eg with list value (deep equality)", src: `fn sc (v : List[Float]) -> List[Float]\n  eg sc([1.0, 2.0]) = [10.0, 20.0]\nbody List[Float]\n  map(v, fn (x : Float) => x * 10.0)\nend sc`, check: "ok", contracts: "ok" },

  // ── ラムダ引数の型注釈は任意（v0.3.2・AI生成実験の知見: 両モデルとも fn (acc, x) => と書く）──
  { name: "untyped lambda in map", src: `fn sc (v : List[Float], k : Float) -> List[Float]\nbody List[Float]\n  map(v, fn (x) => x * k)\nend sc`, check: "ok", evals: [["get(sc([1.0, 2.0], 10.0), 1)", 20]] },
  { name: "untyped lambda in fold", src: `fn total (v : List[Int]) -> Int\nbody Int\n  fold(v, 0, fn (acc, x) => acc + x)\nend total`, check: "ok", evals: [["total([1, 2, 3])", 6]] },
  { name: "untyped lambda in filter", src: `fn pos (v : List[Float]) -> List[Float]\nbody List[Float]\n  filter(v, fn (x) => x >= 0.0)\nend pos`, check: "ok", evals: [["length(pos([-1.0, 2.0]))", 1]] },
  { name: "untyped lambda via let (check position)", src: `fn f (y : Float) -> Float\nbody Float\n  let g : (Float) -> Float = fn (x) => x * 2.0 in g(y)\nend f`, check: "ok", evals: [["f(4.0)", 8]] },
  { name: "annotated lambda still works", src: `fn total (v : List[Int]) -> Int\nbody Int\n  fold(v, 0, fn (acc : Int, x : Int) => acc + x)\nend total`, check: "ok", evals: [["total([2, 3])", 5]] },
  { name: "wrong annotation vs expected", src: `fn f (v : List[Int]) -> List[Int]\nbody List[Int]\n  map(v, fn (x : Float) => x)\nend f`, check: "type_mismatch" },
  { name: "untyped lambda uninferable position", src: `fn f () -> Int\nbody Int\n  length([fn (x) => x])\nend f`, check: "type_mismatch" },

  // ── 構造等価（v0.3.1・dogfood第2ラウンドの H を修正）──
  { name: "list equality is structural", src: `fn f () -> Bool\nbody Bool\n  [1.0, 2.0] == [1.0, 2.0]\nend f`, check: "ok", evals: [["f()", true]] },
  { name: "record equality is structural", src: `fn f () -> Bool\nbody Bool\n  {x = 1.0, y = 2.0} == {x = 1.0, y = 2.0}\nend f`, check: "ok", evals: [["f()", true]] },
  { name: "structural inequality", src: `fn f () -> Bool\nbody Bool\n  [1.0, 2.0] != [1.0, 3.0]\nend f`, check: "ok", evals: [["f()", true]] },

  // ── 型エイリアス（v0.3.1・dogfood第2ラウンドの I）──
  { name: "type alias in signature and lambda", src: `type Point = {x : Float, y : Float}\nfn xs (ps : List[Point]) -> List[Float]\nbody List[Float]\n  map(ps, fn (p : Point) => p.x)\nend xs`, check: "ok", evals: [["get(xs([{x = 5.0, y = 0.0}]), 0)", 5]] },
  { name: "alias to alias", src: `type P = {x : Float}\ntype Q = P\nfn f (q : Q) -> Float\nbody Float\n  q.x\nend f`, check: "ok", evals: [["f({x = 3.0})", 3]] },
  { name: "unknown alias is parse error", src: `fn f (p : Pt) -> Float\nbody Float\n  1.0\nend f`, parseErr: true },

  // ── v0.4: 文字列 stdlib 拡張＋安全な既定値つき取得（dogfood 第3ラウンド）──
  { name: "toString int/float/bool", src: `fn f (n : Int) -> String\nbody String\n  toString(n)\nend f`, check: "ok", evals: [["f(42)", "42"], ['concat(toString(true), toString(1.5))', "true1.5"]] },
  { name: "toString rejects functions", src: `fn g (x : Int) -> Int\nbody Int\n  x\nend g\nfn f () -> String\nbody String\n  toString(g)\nend f`, check: "type_mismatch" },
  { name: "split + head", src: `fn firstWord (s : String) -> String\n  eg firstWord("hello world") = "hello"\nbody String\n  head(split(s, " "))\nend firstWord`, check: "ok", contracts: "ok", evals: [['firstWord("ai lang")', "ai"]] },
  { name: "join", src: `fn f (xs : List[String]) -> String\nbody String\n  join(xs, "-")\nend f`, check: "ok", evals: [['f(["a", "b", "c"])', "a-b-c"]] },
  { name: "contains / substring / trim", src: `fn f (s : String) -> Bool\nbody Bool\n  contains(trim(s), "food")\nend f\nfn g (s : String) -> String\nbody String\n  substring(s, 0, 3)\nend g`, check: "ok", evals: [['f("  food court ")', true], ['g("abcdef")', "abc"]] },
  { name: "headOr on empty", src: `fn f (v : List[Float]) -> Float\n  eg f([]) = 0.0\n  eg f([7.0]) = 7.0\nbody Float\n  headOr(v, 0.0)\nend f`, check: "ok", contracts: "ok" },
  { name: "getOr out of range", src: `fn f (v : List[Int], i : Int) -> Int\n  eg f([10, 20], 5) = -1\n  eg f([10, 20], 1) = 20\nbody Int\n  getOr(v, i, -1)\nend f`, check: "ok", contracts: "ok" },
  { name: "headOr default type mismatch", src: `fn f (v : List[Float]) -> Float\nbody Float\n  headOr(v, "zero")\nend f`, check: "type_mismatch" },

  // ── Option[T]（v0.5・dogfood probe M/N: parse不能＋find番兵の解消）──
  { name: "some + unwrapOr", src: `fn f (x : Float) -> Float\nbody Float\n  unwrapOr(some(x), 0.0)\nend f`, check: "ok", evals: [["f(5.0)", 5]] },
  { name: "none in let annotation", src: `fn f () -> Float\nbody Float\n  let o : Option[Float] = none in unwrapOr(o, -1.0)\nend f`, check: "ok", evals: [["f()", -1]] },
  { name: "isSome", src: `fn f (v : List[Float]) -> Bool\nbody Bool\n  isSome(find(v, fn (x) => x > 10.0))\nend f`, check: "ok", evals: [["f([5.0, 20.0])", true], ["f([1.0])", false]] },
  { name: "find returns Option", src: `fn firstBig (v : List[Float]) -> Float\n  eg firstBig([1.0, 50.0, 7.0]) = 50.0\n  eg firstBig([1.0]) = -1.0\nbody Float\n  unwrapOr(find(v, fn (x) => x > 10.0), -1.0)\nend firstBig`, check: "ok", contracts: "ok" },
  // evals を必ず併記（contracts はインタプリタのみ・evals は両バックエンドを通る。parseInt の \d エスケープ退行の検出用）
  { name: "parseInt some/none", src: `fn f (s : String) -> Int\n  eg f("42") = 42\n  eg f("abc") = 0\nbody Int\n  unwrapOr(parseInt(s), 0)\nend f`, check: "ok", contracts: "ok", evals: [['f("90")', 90], ['f("x9")', 0], ['f(" -7 ")', -7]] },
  { name: "parseFloat", src: `fn f (s : String) -> Float\nbody Float\n  unwrapOr(parseFloat(s), 0.0)\nend f`, check: "ok", evals: [['f("2.5")', 2.5], ['f("x")', 0]] },
  { name: "eg with option value", src: `fn f (v : List[Int]) -> Option[Int]\n  eg f([7]) = some(7)\n  eg f([]) = none\nbody Option[Int]\n  find(v, fn (x) => x > 0)\nend f`, check: "ok", contracts: "ok" },
  { name: "none needs context in synth", src: `fn f () -> Float\nbody Float\n  unwrapOr(none, 0.0)\nend f`, check: "type_mismatch" },
  { name: "unwrapOr default type mismatch", src: `fn f (s : String) -> Int\nbody Int\n  unwrapOr(parseInt(s), "zero")\nend f`, check: "type_mismatch" },
  { name: "isSome on non-option", src: `fn f (x : Int) -> Bool\nbody Bool\n  isSome(x)\nend f`, check: "type_mismatch" },
  { name: "option in record + alias", src: `type User = {name : String, age : Option[Int]}\nfn ageOr (u : User, d : Int) -> Int\nbody Int\n  unwrapOr(u.age, d)\nend ageOr`, check: "ok", evals: [['ageOr({name = "ai", age = some(3)}, 0)', 3], ['ageOr({name = "bo", age = none}, 99)', 99]] },

  // ── v0.5.1: fold への期待型伝播・[] の check 規則・String の +（dogfood 第5ラウンド）──
  { name: "fold with [] init", src: `fn evens (v : List[Int]) -> List[Int]\n  eg evens([1, 2, 3, 4]) = [2, 4]\nbody List[Int]\n  fold(v, [], fn (acc, x) => if(x / 2 * 2 == x, append(acc, x), acc))\nend evens`, check: "ok", contracts: "ok", evals: [["length(evens([2, 4, 5]))", 2]] },
  { name: "fold with none init", src: `fn maxOpt (v : List[Float]) -> Option[Float]\n  eg maxOpt([3.0, 9.0, 1.0]) = some(9.0)\n  eg maxOpt([]) = none\nbody Option[Float]\n  fold(v, none, fn (acc, x) => if(isSome(acc), if(x > unwrapOr(acc, x), some(x), acc), some(x)))\nend maxOpt`, check: "ok", contracts: "ok" },
  { name: "empty list literal as arg", src: `fn n (v : List[Float]) -> Int\nbody Int\n  length(v)\nend n\nfn f () -> Int\nbody Int\n  n([])\nend f`, check: "ok", evals: [["f()", 0]] },
  { name: "string + concatenation", src: `fn hello (name : String) -> String\n  eg hello("ai") = "hello, ai!"\nbody String\n  "hello, " + name + "!"\nend hello`, check: "ok", contracts: "ok", evals: [['hello("x")', "hello, x!"]] },
  { name: "string + with toString", src: `fn label (n : Int) -> String\nbody String\n  "n=" + toString(n)\nend label`, check: "ok", evals: [["label(42)", "n=42"]] },
  { name: "+ rejects string minus", src: `fn f (s : String) -> String\nbody String\n  s - "x"\nend f`, check: "type_mismatch" },
  { name: "+ mixed string/int rejected", src: `fn f (s : String) -> String\nbody String\n  s + 1\nend f`, check: "type_mismatch" },

  // ── v0.5.2: map が Option にも効く（A3 実測: Haiku/Opus 両方が1手目にこの形を書いた）──
  { name: "map over some", src: `fn f (x : Float) -> Option[Float]\n  eg f(3.0) = some(6.0)\nbody Option[Float]\n  map(some(x), fn (v) => v * 2.0)\nend f`, check: "ok", contracts: "ok", evals: [["unwrapOr(f(2.0), 0.0)", 4]] },
  { name: "map over none stays none", src: `fn f () -> Option[Int]\n  eg f() = none\nbody Option[Int]\n  let o : Option[Int] = none in map(o, fn (v) => v + 1)\nend f`, check: "ok", contracts: "ok", evals: [["isSome(f())", false]] },
  { name: "map over find (A3 shape)", src: `type Expense = {amount : Float, cat : String}\nfn nameFirstBig (es : List[Expense], lim : Float) -> String\n  eg nameFirstBig([{amount = 3.0, cat = "food"}, {amount = 200.0, cat = "travel"}], 100.0) = "travel"\n  eg nameFirstBig([], 5.0) = "none"\nbody String\n  unwrapOr(map(find(es, fn (e) => e.amount > lim), fn (e) => e.cat), "none")\nend nameFirstBig`, check: "ok", contracts: "ok", evals: [[`nameFirstBig([{amount = 150.0, cat = "a"}], 100.0)`, "a"]] },
  { name: "map on non-list-non-option errors", src: `fn f (x : Int) -> Int\nbody Int\n  head(map(x, fn (v) => v))\nend f`, check: "type_mismatch" },

  // ── String ──
  { name: "string concat + strlen", src: `fn f (s : String) -> Int\nbody Int\n  strlen(concat(s, "!"))\nend f`, check: "ok", evals: [['f("hi")', 3]] },
  { name: "string literal eval", src: `fn greet (name : String) -> String\nbody String\n  concat("hello ", name)\nend greet`, check: "ok", evals: [['greet("ai")', "hello ai"]] },

  // ── 契約 ──
  { name: "contract eg passes", src: `fn norm (v : Float, w : Float) -> Float\n  ensures ret >= 0.0\n  eg norm(3.0, 4.0) = 5.0\nbody Float\n  sqrt(v * v + w * w)\nend norm`, check: "ok", contracts: "ok" },
  { name: "contract eg fails (wrong body)", src: `fn norm (v : Float, w : Float) -> Float\n  eg norm(3.0, 4.0) = 5.0\nbody Float\n  v * v + w * w\nend norm`, check: "ok", contracts: "fail" },
];

// ───────────────────────── ランナー ─────────────────────────

function runCase(c: Case): { pass: boolean; msg: string } {
  // parse
  let prog;
  try { prog = parseProgram(c.src); }
  catch (e: any) {
    if (c.parseErr) return { pass: true, msg: "parse error (期待通り)" };
    return { pass: false, msg: `想定外のパースエラー: ${e.message}` };
  }
  if (c.parseErr) return { pass: false, msg: "パースエラーを期待したが通った" };

  // check
  const r = check(prog);
  if (c.check === "ok") {
    if (!r.ok) return { pass: false, msg: `型検査失敗を検出: ${r.errors.map((e) => e.code).join(",")}` };
  } else if (c.check) {
    if (r.ok) return { pass: false, msg: `診断 ${c.check} を期待したが ok` };
    if (!r.errors.some((e) => e.code === c.check)) return { pass: false, msg: `診断 ${c.check} を期待したが [${r.errors.map((e) => e.code).join(",")}]` };
    return { pass: true, msg: `診断 ${c.check} (期待通り)` };
  }

  // evals — インタプリタと JS バックエンドの両方で検証（二重実装・一つのテスト群）
  const eq = (got: any, want: any) => typeof got === "number" && typeof want === "number" ? Math.abs(got - want) <= 1e-9 : got === want;
  for (const [expr, want] of c.evals ?? []) {
    let got: any; try { got = evalInProgram(prog, expr); } catch (e: any) { return { pass: false, msg: `評価エラー ${expr}: ${e.message}` }; }
    if (!eq(got, want)) return { pass: false, msg: `[interp] ${expr} = ${got}, 期待 ${want}` };
    let js: any; try { js = runJs(prog, expr); } catch (e: any) { return { pass: false, msg: `JSバックエンド実行エラー ${expr}: ${e.message}` }; }
    if (!eq(js, want)) return { pass: false, msg: `[js] ${expr} = ${js}, 期待 ${want}（インタプリタと不一致）` };
  }

  // contracts
  if (c.contracts) {
    const viol = runContracts(prog);
    if (c.contracts === "ok" && viol.length > 0) return { pass: false, msg: `契約違反: ${JSON.stringify(viol)}` };
    if (c.contracts === "fail" && viol.length === 0) return { pass: false, msg: `契約違反を期待したが無し` };
  }

  return { pass: true, msg: "" };
}

let pass = 0, fail = 0;
console.log("════════ Ailex v0.1 conformance tests ════════");
for (const c of CASES) {
  const r = runCase(c);
  if (r.pass) { pass++; console.log(`  ✓ ${c.name}${r.msg && !r.msg.includes("期待通り") ? "" : r.msg ? "  (" + r.msg + ")" : ""}`); }
  else { fail++; console.log(`  ✗ ${c.name} — ${r.msg}`); }
}
console.log("──────────────────────────────────────────────");
console.log(`  ${pass}/${CASES.length} passed${fail ? `, ${fail} FAILED` : " ✅"}`);
if (fail) process.exit(1);
