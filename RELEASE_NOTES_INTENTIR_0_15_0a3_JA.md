# IntentIR 0.15.0a3 alpha リリースノート

IntentIR 0.15.0a3 は、既存の IntentIR に保存状態の read-only 参照を追加する alpha 更新です。Python 3.11 以上が必要です。

## 追加内容

- `intentir read SOURCE --db PATH` で、保存済み SQLite 状態を module 全体の検証後に JSON で出力します。
- `--entity NAME` で、検証済み状態から指定した entity だけを返せます。
- Todo スターターと配布ガイドに、Complete、migration / Rename、Delete 後の read 手順を追加しました。
- 既存コマンドの互換性を壊す変更はありません。今回の変更は追加機能です。

## インストール

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --no-index --no-deps ./intentir-0.15.0a3-py3-none-any.whl
.venv/bin/intentir --version
```

## read の範囲

`read` は action を実行せず、存在する DB を SQLite の `mode=ro` で開きます。DB がない場合は作成せず失敗します。ソースと DB のスキーマが一致しない場合も、明示的な migration が完了するまで拒否します。

論理データ、スキーマ、journal mode は変更しません。ただし SQLite が read-only WAL を扱う際の `-wal` / `-shm` sidecar の利用や作成まで禁止するものではありません。module 全体を読み込んで検証する小規模ローカル用途向けで、filter 言語や pagination はありません。

## 検証状況

リリース前の [commit `0f65c80ffb83aa57457befba0905ec20f09650a4`](https://github.com/oyasumiholiday/ailex/commit/0f65c80ffb83aa57457befba0905ec20f09650a4) に対する [CI run 35324485360](https://github.com/oyasumiholiday/ailex/actions/runs/35324485360) は 9 checks すべて成功しました。これは当該 commit の自動検証結果であり、本番適合性、広範な Windows 対応、外部利用者による再現、または独立評価を示すものではありません。
