# Ailex Primer（AI 向け正典・v0.5）

> この文書はそのまま LLM のシステムプロンプト/コンテキストに入れて使う。
> これが言語の全機能である（ここに無い構文・関数は存在しない）。
> 実測では、この早見表だけの in-context 学習で Haiku 4.5 / Opus 4.8 が本体式を pass@1 100% で書けた（EXPERIMENTS.md §A2）。

## プログラムの形

```
type Point = {x : Float, y : Float}          -- 型エイリアス（使用より前に宣言）

fn dist (p : Point, q : Point) -> Float      -- 関数宣言
  ensures ret >= 0.0                          -- 契約: 戻り値の性質（ret が戻り値）
  eg dist({x = 0.0, y = 0.0}, {x = 3.0, y = 4.0}) = 5.0   -- 契約: 実行される実例
body Float                                    -- 本体の型を再掲
  sqrt((p.x - q.x) * (p.x - q.x) + (p.y - q.y) * (p.y - q.y))
end dist
```

- 本体は**式1つ**。`return` や文は無い。
- コメントは `--` から行末まで。
- `eg` は実行され、間違っていると契約違反として報告される。境界値（0・空・負数）を含めるとよい。
- 再帰・前方参照は可。`main () -> T` があれば `run` で実行される。

## 型

`Int` / `Float` / `Bool` / `String` / `List[T]` / `Option[T]` / レコード `{x : Float, y : Float}` / 関数 `(T) -> U`

- **Int と Float は混在不可**。`toFloat(i)` / `toInt(f)` で明示変換（`toInt` は切り捨て）。
- リテラル: `1`（Int）、`1.0`（Float）、`true`、`"s"`、`[1.0, 2.0]`、`{x = 1.0, y = 2.0}`
- レコードは構造的（フィールド順不問）。アクセスは `p.x`（連鎖可 `c.center.x`）。

## 式

- 演算子: `+ - * /`（`/` は Int で切り捨て）、比較 `== != > >= < <=`、論理 `&& || !`
  - `==` はリスト・レコードも**深く**比較する
- 分岐は式: `if(cond, then, else)`
- 束縛: `let x : T = 式 in 式`
- 無名関数: `fn (x) => x * 2.0`（型注釈は任意。`fn (x : Float) => ...` も可）

## 組み込み関数（これが全て）

| 分類 | 関数 |
|---|---|
| 数値 | `sqrt(Float)->Float`, `toFloat(Int)->Float`, `toInt(Float)->Int` |
| リスト | `length(v)->Int`, `get(v,i)->T`, `head(v)->T`, `tail(v)->List[T]`, `append(v,x)->List[T]` |
| 安全な取得 | `headOr(v, default)->T`, `getOr(v, i, default)->T`（空/範囲外なら default） |
| 高階 | `map(v, f)`（**List にも Option にも効く**）, `filter(v, 述語)`, `fold(v, 初期値, fn (acc, x) => ...)` |
| 数値リスト | `dot(a, b)->Float`, `sum(v)->Float`（List[Float] 用） |
| 文字列 | `strlen`, `concat(s,t)`, `split(s,sep)->List[String]`, `join(xs,sep)`, `contains(s,t)->Bool`, `substring(s,i,j)`, `trim(s)`, `toString(数値/Bool/String)->String` |
| Option | `some(x)->Option[T]`, `none`, `isSome(o)->Bool`, `unwrapOr(o, default)->T`, `find(v, 述語)->Option[T]`, `parseInt(s)->Option[Int]`, `parseFloat(s)->Option[Float]` |

- `head`/`get` は空・範囲外で**実行時エラー**。避けたいときは `headOr`/`getOr`。
- **失敗しうる操作は Option を返す**（`find`/`parseInt`/`parseFloat`）。値の取り出しは `unwrapOr(o, 既定値)`。
- `none` は型が文脈から分かる位置でだけ書ける（`let o : Option[Int] = none`、`if(c, some(x), none)`、Option を期待する引数など）。

## よくある書き方

```
fold(xs, 0.0, fn (acc, x) => acc + x)                 -- 合計
length(filter(v, fn (x) => x < 0.0))                  -- 条件を満たす個数
map(ps, fn (p) => p.x)                                -- レコードのリストから射影
fold(es, 0.0, fn (a, e) => if(e.amount > a, e.amount, a))  -- 最大値
join(split(trim(s), " "), "-")                        -- 単語区切りを - に
unwrapOr(parseInt(s), 0)                              -- 文字列→Int（失敗は 0）
"n=" + toString(n) + "!"                              -- 文字列は + で連結
fold(lines, [], fn (acc, x) => append(acc, x))        -- fold の初期値に [] や none を書ける
unwrapOr(find(es, fn (e) => e.amount > 100.0), fallback)   -- 条件で探す（番兵不要）
unwrapOr(map(find(es, p), fn (e) => e.cat), "none")   -- 見つけて変換（Option の map）
```

## 検査と診断（ツール向け）

- `ailex check f.ax` → 構造化 JSON 診断。型エラーは**スコープ（使える名前と型の一覧）**を含む。
  未知フィールドは**使えるフィールド一覧**を含む。実行時エラーも `{code: "runtime", detail}`。
- `ailex scope f.ax [関数名]` → その位置で使える名前と型（機械可読）。
- `ailex run f.ax` → 型＋契約検査のうえ JS に変換して実行。
- 診断を読んで直すときは、**scope / fields に列挙された名前だけ**を使うこと（それ以外は存在しない）。
