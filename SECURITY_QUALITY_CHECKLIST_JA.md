# IntentIR セキュリティ・品質チェックリスト

## 位置づけ

このChecklistは、[AI制作で気を付けるセキュリティ・品質チェック](docs/SECURITY_QUALITY_REVIEW_CRITERIA_JA.md)をIntentIRの開発・Releaseへ適用するための運用版です。元の基準は編集せず、個別Reviewの判定と証拠は別のReportへ記録します。

初回適用結果は [SECURITY_QUALITY_BASELINE_2026-07-21_JA.md](SECURITY_QUALITY_BASELINE_2026-07-21_JA.md) に記録しています。

判定は必ず`OK / NG / 未確認 / 対象外`のいずれかにします。確認できていない項目を推測で`OK`にしません。秘密、Token、Cookie、Webhook URL、個人情報の値はReportへ転載しません。

## Release Gate

次のどれかに該当する場合、公開、Package Release、GitHub Merge、MCP配布を停止します。

- 公開停止事項に`NG`または重大な`未確認`がある
- Repository、履歴、Log、Fixture、Reportに秘密情報の疑いがある
- AIがProject Root外へアクセスできる、または書込みが明示許可なしで有効になる
- `apply_patch`がHash Guard、検証義務、原子的保存を迂回できる
- Test、Compile、MCP Schema/stdio検証のいずれかが失敗する
- Critical/High依存脆弱性の影響が未評価
- Release対象を戻せるCommit、Tag、Rollback手順がない
- 個人情報、決済、医療、金融、採用、社内機密を扱うのに専門家Reviewがない

## 必須確認

### 1. 秘密情報・Git・公開

- [ ] `.env`、秘密鍵、DB、Credential、IDE設定、一時FileがGit除外されている
- [ ] Source、Test、Example、Report、Logを秘密検出し、値を回答へ表示していない
- [ ] 過去に公開した秘密がある場合、文字列削除だけでなく失効・再発行済み
- [ ] GitHub Secret scanningとPush protectionの設定を確認した
- [ ] Branch protection、必須Review、必須CI、Release承認を確認した
- [ ] Git remoteにCredentialを埋め込んでいない
- [ ] Release CommitとRollback先を特定できる

### 2. 依存関係・CI・Supply Chain

- [ ] AIが提案したPackageの実在、公式提供元、対応Versionを確認した
- [ ] Application/Test環境の依存をLockし、再現可能な導入Commandがある
- [ ] Critical/High脆弱性をScanし、影響と対応を記録した
- [ ] 不要なDependencyを追加していない
- [ ] CI Actionは信頼できる提供元で、権限は`contents: read`を基本にする
- [ ] Test、Compile、Package BuildがMerge前に実行される
- [ ] OSS Licenseと配布条件を確認した

### 3. Parser・入力・生成物

- [ ] Source、JSON、Patch、CLI引数、MCP引数をServer側で構造・型検証する
- [ ] 未知Field、未知Operation、範囲外値、Path traversalを安定診断で拒否する
- [ ] AI生成Sourceを構文・型・参照・契約・Test検証なしで保存しない
- [ ] Errorへ秘密、外部入力全文、不要な内部Path、Stack traceを露出しない
- [ ] TypeScript、SQLite DDL、IR生成結果が決定的で、直接実行前に検証される
- [ ] SQL値を文字列連結せず、永続化ではParameter bindingを使用する

### 4. IntentPatch・AI Tool権限

- [ ] 読取りToolと書込みToolを明確に分離する
- [ ] MCPの書込みは既定で無効で、起動時に明示許可が必要
- [ ] Host側で`intentir.apply_patch`の直前に利用者が対象とDiffを確認できる
- [ ] `baseModuleId`と`expectedId`が一致しないPatchを拒否する
- [ ] 全Operationを一つのTransactionとして検証・保存する
- [ ] Sourceが検証後に変わった場合、保存せず再生成を要求する
- [ ] Project Root外とImport所有元への誤書込みを拒否する
- [ ] Patch、Hash、診断、LogへCapability実値や秘密を含めない
- [ ] 外部文書を命令ではなくデータとして扱い、Prompt Injectionで権限を拡大しない

### 5. Data・SQLite・Migration

- [ ] Testは本番Dataを使わず、Fixtureまたは匿名化Dataだけを使う
- [ ] SQLite操作はTransaction、Constraint、Rollbackを検証する
- [ ] Migrationは既定Plan-onlyで、破壊的変更に追加承認が必要
- [ ] Schema変更前にBackup/復元、所要時間、Rollback方針を確認する
- [ ] ErrorやTest出力へRecordの秘密・個人情報を出さない
- [ ] Hosted DB/Storageを導入した場合、Network、最小権限、暗号化、Backup復元を元基準で追加確認する

### 6. Log・監視・運用

- [ ] 重要な書込み、拒否、検証失敗を秘密なしで追跡できる
- [ ] LogへToken、Cookie、Credential、Source内秘密を出さない
- [ ] MCP/CLIの異常終了とCI失敗を検知できる
- [ ] Incident時の停止、Credential失効、調査、復旧、告知手順がある
- [ ] Release後の監視、Rollback、依存更新の担当と周期を決める

### 7. 機能品質

- [ ] 主要なCompile、Verify、Patch、Run、Migrate、BuildをEnd-to-Endで確認する
- [ ] 空、重複、境界値、型不一致、古いHash、並行変更、I/O失敗を試す
- [ ] Dry-runがSourceを変更しないことを確認する
- [ ] 同じ入力から同じIDと生成物が得られることを確認する
- [ ] Python、生成TypeScript、SQLiteで意味と制約が一致する
- [ ] 通常環境とoptional MCP環境の両方を検証する

## 現在対象外の章

現状のIntentIRはLocal CLI/Library/MCP stdio Serverであり、公開Web Serviceではありません。そのため、元基準の次の項目は機能を導入するまで`対象外`です。ただし、HTTP TransportやHosted Serviceを追加した時点で必須確認へ戻します。

- Cloud DB、Supabase RLS、Object Storage
- Login、Session、Cookie、Web Authorization
- Public API、CORS、CSRF、HTTPS Header、Rate limit
- Slack/Webhook、問い合わせForm、File upload
- Browser UI、Responsive、Accessibility、SEO、画像、Core Web Vitals
- Email配信、決済、利用者Dataの退会・削除

## 実行Command

```sh
# 通常環境
python3 -m unittest discover -s tests -v
python3 -m compileall -q intentir tests
python3 -m intentir --version

# optional MCP環境
uv sync --extra mcp
uv run --extra mcp python -m unittest discover -s tests -v

# 代表的なAgent read-only確認
python3 -m intentir agent intentir.describe_module \
  --root . \
  --arguments '{"source":"examples/todo_crud.intent"}'
```

秘密検出や依存脆弱性Scanは、値を標準出力やReview Reportへ転載しない設定で実行します。

## Review Report Template

```md
# IntentIR Security/Quality Review

- 確認日: YYYY-MM-DD
- 対象Commit/Tag:
- 対象Version:
- 確認者:
- 対象環境:

## 公開停止事項

| 項目 | 判定 | 根拠 | 対処/追加確認 |
|---|---|---|---|

## NG

## 未確認

## 対象外

## 検証Commandと結果

## 公開前に直す順番
```
