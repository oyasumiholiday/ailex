# IntentPatch v0.13 検証レポート

## 目的

IntentPatchは、AIによる変更を行番号依存の文字列差分ではなく、内容ハッシュで保護された意味操作として扱うProtocolです。古い状態への誤適用、部分的な書き換え、検証されない変更を防ぎながら、人間には通常のDiffを提示します。

## Patch Envelope

```json
{
  "schemaVersion": "0.13.0",
  "baseModuleId": "sha256:...",
  "operations": [
    {
      "kind": "insert_member",
      "target": "entity:Task",
      "expectedId": "sha256:...",
      "member": "fields",
      "value": {
        "name": "priority",
        "type": "Integer",
        "default": 0
      }
    }
  ],
  "requestedObligations": ["static", "affected-tests"]
}
```

`baseModuleId`はPatchが前提とするModule、`expectedId`は対象Nodeの意味内容を固定します。IDはSourceの行番号や空白ではなくCanonicalな意味内容から生成されます。

## 実装したOperation

- `add_definition`: 新しい定義を追加
- `replace_definition`: 定義全体を置換
- `remove_definition`: 定義を削除
- `rename_symbol`: 定義名と意味参照を変更
- `set_member`: 既存メンバーを置換
- `insert_member`: Collectionへメンバーを追加
- `remove_member`: メンバーを削除

対象はCapability Operation、Entity Field、Function Input・Body・Return Type・Example、Action Input・Use・Requirement・Effect・Ensure、Test Given・When・Expectです。内容ID、依存Edge、義務IDは直接編集させず、Compilerが変更後のProgramから再構築します。

## 適用手順

1. Sourceをコンパイルし、現在のModule IDとNode IDを取得する
2. Envelopeと全Operationを構造検証する
3. `baseModuleId`と各`expectedId`を照合する
4. 全Operationをメモリ上のProgramへ順番に適用する
5. Canonical Sourceへ整形し、再コンパイルと静的検証を行う
6. 変更前後のGraphから影響Symbolを計算する
7. `affected-tests`または`all-tests`を要求された場合は実行検証する
8. 全て成功した場合だけ、一時Fileの`fsync`と`os.replace`で原子的に保存する

CLIは既定でdry-runです。

```sh
python3 -m intentir patch \
  examples/todo_crud.intent examples/add_task_priority.patch.json

python3 -m intentir patch \
  examples/todo_crud.intent examples/add_task_priority.patch.json --json

python3 -m intentir patch \
  examples/todo_crud.intent examples/add_task_priority.patch.json --apply
```

## 成功時の結果

- `patchId`: SourceとEnvelopeから決定的に生成したPatch ID
- `baseModuleId`: 適用前Module ID
- `resultModuleId`: 検証済みの適用後Module ID
- `changedSymbols`: 直接変更されたSymbol
- `affectedSymbols`: 依存Edgeを逆向きに辿った影響範囲
- `executedObligations`: 実際に検証した義務
- `diff`: 人間が確認できるUnified Diff
- `applied`: Fileへ保存したかどうか

同じSourceとPatchからは同じ`patchId`と`resultModuleId`を得ます。

## 拒否とRollback

主な安定診断Codeは次のとおりです。

- `stale_base_module`: Module IDが現在値と一致しない
- `stale_target_node`: Node IDが現在値と一致しない
- `unknown_patch_target`: 対象Symbolが存在しない
- `unknown_patch_operation_field`: Operation種別で許可されていないFieldがある
- `imported_patch_target`: Import元の定義をRoot Sourceから変更しようとした
- `conflicting_patch_operation`: 同じ対象への矛盾する操作
- `patch_obligation_failed`: 要求した実行義務が失敗した
- `concurrent_source_change`: 計画後、保存前にSourceが変更された

構文、型、参照、契約、Testのいずれかが失敗した場合、変更Sourceは返さずFileも更新しません。複数Operationの途中状態が保存されることもありません。

## 自動検証結果

2026-07-21に次を実行しました。

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q intentir tests
```

全73件が成功しました。このうちIntentPatch専用の7件は、定義操作、メンバー操作、Rename参照更新、古いModule/Node拒否、無効結果の全体Rollback、影響Testによる拒否、CLIのdry-runと明示適用を検証します。

## 現在の制約

- 一つのPatchが直接変更できるのはRoot Source内の定義のみ
- Importされた定義は、その定義を所有するSourceへ別Patchを送る必要がある
- Member Pathは現在実装済みの意味Collectionと単一Memberに限定される
- 定義を変更するとCanonical Formatterを通るため、その定義内のコメントを保持できない場合がある
- `rename_symbol`と、Rename後の同一対象をさらに変更する操作は一つのPatchに混在できない
- MCP Server、Agent Adapter、並行Agent Demo、外部言語向けAdapter、比較Benchmarkは未実装

次の開発では、IntentPatchをモデル非依存のTool APIへ公開し、全文再生成・Unified Diff・構造編集との比較を同一課題で計測します。
