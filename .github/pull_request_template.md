## 変更内容

## 検証

- [ ] `python3 -m unittest discover -s tests -v`
- [ ] `python3 -m compileall -q intentir tests`
- [ ] 変更対象のCLI/MCP/生成物を実行確認した

## セキュリティ・品質

[IntentIRセキュリティ・品質チェックリスト](../SECURITY_QUALITY_CHECKLIST_JA.md)と[完全版レビュー基準](../docs/SECURITY_QUALITY_REVIEW_CRITERIA_JA.md)を参照してください。

- [ ] 秘密、Credential、個人情報をSource、Fixture、Log、Reportへ追加していない
- [ ] 新しい入力と外部Dataを構造・型・範囲・Path境界で検証している
- [ ] AI/MCPの権限を増やす変更では、読取/書込、既定値、人の承認を確認した
- [ ] Patch/DB/Filesystem変更の原子性、Rollback、並行変更を確認した
- [ ] Dependencyの提供元、Version、License、脆弱性を確認した
- [ ] 対象外または未確認の項目と理由をPRへ記録した

## Rollback
