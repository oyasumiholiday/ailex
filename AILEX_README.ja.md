# Ailex

[English README](README.md)

**AI が書くために設計した、小さな型付き言語。** 契約（実行される実例）・スコープを開示する構造化診断・検証済み2バックエンド（インタプリタ＋ JavaScript）。

```
type Point = {x : Float, y : Float}

fn dist (p : Point, q : Point) -> Float
  ensures ret >= 0.0
  eg dist({x = 0.0, y = 0.0}, {x = 3.0, y = 4.0}) = 5.0
body Float
  sqrt((p.x - q.x) * (p.x - q.x) + (p.y - q.y) * (p.y - q.y))
end dist
```

`eg` は飾りではなく**実行される契約**。`ailex run` が検査し、破れば構造化診断で報告する。

## なぜ AI 向けか（全部、実測に根拠がある）

1. **診断が「何が使えるか」を開示する。** 型エラーはスコープ（名前と型の一覧）、未知フィールドは使えるフィールド一覧を含む JSON。LLM の修復実験で、この開示が未知 API の名前当て発散を一手修正に変えた（pass@k 80%→98–100%、[EXPERIMENTS.md](EXPERIMENTS.md) §Q1）。
2. **構文はモデルの事前分布と喧嘩しない。** 中置演算子、注釈任意のラムダ `fn (acc, x) => ...`。ラムダ注釈を必須にしていた頃、実測の失敗は**すべて**その parse エラーだった。言語側を直して再測定したら Haiku/Opus とも pass@1 50–63%→**100%**（§A1→A2）。
3. **契約＝実行される実例。** 仕様の最小単位を `eg` として関数に同居させ、常に検査する。
4. **在ることが分かっている挙動。** 2つのバックエンド（インタプリタ／JS 変換）が同一の適合テスト 89 件で常時一致検証される。`==` はリスト・レコードを深く比較し、実行時エラーも構造化診断で返る。

早見表 1 枚（[PRIMER.md](PRIMER.md)）をコンテキストに入れるだけで、Haiku 4.5 と Opus 4.8 が 16/16 タスク（Option・レコード・文字列処理を含む）を一発で書けた。それがこの言語の受け入れテストである。

## 使う

Node.js 23 以上（.ts 直接実行）。

```sh
node core/cli.ts run examples/points.ax     # 検査 → JS に変換して実行
node core/cli.ts check file.ax              # 型＋契約検査 → 構造化診断(JSON)
node core/cli.ts scope file.ax dist         # その位置で使える名前と型(JSON)
node core/cli.ts fmt file.ax                # 正規形へ整形
node core/cli.ts emit-js file.ax            # 生成される JavaScript を表示
# リポジトリ内なら ./ailex run ... too。npm bin としては bin/ailex.js（npm i -g / npx 用意済み・未公開）
```

テスト: `npm test`（適合テスト 89 件・両バックエンドの一致まで検証）。

## 言語の中身（v0.5.3）

型 `Int / Float / Bool / String / List[T] / Option[T] / {レコード} / (T)->U`、型エイリアス、中置演算子、`if` 式、`let..in`、再帰、無名関数（注釈任意）、`map/filter/fold`、文字列 stdlib（`split/join/contains/substring/trim/toString`）、安全な取得（`headOr/getOr`）、`Option[T]`（`some/none/isSome/unwrapOr` と Option を返す `find/parseInt/parseFloat`）、契約（`requires/ensures/eg`）。全機能は [PRIMER.md](PRIMER.md)、設計と履歴は [SPEC.md](SPEC.md)。

## 正直な現状

- 研究プロトタイプから言語リリースへ移行中の**個人プロジェクト**。API は安定していない。
- 未対応: effect/IO・モジュール・パターンマッチ・即時ラムダ呼び・ユーザ定義多相。`head/get` は空/範囲外で実行時エラー（`headOr/getOr`・`find` を推奨）。
- 設計判断はすべて実測かドッグフーディングに根拠を持たせている（[DOGFOOD.md](DOGFOOD.md)・[EXPERIMENTS.md](EXPERIMENTS.md)）。うまくいかなかった実験・撤回した主張も同文書に残している（例: 「構造化フィードバックの*形式*が効く」という当初仮説は実測で棄却）。
- 「AI はこの言語を学習していない」問題は in-context 学習（PRIMER 1枚）で回避できることを 16 タスク規模で確認済み。それ以上の規模は未検証。

## ドキュメント

| ファイル | 内容 |
|---|---|
| [PRIMER.md](PRIMER.md) | AI 向け正典（システムプロンプトにそのまま入れる） |
| [SPEC.md](SPEC.md) | 言語仕様と設計判断・バージョン履歴 |
| [CHANGELOG.md](CHANGELOG.md) | 変更履歴 |
| [README.md](README.md) | ルートへ昇格したIntentIR意味層とAilexとの統合概要 |
| [DOGFOOD.md](DOGFOOD.md) | ドッグフーディングの記録（痛点→修正） |
| [EXPERIMENTS.md](EXPERIMENTS.md) | AI 実測の記録（否定的結果も含む） |
| [core/README.md](core/README.md) | 実装の歩き方 |
