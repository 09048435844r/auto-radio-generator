# Auto Radio Generator - CLAUDE.md

## インターフェース仕様書

リサーチパイプラインと台本生成パイプラインの
インターフェース仕様書を必ず参照すること。

場所: `/mnt/e/windsurf/life-update-radio-specs/interface_spec.md`

### 参照タイミング
- research_brief.jsonのフィールドを参照するとき
- 新機能を実装するとき
- 品質基準を変更するとき

### 更新ルール
仕様書を変更する場合は:
1. `/mnt/e/windsurf/life-update-radio-specs/interface_spec.md` を編集
2. git commit & push
3. リサーチ側パイプラインに変更を共有する

補足 (2026-07-16): specs リポジトリ (SSOT) は commit 後に**即 push** すること。
未 push 期間は複数クローン・複数セッション間の分岐リスク期間となるため
(2026-07-15 の分岐事故で実証)。コード系リポジトリの「push は手動」運用の例外。
編集前の標準手順 (status / log / pull --rebase / backlog 節構造確認) は
specs リポジトリ側の CLAUDE.md を参照。
