# IntentIR 0.15.0a2 Windows 公開 wheel 確認

公開済みの IntentIR `0.15.0a2` wheel を Windows Server 2022 上で確認した CI 記録です。現在のソース checkout をインストールするテストではありません。

## 固定対象と結果

- Release source: [`cb154fb1f56476644b9237fb191dad5002fe3f99`](https://github.com/oyasumiholiday/ailex/commit/cb154fb1f56476644b9237fb191dad5002fe3f99)
- Smoke script: [`5d3a4415a716e64628a76844106cc9be46a04f34`](https://github.com/oyasumiholiday/ailex/commit/5d3a4415a716e64628a76844106cc9be46a04f34)
- Published wheel: `intentir-0.15.0a2-py3-none-any.whl`
- Wheel SHA-256: `8c82ebddaced33d9eba4dd7bcb9014057ebeced21ec51d21e09329d7bbeebdf8`
- Runner: `windows-2022`、image version `20260913.307.1`
- Push CI: [`35319144364`](https://github.com/oyasumiholiday/ailex/actions/runs/35319144364) 全7チェック成功
- PR CI: [`35319154428`](https://github.com/oyasumiholiday/ailex/actions/runs/35319154428) 全7チェック成功
- Python 3.11 job: [`105517440904`](https://github.com/oyasumiholiday/ailex/actions/runs/35319144364/job/105517440904) 成功。出力: `{"ok":true,"release":"0.15.0a2","python":"3.11.9","powershell":"7.6.6","result":"published-wheel-windows-smoke"}`
- Python 3.13 job: [`105517440874`](https://github.com/oyasumiholiday/ailex/actions/runs/35319144364/job/105517440874) 成功。出力: `{"ok":true,"release":"0.15.0a2","python":"3.13.15","powershell":"7.6.5","result":"published-wheel-windows-smoke"}`

PowerShell 7.3 以上、`PSNativeCommandArgumentPassing=Standard`、明示的 UTF-8 を条件にしました。実際に観測した PowerShell は上記の 7.6.6 と 7.6.5 であり、7.3 自体を実行した結果ではありません。wheel を新規 GUID 一時ディレクトリへダウンロードし、SHA-256 一致後に新しい venv へ `--no-index --no-deps` でインストールしています。その後 checkout 外で、両デモ、空タイトル拒否を含む永続 CRUD、Patch、migration、Unicode と空白を含む JSON・パスの PowerShell round-trip を確認しました。

## 再現

Windows で Python 3.11 以上を `PATH` に置き、PowerShell 7.3 以上からリポジトリルートで実行します。公開 wheel のダウンロードにはネットワーク接続が必要ですが、インストールはローカル wheel だけを使用します。

```powershell
pwsh -NoProfile -File .\scripts\smoke_windows_release.ps1
```

スクリプトは既存データを削除・上書きせず、新しい GUID 一時ディレクトリを作成します。終了後も自動削除しません。

## この結果が示さないこと

これは固定 runner 上の公開 wheel スモークであり、Windows の全テスト suite、Windows 10/11、PowerShell 7.3 未満、Legacy 引数処理、UTF-8 を明示しない既定 locale の動作を確認したものではありません。人が Windows 上で手順を試した結果や、独立利用者による検証でもありません。Windows 全般の対応や本番適合を保証するものではありません。
