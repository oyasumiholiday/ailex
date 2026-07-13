# Ailex 先行研究監査（新奇性の空き地の特定）

> 出所: deep-research ワークフロー（2026-07-10、合成手前で途中停止）。
> スコープ→検索→主張抽出(20)→敵対的検証(67, 2/3の反証で棄却)まで完了。以下は「検証を生き延びた高信頼の主張」を手作業で統合したもの。
> 注意: 各論文の一次資料の verbatim 引用で裏取り済みだが、最終合成・重複統合は未完。個別PDFを全読したわけではない。

---

## 結論（先に）

Ailex の4中核アイデアのうち、**#1（型安全 constrained decoding / 単調型付け可能性）は機構としては 2025 年に取られている**。ETH Zurich が PLDI/OOPSLA 2025 でほぼ同じことをやっている。ただし「**言語を、どの生成接頭辞も well-typed になるよう設計する**」という *by-design* の枠組みと、**検証器応答を機械可読な構造化フィードバックとして生成ループへ還流する**（#2）は、まだ明確に取られていない空き地。指示理解層（仕様IR）も、否定的知見（NLは効かない）と重い形式仕様の間に空きがある。

---

## 実行層の監査

### Ailex #1: 単調型付け可能性 / 型安全 constrained decoding

**最近接先行（＝ほぼ同一）**: Mündler, He, Wang, Sen, Song, Vechev, **"Type-Constrained Code Generation with Language Models"**, PLDI/OOPSLA 2025, **arXiv:2504.09246**（PACMPL, DOI 10.1145/3729274。ETH Zurich SRI Lab + UC Berkeley）。
- 一次資料 verbatim: 「we develop a **sound algorithm to determine if a partial program can be completed into a well-typed program**」「novel **prefix automata** and a **search over inhabitable types**」「reduces compilation errors by **more than half**」。単純型付き言語で形式化し TypeScript に拡張。
- **差分**: 彼らは**既存言語(TypeScript)に型制約デコードを後付け**する（prefix automata＋型の居住可能性探索）。Ailex の主張は「**言語自体を、単調型付け可能になるよう設計する**」。→ **機構は取られている。残る新奇性は "retrofit（既存言語へ後付け）" vs "by-design（言語設計として内在）" の差**に限定される。この差が生成精度・コスト・実装単純さで意味を持つかを示さないと新奇性は弱い。
- 検証注意: 「型エラーは未対処の空き地だった」という強い言い方は**過剰主張**（検証で複数指摘）。この論文自身が先行を引いている。

**構文レベルの先行（型は保証しない）**: **SynCode**（Ugare et al., ICML/COLM 2024, arXiv:2403.01632）, GBNF/llguidance。
- DFA mask store による文法制約デコード。保証は **CFG（構文）のみ**——use-before-declaration や型整合は対象外と明記。
- 検証注意: 「sound かつ complete で全ての妥当トークンを保持」は**過剰主張**。completeness は条件付き（accept sequence が任意トークンより長いとき, d>len(t)）。

### Ailex #2 / #4: typed holes を型文脈付きで LLM に渡す・穴埋め合成

**最近接先行**: Blinn, Li, Kim, Omar（Hazel グループ）, **"Statically Contextualizing Large Language Models with Typed Holes"**, OOPSLA 2024, **arXiv:2409.00921**（PACMPL, DOI 10.1145/3689728）。
- verbatim: 「the Hazel Language Server **identifies the type and typing context of the hole** being filled, **even in the presence of errors**」。ChatLSP（LSPの保守的拡張）。
- 効果: MVUBench(GPT-4) で test-pass が文脈なし ~5% → 型定義のみ ~20%(4x) → 型+ヘッダ ~60%(12x)。
- **差分**: これは**プロンプトへの文脈注入（context injection）＋反復精緻化**であって、**生成を構造的に制約するわけではない**。Ailex の #2（期待型・スコープ候補を返す）と #4（穴埋め）に非常に近いが、Ailex 独自性は「フィードバックを**機械可読な構造化データ**として、かつ**デコード制約**として使う」点に絞られる。

---

## 検証フィードバック / 修復層

**Self-Repair の限界（Ailex #2 の価値仮説を支持）**: Olausson et al., **"Is Self-Repair a Silver Bullet for Code Generation?"**, ICLR 2024, **arXiv:2306.09896**（MIT CSAIL + MSR）。
- verbatim: 自己修復は「**bottlenecked by the model's ability to provide feedback on its own code**」。強いフィードバック（人間/強モデル）に差し替えると pass 33.3%→52.6%（**1.58x**）。GPT-4 の自己フィードバックは不正確(32/80 vs 人間7/80)、不確実性を表明しない(0/80 vs 7/80)。コスト込みだと自己修復の利得は小さいことも。
- **含意**: 「フィードバックの質」がボトルネック、と実証済み。だが**この論文は自然言語フィードバック**。→ **「機械可読な構造化フィードバック（期待型・スコープ候補・未達の証明義務）が自己修復を改善するか」は未検証の空き地**。Ailex の E2/E3（Haiku で修復が hypot を1回回収、しかし確実でない）とも整合。

**関連**: 
- **Counterexample-guided learning with reasoning agents**（arXiv:2606.11521）: verifier feedback を反例集合として反復還流（正規表現帰納）。
- **Structural Verification for EDA**（arXiv:2604.18834, ICCAD 2026）: **structural dependency graph = machine-readable "execution contract"**、実行前に構造整合を強制。「構造化検証」の近接例。
- **Vericoding benchmark**（Bursuc et al., POPL 2026, arXiv:2509.22908）: 既製LLMで Dafny **82%** / Verus **44%** / Lean **27%**。かつ **「Adding natural-language descriptions does not significantly improve performance」**（重要）。

---

## 三層（L0/L1/L2）・内容アドレス・投影

**最近接（投影×逐次意味検証）**: **"Projectional decoding"** の論文（MPS/projectional editing に由来と明記）。
- 生成中に**明示的な部分グラフモデル（木でなく型付きグラフのメタモデルインスタンス）を主表現として保持**し、意味制約を逐次検証。CLEVR(Qwen3) で semantic validity 55.44%→73–80%。
- **差分**: Ailex の「L0 グラフ=真実＋逐次意味検証」に非常に近い。ただし Ailex 固有の「**複数の L2 投影＋編集面を L1 に一本化**」という一体設計は未確認。

**内容アドレス（＝取られている）**: Unison、および "AI向け言語"カタログ中の **X07**（BLAKE3 で内容アドレスした canonical JSON AST ＋ **RFC 6902 patch**）、**Tacit**（BLAKE3＋De Bruijn index）。→ Ailex の「内容アドレス L0」「patch=トランザクション」は X07 が近い。**内容アドレスは新奇でない**。

**IR＝意味正規化層**: ある論文は「IR は機能的に等価なコードを似せる意味正規化層で、LLM に綺麗な入力を与える」と述べ、L0/L1 正規形の前提を支持。ただし**設計された言語でなく前処理**扱い。

---

## 指示理解層（仕様IR）

**最近接（意図の形式IR）**: Councilman et al.（UIUC/IBM）, **"Towards Formal Verification of LLM-Generated Code from Natural Language Prompts"**（Astrogator, Ansible向け）, **arXiv:2507.13290**。
- **NLライクだが形式定義された "Formal Query Language" を意図の中間表現として置き、コードが意図に一致することを形式検証**。
- verbatim: 「an LLM generated query **cannot be trusted** because a mistake in it means we are guaranteeing correctness with regards to an **incorrect specification**」→ 仕様の信頼問題、人間確認を必須に。

**方向性の一致（仕様が要、NLは効かない）**:
- 複数論文が「**仕様（tests → code contracts → 論理契約(Dafny/F*/Verus) → DSL）こそが AI 生成コードの信頼性機構**であり、生成言語そのものではない」と枠づけ。
- Vericoding の「NL説明を足しても上がらない」。→ **実測 E2/E3 の教訓（マスクは型を守るが意味を守らない＝仕様側が本丸）と一致**。
- Planning 系: **LLM-as-Formalizer vs LLM-as-Planner** の taxonomy、PDDL+LLM（固定ドメイン＋LLMは問題例のみ生成）、TIC が GPT-3.5 でほぼ100%（NL→形式IR→論理推論）、**Canonical Intermediate Representation (CIR)**（LLM生成IRで最適化モデル化、47.2%で精度向上）。

---

## 言語設計そのもの（"AI-native language" 主張）

- **~35 個**の「AI/LLM が書くための言語」プロジェクトが既に存在（3陣営: 構文的/検証的/…）。**この空間は混雑している**。
- **SudoLang**: LLMネイティブ疑似言語。ただし制約は**ソフト（AIが違反を直そうとするベストエフォート）**で、**構造的保証でない**。型は soft/推論ベースで静的検査なし。→ 「型エラーが構造的に不可能」という Ailex の主張とは対照的。
- **決定的**: カタログ中、**「左から右の任意の接頭辞が常に well-typed（＝monotone typability 相当）」を主張するプロジェクトはゼロ**。typed holes も Tacit のみ。→ **"AI-native language" の枠で monotone typability は未主張**（ただし学術の ETH 論文が機構は達成済み）。

---

## 新奇性の空き地（優先度付き）

**ほぼ取られている（新奇性を主張しにくい）**
- 型安全 constrained decoding の**機構**（ETH, 2025）
- 内容アドレス L0 / patch（Unison, X07, Tacit）
- typed-hole の型文脈を LLM に渡す（Hazel/ChatLSP, 2024）
- 構文 constrained decoding（SynCode/GBNF）
- 自己修復の価値（ただし NL フィードバック）

**まだ空いている（候補・優先度順）**
1. **【最有力・即実験可】機械可読な構造化フィードバック vs 自然言語フィードバック**。Self-Repair(ICLR 2024) は「フィードバックの質がボトルネック」を実証したが、フィードバックは NL。「期待型＋スコープ候補＋未達の証明義務」を構造化データで還流すると修復ラウンド/pass@k が改善するか——**見つかった範囲で誰もやっていない**。Ailex は構造化フィードバック機構と compare.ts を既に持つ。
2. **by-design monotone typability vs retrofit（ETH）**。同じ型安全生成を、既存言語への後付けでなく言語設計として内在させると、生成精度・コスト・実装単純さで優位が出るか。
3. **L0/L1/L2 の一体設計＋L1唯一編集**。projectional decoding は部分グラフを持つが「複数 L2 投影＋編集面 L1 一本化」の一体設計は未確認。
4. **軽量契約IR vs NL**（指示理解層）。Vericoding は「重い形式仕様では NL は効かない」を示した。型＋契約＋実例の**軽量**中間が、NL 指示よりコードの機能的正解率を上げるか、は中間帯として未探索。

## 反証可能な問い（研究の芯）

- **Q1（最有力）**: 構造化フィードバック（機械可読）は、自然言語フィードバックに対し、同一モデル・同一タスクで**修復ラウンド数を減らし pass@k を上げる**か？ ← Self-Repair の設定で差分実験。Ailex で今すぐ着手できて、新奇性が最も明確。
- **Q2**: by-design の型安全生成は、ETH の retrofit 型制約デコードに対し優位を示せるか（精度/コスト/実装）。
- **Q3**: 軽量契約IR は NL 指示よりコード生成の機能的正解率を上げるか（Vericoding の否定的結果の"軽量版"での再検証）。

**推奨**: 芯を **Q1** に据える。理由: (a) 先行が「フィードバックの質が鍵」と実証済みだが NL に留まる、(b) 構造化フィードバックを還流した既存例が見当たらない、(c) Ailex は機構と実験ハーネスを既に持ち即着手できる。monotone typability(Q2) は ETH に機構を取られているので、主軸でなく「by-design の実利」に格下げして添える。
