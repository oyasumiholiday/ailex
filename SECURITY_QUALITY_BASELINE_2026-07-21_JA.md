# IntentIR セキュリティ・品質ベースライン

- 確認日: 2026-07-21
- 対象Version: 0.14.0
- 対象Commit/Tag: `codex/intentir-v0.14`統合Commit（本Reportと同時に作成）
- 対象環境: Local macOS、Python 3.12、optional MCP Python SDK 1.28.1
- 確認基準: [IntentIR運用Checklist](SECURITY_QUALITY_CHECKLIST_JA.md)
- 完全版基準: [改変しない元Review基準](docs/SECURITY_QUALITY_REVIEW_CRITERIA_JA.md)

## 結論

**現時点の公開・Package Release判定は停止です。** Local実装とTest、License分離、初回CommitによるRollback点の確保、Git remoteとの履歴照合は通っています。一方、GitHub側の保護設定とCI実行結果、MCP Host側の利用者承認・監査は確認できていません。

## 公開停止事項

| 項目 | 判定 | 根拠 | 対処/追加確認 |
|---|---|---|---|
| GitHub保護とCI | 未確認 | `origin`の`main`とv0.12履歴は照合済みだが、Repository設定とGitHub Actions結果は未確認 | Secret scanning、Push protection、Branch protection、必須CIを確認する |
| MCP書込み運用 | 未確認 | 実装は既定拒否だが、Host側の利用者承認UIと永続監査Logは未確認 | `--allow-writes`を使うHostごとに承認・Diff表示・監査を検証する |

## OK

| 項目 | 根拠 |
|---|---|
| 元Review基準の保全 | 元FileとProject内CopyのSHA-256が一致 |
| OSS License | AilexのMITを`LICENSE`に保持し、IntentIRのApache-2.0を`LICENSE-APACHE`とPackage metadataへ設定 |
| Git remoteと履歴 | `origin`を既存Repositoryへ接続し、`main`、v0.12 Draft PR、v0.14統合Branchの関係を照合 |
| Release CommitとRollback | `main`初回Snapshotで公開対象とRollback点を固定 |
| 秘密候補のGit除外 | `.env`、秘密鍵、DB、Log、仮想環境などを`.gitignore`へ追加 |
| 作業Treeの限定秘密Scan | 一般的なCloud/GitHub/OpenAI/Slack Tokenと秘密鍵の形式に一致するFileなし。秘密・Credentialを示すFile名もなし |
| 依存固定 | `uv.lock`でMCPを含む32 Packageを固定し、`uv lock --check`成功 |
| 既知脆弱性Scan | 固定済み配布依存を`pip-audit`で確認し、既知脆弱性0件。EditableなLocal Package本体はVersion推論不可として除外 |
| Supply Chain設定 | GitHub ActionsをCommit SHAで固定し、Workflow権限を`contents: read`へ限定。npm、pip、GitHub ActionsのDependabotを週次設定 |
| AI書込みの最小権限 | Agent CLIとMCPは書込み既定無効。`--allow-writes`でのみ有効化し、未許可時は`write_tool_disabled`を返す |
| Tool区分 | MCP annotationで読取りToolと破壊的な`apply_patch`を区別 |
| Project境界 | Root外PathとSymbolic Link経由の逸脱を拒否し、診断へ不要な絶対Pathを含めない |
| Patch安全性 | `baseModuleId`、`expectedId`、静的検証、要求Test、原子的保存、Stale拒否を自動Testで確認 |
| Model Adapter境界 | CommandはCLIでのみ指定し、Shell不使用、Timeout、出力上限、UTF-8/JSON/Request ID検証を実装。評価TestはRequestへ含めない |
| OpenAI Provider境界 | API Keyは環境変数からのみ読取り、Payload/Resultへ非保存。`store: false`、Strict Structured Outputs、4 MB応答上限、Provider Body非転載をOffline Testで確認 |
| Data/Migration | SQLite Transaction、Constraint、失敗時Rollback、Plan-only Migration、破壊的変更の追加許可を自動Testで確認 |
| Local Test | Ailex 89件成功。IntentIRは通常環境91件中90件成功、optional MCP 1件のみSkip。MCP環境では91件すべて成功 |
| Compile/Package | `compileall`成功、`intentir-0.14.0` wheel build成功 |

## 未確認

- 過去のGit履歴や公開物に秘密が含まれていないか、含まれていた場合に失効・再発行済みか
- GitHub Secret scanning、Push protection、Private Vulnerability Reporting、Branch protection、必須Review、必須CIの設定
- 追加したGitHub ActionsがGitHub上のPython 3.11/3.13環境で実行成功するか
- `--allow-writes`を使う各MCP Hostで、適用直前の利用者承認、対象Path、Diff、監査記録が保証されるか
- Release後の監視、Incident対応、担当者、更新周期
- macOS以外でのCLI、SQLite、生成TypeScriptの動作

## 対象外

現状はLocal CLI/Library/MCP stdio Serverで、公開HTTP Service、Browser UI、利用者Account、外部Storage、決済を持ちません。機能追加時には対象外を解除して完全版基準で再Reviewします。

- Cloud DB、Supabase RLS、Object Storage、Hosted Backup
- Login、Session、Cookie、Role/権限管理
- Public API、CORS、CSRF、HTTPS Header、Rate limit
- Webhook、Slack、問い合わせForm、Email配信
- File upload、画像最適化、Responsive、Browser、Accessibility、SEO
- 決済、返金、退会、利用者Data削除

## 検証Commandと結果

| Command | 結果 |
|---|---|
| 元FileとCopyの`shasum -a 256` | 同一Hash |
| File名のみを返す限定秘密Pattern Scan | 一致なし |
| `npm ci --ignore-scripts` | 固定依存7 Packageを導入、既知脆弱性0件 |
| `npm test` | Ailex適合Test 89件成功 |
| `npm pack --dry-run` | Ailex配布物30 File、IntentIR用`.intent` Fixtureを除外 |
| `uv lock --check` | 成功、32 Package解決 |
| `uvx pip-audit ... --no-deps --disable-pip` | 既知脆弱性なし、Editable Local PackageのみSkip |
| `python3 -m unittest discover -s tests -v` | 91件中90件成功、1件Skip |
| MCP依存環境の同Test | 91件成功 |
| `python3 -m compileall -q intentir tests` | 成功 |
| `python3 -m pip wheel . --no-deps` | wheel build成功 |
| Wheel metadata / contents | `License-Expression: Apache-2.0`と`dist-info/licenses/LICENSE-APACHE`を確認 |
| Fixture Trajectory / Model Adapter | 16 / 16および4 / 4 Checkpoint Run成功 |
| OpenAI Provider Offline Test | Payload、Structured Output、Provenance、秘密非混入、失敗分類が成功。実API未実行 |
| Benchmarkの7種類の公開JSON Schema | Fixture/Model Manifestを含む9実体がDraft 2020-12検証成功 |
| Agent CLI/MCP CLIの`--help` | `--allow-writes`を確認 |

限定秘密Scanは完全な保証ではありません。GitHub接続後はGit履歴を含む専用ScannerとGitHub側のPush protectionでも確認します。

## 公開前に直す順番

1. 統合BranchをGitHubへ公開し、公開済み秘密の有無を確認する
2. GitHubのSecret scanning、Push protection、Branch protection、Private Vulnerability Reporting、必須CIを設定する
3. GitHub Actionsを実行し、AilexとIntentIRの全Job成功を確認する
4. MCP書込みを配布する場合、Host側の利用者承認と永続監査を確認する
