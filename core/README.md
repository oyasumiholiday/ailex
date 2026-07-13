# Ailex v0.1 コア

AI が書くための中間言語 Ailex の reference 実装（tree-walking）＋ JS バックエンド＋ CLI。
設計は [../SPEC.md](../SPEC.md)、作り方の手順は [../PROCESS.md](../PROCESS.md)。

## 使い方

```sh
node ailex/core/cli.ts <cmd> <file.ax> [arg]     # または ./ailex/ailex <cmd> ...
```

| コマンド | 説明 |
|---|---|
| `check <file>` | 型＋契約検査 → 構造化診断(JSON)。exit 0=ok / 1=診断あり |
| `run <file>` | 検査 → JS へ落として実行（`eg` を検査し `main()` があれば評価） |
| `fmt <file>` | L1 正規形へ整形 |
| `scope <file> [fn]` | そのスコープで使える名前と型を機械可読(JSON)で |
| `emit-js <file>` | 生成される JavaScript を表示 |

例: `./ailex/ailex run ailex/examples/demo.ax`

## 実装ファイル

- `lang.ts` — 字句・パーサ・AST・双方向型検査・評価器・構造化診断・契約・正規形プリンタ
- `tojs.ts` — L0 → JavaScript transpiler（実行を本物にする2つ目のバックエンド）
- `cli.ts` — コマンドライン
- `conformance.ts` — golden テスト群＋ランナー（**インタプリタと JS 実行の両方を1つのテスト群で検証**）

## テスト

```sh
node ailex/core/conformance.ts     # 28/28 緑を保つ
```

機能を足す前にここへ golden ケースを足し、緑を保ちながら育てる（実在の言語の教訓）。

## v0.1 でできること / できないこと

**できる**: `Int/Float/Bool/String/List[T]`、中置演算子＋優先順位、`if`、`let..in`、関数、契約(`requires/ensures/eg`)、数値・リスト・文字列 stdlib、型/契約検査、JS 実行、CLI。

**v0.2 以降**: 再帰・ユーザ定義多相・`Record`・`Option`・effect/IO・FFI・モジュール・高階関数（`map/fold`/ラムダ）・`scope` の行:列精度・self-host。
