# Ailex 言語仕様 v0.1

> AI（LLM）が書き手、人間が読み手の中間言語。実行時は host（JS）へ transpile する。
> 設計思想は [LANGUAGE.md](LANGUAGE.md)、その根拠となる実測は [EXPERIMENTS.md](EXPERIMENTS.md)。
> 本書は**実装可能な完全仕様**。現行実装との差分は §12。

---

## 1. 設計不変条件（実装が守るべき性質）

1. **正規形の一意性**: 意味が等しい2プログラムの L1 表現は byte 一致する。
2. **文脈適合の小ささ**: 本仕様＋stdlib 一覧が単一プロンプトに収まる規模を保つ。
3. **単調型付け**: 宣言（型・契約）は本体に前置。（注: v0.1 実装は全関数を先にスコープ登録するため**前方参照・再帰は可**。dogfood で確認・[DOGFOOD.md](DOGFOOD.md)。当初の「依存順・非再帰」は撤回。）
4. **決定性**: 同じプログラムは同じ結果。v0.1 に副作用・IO はない（純粋）。
5. **LLM の事前分布に沿う**: 中置算術・標準的な優先順位を採用（実測 Q1 の教訓）。

---

## 2. 字句構造（Lexical）

- **コメント**: `--` から行末まで。
- **識別子**: `[A-Za-z_][A-Za-z0-9_]*`。予約語を除く。
- **予約語**: `fn end body let in if group sig requires ensures eg true false Int Float Bool String List`。
- **整数リテラル**: `[0-9]+`（先頭 `-` は単項マイナス演算子で処理）。例 `0` `42`。
- **浮動小数リテラル**: `[0-9]+\.[0-9]+`。例 `1.0` `3.14`。
- **文字列リテラル**: `"` … `"`。エスケープ `\n \t \" \\`。
- **真偽リテラル**: `true` `false`。
- **演算子・区切り**: `+ - * / >= <= > < == != && || ! ( ) [ ] , : -> =`。
- 空白・改行はトークン区切り。意味を持たない（正規形はフォーマッタが決める）。

---

## 3. 型（Types）

| 型 | 意味 | JS 表現 |
|---|---|---|
| `Int` | 数学的整数（v0.1 は JS safe-integer 範囲、範囲外は未定義動作） | `number` |
| `Float` | IEEE 754 倍精度 | `number` |
| `Bool` | 真偽 | `boolean` |
| `String` | 不変 UTF-8 文字列 | `string` |
| `List[T]` | 不変・同型要素の列 | 凍結 `Array` |
| `(T1, …, Tn) -> R` | 関数 | JS 関数 |

- **null は無い。** 欠如は v0.2 の `Option[T]` で表す。
- **暗黙変換なし。** `Int` と `Float` は混ぜられない（`toFloat`/`toInt` で明示）。
- **型の同一性は構造的。** `List[Int]` と `List[Int]` は同一。

---

## 4. 文法（Grammar, EBNF）

```ebnf
program     = { fn } ;
fn          = "fn" ident "(" [ params ] ")" "->" type
              { contract }
              "body" type expr
              "end" ident ;
params      = param { "," param } ;
param       = ident ":" type ;
contract    = ("requires" | "ensures") expr
            | "eg" expr "=" expr ;

type        = "Int" | "Float" | "Bool" | "String"
            | "List" "[" type "]"
            | "(" [ type { "," type } ] ")" "->" type ;

expr        = "let" ident ":" type "=" expr "in" expr
            | "if" "(" expr "," expr "," expr ")"
            | or ;
or          = and { "||" and } ;
and         = cmp { "&&" cmp } ;
cmp         = add [ ("==" | "!=" | ">=" | "<=" | ">" | "<") add ] ;
add         = mul { ("+" | "-") mul } ;
mul         = unary { ("*" | "/") unary } ;
unary       = [ "-" | "!" ] app ;
app         = atom [ "(" [ args ] ")" ] ;
args        = expr { "," expr } ;
atom        = int | float | string | "true" | "false"
            | ident
            | "[" [ args ] "]"
            | "(" expr ")" ;
```

- **`body T`** は戻り型を本体直前で再掲する（冗長性 = 生成器の錨。設計上の意図）。
- `if` は式（三項）。文はない。すべて式指向。
- `let x : T = e1 in e2` は局所束縛（v0.1 は型注釈必須）。
- 演算子優先順位（低→高）: `||` < `&&` < 比較 < `+ -` < `* /` < 単項 `- !` < 適用。左結合。

---

## 5. 型付け規則（双方向）

判定は「式 e が型 T を **検査(check)** に通る」/「式 e が型 T を **合成(synth)** する」の2種。

**合成（synth）**:
- 整数リテラル ⟹ `Int`／浮動 ⟹ `Float`／文字列 ⟹ `String`／`true|false` ⟹ `Bool`。
- 変数 `x` ⟹ スコープの束縛型（未束縛は構造化エラー `unbound`）。
- 適用 `f(a1..an)`: `f` が `(P1..Pn)->R` に synth し、各 `ai` を `Pi` に check ⟹ `R`。`f` が関数型でなければ `not_a_function`。
- 算術 `a ⊕ b`（`⊕∈{+,-,*,/}`）: 両辺を同一の数値型（`Int` か `Float`）に要求 ⟹ その型。混在は `type_mismatch`。
- 比較 `a ⊗ b`（`⊗∈{==,!=,>,>=,<,<=}`）: 両辺同型 ⟹ `Bool`。`== !=` は任意の同型、大小は数値のみ。
- 論理 `a && b` / `a || b` / `!a`: 各辺 `Bool` に check ⟹ `Bool`。
- 単項 `-a`: `a` を数値型に synth ⟹ 同型。

**検査（check）** の特別扱い（多相・双方向の要）:
- `if(c, t, e)` を `T` に check: `c` を `Bool` に、`t` と `e` を各々 `T` に check。
- `let x:S = e1 in e2` を `T` に check: `e1` を `S` に check、`x:S` を加えて `e2` を `T` に check。
- リスト `[e1..en]` を `List[T]` に check: 各 `ei` を `T` に check。空 `[]` は check 位置の要求型を採る（synth 位置では型不定エラー）。
- 上記以外の式 e を `T` に check: `e` を synth した型 `S` と `T` が同一かを見る（不一致は `type_mismatch`）。

関数 `fn f(..)->R body R e end f`: 本体 `e` を `R` に check。`ensures`/`eg` は §7。

---

## 6. 評価意味論（Operational・call-by-value・eager）

- リテラルはその値。変数は環境から。
- `f(a1..an)`: 引数を左から評価し、関数（stdlib or ユーザ定義）を適用。
- ユーザ定義 `f` の適用: 仮引数を実引数に束縛し本体を評価。
- `if(c,t,e)`: `c` を評価し `true` なら `t`、さもなくば `e`（短絡）。
- `let x=e1 in e2`: `e1` を評価して `x` に束縛し `e2` を評価。
- 算術・比較・論理は host 意味論（`/` は `Int` では整数除算=切り捨て、0 除算は実行時エラー）。
- 純粋・決定的。同入力→同出力。

---

## 7. 契約（Contracts）

- `requires e`: 事前条件（`Bool` 式・引数を参照可）。v0.1 は宣言のみ（実行時 assert は v0.2）。
- `ensures e`: 事後条件（`Bool` 式・戻り値を `ret` で参照）。`eg` 評価時に併せて検査。
- `eg call = value`: 実行可能な実例。`call` を評価した結果が `value` と一致することを検査（許容誤差 Float は 1e-9）。同時に `ensures` を `ret=結果` の下で検査。
- 契約違反は構造化エラー（§9）で報告。型検査を通ったコードのみ契約検査に進む。

---

## 8. 標準ライブラリ（v0.1・暗黙にスコープ内）

宣言不要で使える。**組み込み関数はパラメトリック多相を許す**（ユーザ定義の多相は v0.2。Go の `len`/`append` と同じ扱い）。

**数値** `+ - * /`（`(Int,Int)->Int` / `(Float,Float)->Float`）, 単項 `-`,
`abs`, `min`, `max`（数値, 同型2引数→同型）, `sqrt : (Float)->Float`,
`toFloat : (Int)->Float`, `toInt : (Float)->Int`（切り捨て）.
**比較** `== != > >= < <=` → `Bool`. **論理** `&& || !`.
**リスト** `length : (List[T])->Int`, `get : (List[T], Int)->T`（範囲外は実行時エラー）,
`head : (List[T])->T`, `tail : (List[T])->List[T]`, `append : (List[T], T)->List[T]`,
`dot : (List[Float], List[Float])->Float`, `sum : (List[Float])->Float`.
**文字列** `strlen : (String)->Int`, `concat : (String, String)->String`.

> v0.1 に高階関数（`map`/`fold`/ラムダ）は無い。リスト処理は上記の一次関数のみ（v0.2 で HOF）。

---

## 9. 構造化診断（コンパイラの唯一の出力形式）

コンパイラ／検証器は**英文でなく構造化データ**を返す（英文は L2 投影として別途生成可）。スキーマ:

```
{ ok: false,
  errors: [ { code, at: <ノードID>, ... } ] }
```

`code` と付随フィールド:
- `parse` : `{ detail }`
- `unbound` : `{ name, scope: [{name, type}] }`
- `not_a_function` : `{ name, scope: [...] }`
- `type_mismatch` : `{ expected, actual, scope: [...] }`
- `hole` : `{ name, expected, scope: [...] }`（未完成な式）
- `contract` : `{ kind: "ensures"|"eg", call, expected, actual }`

**`scope` は名前と型の一覧を必ず含む**（実測 Q1/Q1b: 回復に最も効いた情報）。

---

## 10. AI 向け言語機能（第一級）

- **`ailex scope <file> <pos>`**: 位置 pos のスコープ内の名前と型を機械可読で返す。
- **`ailex fmt <file>`**: L1 正規形へ一意化（優先順位・空白・順序を規定形に）。違反はエラーでなく正規化。
- **`ailex check <file>`**: 型＋契約検査 → §9 の構造化診断。
- **`ailex run <file>`** / **`ailex build <file>`**: §11 で JS へ落として実行 / 出力。
- 本仕様は単一ファイルで、生成器のプロンプトに丸ごと入れて in-context 学習に使える規模を維持する。

---

## 11. 実行モデル（L0 → JavaScript lowering）

Ailex は中間言語。L0（型付きグラフ）から JS へ transpile して実行する。対応:

| Ailex | JS |
|---|---|
| `Int`/`Float` | `number` ／ `Bool` | `boolean` ／ `String` | `string` |
| `List[T]` | `Object.freeze([...])` |
| `fn f(x:T)->R body R e end` | `const f = (x) => <e>;` |
| `f(a,b)` | `f(a, b)` |
| `if(c,t,e)` | `(c ? t : e)` |
| `let x:T=e1 in e2` | `((x) => <e2>)(<e1>)`（または IIFE/const） |
| 算術・比較・論理 | 同名の JS 演算子（`Int` の `/` は `Math.trunc(a/b)`） |
| stdlib | `ailex_rt` ランタイム（`length`→`a.length` 等の薄いラッパ） |

将来、同じ L0 から Python / WASM ターゲット（多言語 lowering）＝「中間」言語たる所以。FFI（host 関数の型付き import）は v0.2。

---

## 12. 現行実装との差分（v0.1 実装で埋める）

現行 [prototype.ts](prototype.ts) 他: パーサ／双方向型検査／評価器／L1・L2／`if`／関数／`Float`・`Vec Float`／リテラル／契約／スコープ提示／構造化フィードバック／マスク生成。

**v0.1 で変える/足す:**
1. `Vec Float` を廃し **`List[T]`** に一般化。`Int` `String` `Bool` 演算を追加。
2. **中置演算子** `+ - * / && || ! == != > >= < <=` と優先順位（現状は `>=` と関数呼びのみ）。
3. **`let ... in`**。
4. `group`/`sig` 宣言を廃し、**stdlib を暗黙スコープ**に（§8）。ユーザ関数は `fn` のみ。
5. **JS lowering バックエンド**（現状は TS インタプリタ）。
6. `scope` / `fmt` / `check` / `run` を **CLI コマンド**化。

**v0.1 でやらないこと**: ユーザ定義多相・`Record`・`Option`・effect/IO・FFI 構文・モジュール/パッケージ。
（**再帰**は実装で自然に可能と判明したのでサポート。dogfood 参照。）

**v0.2 で追加済み（2026-07-10）**: **高階関数**。無名関数 `fn (x : T) => e`、第一級関数値（インタプリタ・JS 両対応・健全）、
`map`/`filter`/`fold`（多相組み込み）。[DOGFOOD.md](DOGFOOD.md) §C/D/E、`examples/lists.ax`。
未対応の即時ラムダ呼び `(fn (x) => e)(3)` は無し（ラムダは引数か `let` 経由で使う）。

**v0.3 で追加済み（2026-07-10）**: **レコード（構造的）**。
- 型 `{x : Float, y : Float}`（構造的同一性・フィールド順不問。正規形の表示は名前順）
- リテラル `{x = 1.0, y = 2.0}`、フィールドアクセス `p.x`（後置・連鎖可 `c.center.x`）
- 検査: 期待レコード型に対しフィールドの過不足を報告。未知フィールドは `unknown_field` 診断で**使えるフィールド一覧を開示**
- JS lowering: オブジェクトリテラル / `.name` アクセス
- 契約 `eg` の判定を**深い等価**（`valEq`: 数値は誤差 1e-9・リスト/レコードは構造比較）に変更（リストを返す eg の潜在バグも修正）
- [DOGFOOD.md](DOGFOOD.md) §F、`examples/points.ax`（重心・円内判定）。conformance 46/46。

**v0.5.2 で追加済み（2026-07-13・AI実測 A3 が決めた）**:
- **`map` を Option に多重定義**: `map(o, f) : (Option[T], (T)->U) -> Option[U]`（some なら適用・none はそのまま）。
- 動機: A3（16タスク）で Haiku/Opus の唯一の失敗が同一タスク・同一原因——**両モデルとも `map(find(...), fn (e) => e.cat)` と書いた**（Rust の opt.map / Haskell fmap の事前分布）。3ラウンドの型フィードバックでも番兵ピーク形には辿り着かず。言語側を直せば両モデルの1手目がそのまま正解になる（A1→A2 と同型の判断）。
- conformance 89/89（A3 の形そのままのケースを含む）。

**v0.5.1 で追加・修正済み（2026-07-12・dogfood 第5ラウンド＝成績表を書いた痛点が決めた）**:
- **fold への期待型伝播**（双方向の強化）: check 位置の `fold(v, init, f)` は期待型を初期値へ伝える。`fold(lines, [], ...)`・`fold(ss, none, ...)` が自然に書ける（従来は「空リスト(型不定)」で拒否→ラムダ注釈必須へ連鎖）。
- **`[]` の check 規則**: 期待型が `List[T]` の位置なら空リストに型が付く（引数位置・`eg parseAll([]) = []` も可）。
- **String の `+`**: 文字列連結を `+` で（`concat` の4重ネスト解消。モデルの事前分布とも一致。`-`/数値との混在は従来どおり拒否）。
- **バックエンド不一致の修正**: JS 側 `parseInt` の正規表現がテンプレートリテラルの `\d` エスケープ化けで常に none を返していた（eg=インタプリタは通るが main()=JS で壊れる、を dogfood が検出）。conformance に JS 経路の evals を追加して固定。
- 実証: `examples/gradebook.ax`（行解析→集計→レポート、eg 9件）。conformance 85/85。

**v0.5 で追加済み（2026-07-12・probe M/N＝「parse が書けない」「find に番兵が要る」が決めた）**:
- **`Option[T]`**: 安全な不在。`some(x)` / `none`・`isSome(o)`・`unwrapOr(o, default)`。
- `none` は **check 位置でのみ**型が付く（双方向。`let` 注釈・`if` のもう一方の枝・Option を期待する引数など。文脈が無い synth 位置は診断で誘導）。
- **失敗しうる stdlib は Option を返す**: `find(v, 述語) -> Option[T]`、`parseInt(s) -> Option[Int]`、`parseFloat(s) -> Option[Float]`。
- 実行時表現は `{has, val}`（両バックエンド一致）。`eg f([]) = none` のような Option 値の契約も深い等価で判定。
- パターンマッチは入れない（`isSome`＋`unwrapOr` で v0.5 の範囲は足りる。match は将来の候補）。
- 実証: `examples/option.ax`。conformance 78/78。受け入れ（aigen Haiku）8/8 pass@1 退行なし。

**v0.4 で追加・修正済み（2026-07-11・dogfood 第3ラウンド＝テキスト処理の probe が決めた）**:
- **文字列 stdlib**: `split(s, sep) -> List[String]`、`join(xs, sep)`、`contains(s, t)`、`substring(s, i, j)`、`trim(s)`、`toString(Int|Float|Bool|String) -> String`（多相・関数は型検査で拒否）。
- **安全な既定値つき取得**: `headOr(v, default)`、`getOr(v, i, default)`（多相）。`head`/`get` は従来どおり実行時エラー（完全な `Option[T]` は将来）。
- **CLI の実行時エラーを構造化**: `run` の `main()` が実行時エラーでもクラッシュせず `{code: "runtime", at, detail}` を返す。
- 実証: `examples/words.ax`。conformance 67/67。[DOGFOOD.md](DOGFOOD.md) 第3ラウンド §J/K/L。

**v0.3.2 で追加・修正済み（2026-07-11・AI生成実験 A1 の実測が決めた）**:
- **ラムダの型注釈を任意化**: `fn (acc, x) => acc + x` が期待型の分かる位置（map/filter/fold の引数等）で書ける。期待関数型からパラメータ型を推論し、注釈があれば照合する。
- 動機: 実測 A1 で Haiku/Opus の pass@1 失敗が**全て**「JS/Python の習慣による注釈なしラムダ→parse エラー」だった。言語側を直して再測定した A2 で両モデル pass@1 100%（[EXPERIMENTS.md](EXPERIMENTS.md) §A）。
- **モデルの事前分布と喧嘩しない構文**を第一級の設計制約とする（中置演算子と同型の判断）。conformance 59/59。

**v0.3.1 で追加・修正済み（2026-07-11・dogfood 第2ラウンド）**:
- **構造等価**: `==`/`!=` はリスト/レコードを**深く比較**する（数値は厳密・関数は参照）。従来は参照比較で `[1.0] == [1.0]` が false になる意味論バグだった（両バックエンド修正・一致）。契約 `eg` の判定（数値許容誤差 1e-9）とは区別する。
- **型エイリアス**: `type Expense = {name : String, amount : Float, cat : String}`。透明（展開される・表示も展開形）。宣言は使用に先行。alias-to-alias 可。`examples/ledger.ax`。
- conformance 52/52。

---

## 付録: 例（v0.1 で書けるもの）

```
fn norm (v : List[Float]) -> Float
  ensures ret >= 0.0
  eg norm([3.0, 4.0]) = 5.0
body Float
  sqrt(dot(v, v))
end norm

fn clampPos (x : Float) -> Float
  eg clampPos(-2.0) = 0.0
  eg clampPos(3.0) = 3.0
body Float
  if(x >= 0.0, x, 0.0)
end clampPos

fn scaledSum (a : Float, b : Float, k : Float) -> Float
  eg scaledSum(2.0, 3.0, 10.0) = 50.0
body Float
  let s : Float = a + b in s * k
end scaledSum
```
