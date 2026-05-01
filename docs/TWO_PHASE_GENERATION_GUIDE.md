# 2段階生成（Two-Phase Generation）ガイド

**作成日**: 2026年4月10日  
**バージョン**: v3.6.0  
**目的**: ローカルLLMでの台本生成を高速化・安定化

---

## 概要

2段階生成は、台本生成を「クリエイティブ生成」と「JSON構造化」に分離することで、LLMの得意分野に特化させる最適化手法です。

### アーキテクチャ

```
┌─────────────────────────────────────────────────────────────┐
│ Phase 1: Creative Markdown Generation                       │
│  - LLMがJSON制約なしで自由に会話を生成                        │
│  - temperature=0.85（創造性重視）                            │
│  - 出力: Markdown形式の台本                                  │
│    例: **A**: こんにちは！ **B**: よろしく！                  │
└─────────────────────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────────────────────┐
│ Phase 2: JSON Conversion (Provider-Dependent)               │
│                                                             │
│  [Ollama等のローカルLLM] ⚡ Direct Regex Bypass              │
│    → Python正規表現で直接JSON生成                            │
│    → API呼び出し0回（超高速）                                │
│                                                             │
│  [Gemini/GPT等のクラウドLLM]                                 │
│    → LLMによるJSON変換（temperature=0.1）                    │
│    → 失敗時は正規表現パーサーにフォールバック                  │
└─────────────────────────────────────────────────────────────┘
```

---

## Direct Regex Bypass とは？

**問題**: Gemma4等のローカルLLMは、JSON生成で空応答や不正な出力を返すことが多く、Phase 2のAPI呼び出しが無駄になっていた。

**解決策**: ローカルLLM使用時は、Phase 2のLLM呼び出しを完全にスキップし、Python正規表現で直接JSON生成を行う。

### 実装ロジック

```python
# segment_generator.py
async def _convert_markdown_to_json_with_fallback(self, markdown_script, segment_type):
    # ローカルLLMの場合はPhase 2をスキップ
    if self._llm.provider_name.lower() == "ollama":
        console.print("⚡ Direct Regex Bypass: Phase 2 LLM呼び出しをスキップ")
        json_text = self._parse_markdown_to_json(markdown_script, segment_type)
        return json_text, bypass_usage
    
    # クラウドLLMは従来通りPhase 2を実行
    else:
        json_text, usage = await self._convert_markdown_to_json(...)
        return json_text, usage
```

### 正規表現パーサー

```python
def _parse_markdown_to_json(self, markdown_script, segment_type):
    # **A**: セリフ または **B**: セリフ のパターンを抽出
    pattern = r'\*\*([AB])\*\*:\s*(.+?)(?=\n\*\*[AB]\*\*:|$)'
    matches = re.findall(pattern, markdown_script, re.DOTALL)
    
    # JSON構造を構築
    turns = []
    for speaker, text in matches:
        turns.append({
            "speaker": speaker,
            "text": text.strip(),
            "section": segment_type,
            "chapter_title": None
        })
    
    return json.dumps({
        "segment_id": segment_type,
        "segment_type": segment_type,
        "topic_title": None,
        "turns": turns
    }, ensure_ascii=False)
```

---

## 効果

| 項目 | 変更前 | 変更後 | 改善 |
|------|--------|--------|------|
| **Phase 2 API呼び出し** | 5回（全セグメント） | **0回** | 100%削減 |
| **Phase 2処理時間** | 15分（失敗待ち） | **0秒** | 完全削除 |
| **総処理時間** | 43分 | **25-28分** | **35-40%短縮** |
| **JSON生成成功率** | 100%（フォールバック） | **100%（Direct）** | 維持 |
| **台本品質** | Phase 1のみ | **Phase 1のみ** | 維持 |

---

## 使い方

### 1. 有効化

`config.yaml` を編集：

```yaml
script_generator:
  orchestrator:
    enabled: true                # 新アーキテクチャを有効化
    two_phase_generation: true   # 2段階生成を有効化
```

### 2. 実行

通常通りアプリを起動：

```bash
python app.py
```

### 3. ログ確認

以下のログが表示されれば成功：

```
SegmentGenerator initialized: two_phase_enabled=True, model=qwen3:32b
  Phase 1 API: provider=ollama, model=qwen3:32b, max_tokens=2048, temperature=0.85
⚡ Direct Regex Bypass: Phase 2 LLM呼び出しをスキップ
✓ 正規表現パーサーでJSON生成完了
```

> 注: 2026-04-30 の GX10 移行で本プロジェクトの segment_model は `gemma4:26b`
> → `qwen3:32b` に変更されました。旧ログで `gemma4:26b` と表示されていた箇所は
> 現行設定では `qwen3:32b` になります。

**Phase 2のAPI呼び出しログが表示されない**ことを確認してください。

---

## プロバイダー別の動作

### Ollama（ローカルLLM）

- Phase 1: LLMでMarkdown生成
- Phase 2: **Direct Regex Bypass**（API呼び出しなし）
- 処理時間: **最速**
- コスト: **最小**

### Gemini/GPT（クラウドLLM）

- Phase 1: LLMでMarkdown生成
- Phase 2: **LLMでJSON変換**（失敗時は正規表現フォールバック）
- 処理時間: 通常
- コスト: 通常

---

## トラブルシューティング

### Phase 2がスキップされない

**症状**: `Phase 2 API: provider=ollama...` のログが表示される

**原因**: `two_phase_generation` が `false` になっている

**解決策**:
1. `config.yaml` で `two_phase_generation: true` を確認
2. アプリを再起動

### JSON生成エラー

**症状**: `Fallback parser failed: No valid speaker patterns found`

**原因**: Phase 1のMarkdownが正しい形式で生成されていない

**解決策**:
1. Phase 1のプロンプト（`segment_intro_creative` 等）を確認
2. `**A**: セリフ` または `**B**: セリフ` の形式を明示

---

## 設定ファイル

### config.yaml

```yaml
script_generator:
  orchestrator:
    enabled: true                # 新アーキテクチャを有効化
    two_phase_generation: true   # 2段階生成を有効化
    segment_model: "qwen3:32b"   # Phase 1用モデル（GX10 移行後の現行値）
```

### config/prompts.yaml

```yaml
orchestrator:
  # Phase 1用プロンプト（Markdown生成）
  segment_intro_creative: |
    Markdown形式で台本を書いてください。
    各セリフは「**A**: セリフ内容」または「**B**: セリフ内容」の形式で記述。
    ...

  # Phase 2用プロンプト（クラウドLLMのみ使用）
  markdown_to_json: |
    Convert the following Markdown script to JSON format.
    ...
```

---

## 参考資料

- **アーキテクチャ設計書**: `docs/script_orchestrator_architecture.md`
- **実装コード**: `services/script_generation/segment_generator.py`
- **プロンプト定義**: `config/prompts.yaml`

---

## 今後の拡張

- **Phase 2専用モデル**: `json_model` 設定でPhase 2に軽量モデルを使用
- **マルチプロバイダー対応**: Anthropic等の他のプロバイダーにも対応
- **並列生成**: 複数セグメントの同時生成で更なる高速化
