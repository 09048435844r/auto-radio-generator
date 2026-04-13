# ComfyUI画像生成プロンプト作成工程の調査報告

**調査日:** 2026-04-12  
**目的:** ComfyUI使用時の画像生成プロンプト作成工程を調査し、テキスト混入の原因を特定する

---

## 調査結果サマリー

### 問題の所在
**現状:** ComfyUI使用時、画像生成プロンプトに意図しないテキスト（日本語の台本内容など）が混入している可能性がある。

### プロンプト生成フロー（全体像）

```
1. ThumbnailBackgroundGenerator.generate()
   ↓ (theme, script_summary を渡す)
2. ImagePromptGenerator.generate_thumbnail_prompt()
   ↓ (LLM: Gemini Flash で英語プロンプト生成)
3. 生成された英語プロンプト
   ↓ (prompt 文字列を渡す)
4. ComfyUIClient.generate_image()
   ↓ (workflow JSON の "text" フィールドに設定)
5. ComfyUI API へ送信
```

---

## 詳細フロー解析

### ステップ1: ThumbnailBackgroundGenerator.generate()

**ファイル:** `services/media_processing/thumbnail_background_generator.py`

**処理内容:**
```python
# 93-98行目
prompt = await self.prompt_generator.generate_thumbnail_prompt(
    theme=theme,
    script_summary=script_summary,
    topic_title=topic_title,
    visual_identity=identity
)
```

**入力データ:**
- `theme`: 動画のテーマ（日本語）例: `"持続血糖測定器CGM FreeStyleリブレについて"`
- `script_summary`: 台本の要約（日本語、200-300文字）
- `topic_title`: トピックタイトル（日本語、オプション）
- `visual_identity`: ビジュアルアイデンティティ（色・美学）

**⚠️ 問題点1:** `theme`と`script_summary`は**日本語テキスト**であり、これがLLMに渡される

---

### ステップ2: ImagePromptGenerator.generate_thumbnail_prompt()

**ファイル:** `services/script_generation/image_prompt_generator.py`

**処理内容:**
```python
# 360-369行目
user_message = f"""Generate a visually striking thumbnail background prompt for this video:

Theme: {theme}
Topic: {topic_title or theme}

Summary:
{script_summary[:300]}

Create a CONCRETE, SUBJECT-DRIVEN representation that maximizes click-through rate."""
```

**LLM呼び出し:**
```python
# 375-387行目
response = await self.client.aio.models.generate_content(
    model=self.model_name,
    contents=[
        types.Content(
            role="user",
            parts=[types.Part(text=system_prompt + "\n\n" + user_message)]
        )
    ],
    config=types.GenerateContentConfig(
        temperature=0.9,  # Higher creativity for thumbnails
        max_output_tokens=256,
    )
)

prompt = response.text.strip()
```

**システムプロンプト:**
```python
# 89-133行目（抜粋）
THUMBNAIL_SYSTEM_PROMPT_TEMPLATE = """You are a professional cinematographer specializing in creating SUBJECT-DRIVEN, eye-catching YouTube thumbnail backgrounds.

Your task is to generate a detailed English prompt for FLUX.1 that creates a visually striking thumbnail featuring CONCRETE SUBJECTS from the video's content.

...

OUTPUT FORMAT:
Return ONLY the English prompt text, no explanations.
"""
```

**⚠️ 問題点2:** LLMへの入力に**日本語の`theme`と`script_summary`が含まれている**

**期待される動作:**
- LLMが日本語を理解し、英語プロンプトのみを出力する
- システムプロンプトで「Return ONLY the English prompt text, no explanations」と指示

**実際の動作（推測）:**
- LLMが日本語テキストを引用または混入させる可能性
- 特に`temperature=0.9`（高い創造性）の場合、予期しない出力が発生しやすい

---

### ステップ3: プロンプト後処理

**処理内容:**
```python
# 391-392行目
prompt = self._enforce_quality_keywords(prompt)
```

**`_enforce_quality_keywords()`の処理:**
```python
# 459-484行目
def _enforce_quality_keywords(self, prompt: str) -> str:
    mandatory_quality_keywords = [
        "shot on Kodak Portra 400 film",
        "subtle film grain",
        "highly detailed"
    ]
    
    for keyword in mandatory_quality_keywords:
        if keyword.lower() not in prompt.lower():
            prompt += f", {keyword}"
    
    if "no text" not in prompt.lower():
        prompt += ", no text, no writing, no watermarks"
    
    return prompt
```

**⚠️ 問題点3:** この処理は**追加のみ**で、混入したテキストを除去しない

---

### ステップ4: ComfyUIClient.generate_image()

**ファイル:** `services/media_processing/comfyui_client.py`

**処理内容:**
```python
# 153行目
workflow[self.NODE_IDS["clip_text_pos"]]["inputs"]["text"] = prompt
```

**ワークフローJSON構造:**
```json
{
  "6": {
    "class_type": "CLIPTextEncode",
    "inputs": {
      "text": "[ここにプロンプトが設定される]",
      "clip": ["11", 1]
    }
  }
}
```

**⚠️ 問題点4:** `prompt`文字列がそのまま`text`フィールドに設定される。混入したテキストがあればそのまま送信される。

---

## 混入の原因（推測）

### 原因1: LLMの出力に日本語が混入

**シナリオ:**
```
入力:
Theme: 持続血糖測定器CGM FreeStyleリブレについて
Summary: 持続血糖測定器（CGM）は、皮膚に装着した小型センサーで血糖値を継続的に監視するデバイスである...

LLMの出力（不適切な例）:
A close-up of a continuous glucose monitor (持続血糖測定器) displaying real-time blood sugar graphs...
```

**原因:**
- LLMが日本語を引用してしまう
- システムプロンプトの指示が不十分
- `temperature=0.9`の高い創造性が予期しない出力を生む

### 原因2: フォールバック処理の問題

**フォールバックプロンプト:**
```python
# 508-514行目
return (
    f"A dramatic scene representing '{theme}', "  # ← themeが日本語のまま
    f"bathed in {color_desc}, "
    f"{aesthetic_desc}, "
    f"dynamic composition with depth, "
    f"shot on Kodak Portra 400 film, subtle film grain, highly detailed, no text"
)
```

**⚠️ 問題点5:** フォールバック時に`theme`（日本語）がそのまま埋め込まれる

---

## 検証方法

### 1. ログ確認

**確認すべきログ:**
```python
# image_prompt_generator.py 394行目
logger.info(f"Generated thumbnail prompt: {prompt[:100]}...")
console.print(f"[dim]Thumbnail prompt: {prompt[:80]}...[/dim]")
```

**確認手順:**
1. ComfyUIで画像生成を実行
2. コンソール出力で`[dim]Thumbnail prompt:`を確認
3. プロンプトに日本語が含まれているか確認

### 2. PromptOpsログ確認

**ファイル:** `output/[session_dir]/prompt_ops.jsonl`

**確認内容:**
```json
{
  "timestamp": "...",
  "context_type": "thumbnail",
  "prompt": "[ここに実際のプロンプトが記録される]",
  ...
}
```

---

## 改善提案

### 提案1: 日本語テキストを英語に翻訳してからLLMに渡す

**実装例:**
```python
# ImagePromptGenerator.generate_thumbnail_prompt() 内
# Step 1: Translate Japanese to English
theme_en = await self._translate_to_english(theme)
summary_en = await self._translate_to_english(script_summary[:300])

# Step 2: Use English text in user_message
user_message = f"""Generate a visually striking thumbnail background prompt for this video:

Theme: {theme_en}
Topic: {topic_title_en or theme_en}

Summary:
{summary_en}

Create a CONCRETE, SUBJECT-DRIVEN representation that maximizes click-through rate."""
```

**メリット:**
- LLMへの入力が完全に英語になる
- 日本語混入のリスクがゼロになる

**デメリット:**
- 追加のLLM呼び出しが必要（コスト増）
- 翻訳の精度に依存

---

### 提案2: システムプロンプトを強化

**現在のシステムプロンプト:**
```
OUTPUT FORMAT:
Return ONLY the English prompt text, no explanations.
```

**改善後:**
```
OUTPUT FORMAT:
Return ONLY the English prompt text, no explanations.

CRITICAL CONSTRAINT:
- Your output MUST be 100% English text
- DO NOT include any Japanese characters (日本語) in your output
- DO NOT quote or reference the input theme/summary text directly
- Translate all concepts to English before incorporating them
```

**メリット:**
- 実装が簡単（システムプロンプトの修正のみ）
- 追加コストなし

**デメリット:**
- LLMが指示に従わない可能性がある

---

### 提案3: 出力後のサニタイゼーション

**実装例:**
```python
def _sanitize_prompt(self, prompt: str) -> str:
    """Remove any non-English characters from prompt
    
    Args:
        prompt: Generated prompt
    
    Returns:
        str: Sanitized prompt (English only)
    """
    import re
    
    # Remove Japanese characters (Hiragana, Katakana, Kanji)
    sanitized = re.sub(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]+', '', prompt)
    
    # Remove extra spaces
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    
    # Log if sanitization occurred
    if sanitized != prompt:
        logger.warning(f"Prompt sanitized: removed non-English characters")
        logger.debug(f"Original: {prompt}")
        logger.debug(f"Sanitized: {sanitized}")
    
    return sanitized
```

**適用箇所:**
```python
# generate_thumbnail_prompt() 内
prompt = response.text.strip()
prompt = self._sanitize_prompt(prompt)  # ← 追加
prompt = self._enforce_quality_keywords(prompt)
```

**メリット:**
- 確実に日本語を除去できる
- 実装が簡単

**デメリット:**
- 意図的な日本語（例: 固有名詞）も削除される可能性
- プロンプトの意味が損なわれる可能性

---

### 提案4: フォールバックプロンプトの修正

**現在の問題:**
```python
return (
    f"A dramatic scene representing '{theme}', "  # ← themeが日本語
    ...
)
```

**改善後:**
```python
def _get_fallback_thumbnail_prompt(
    self,
    theme: str,
    visual_identity: Optional[VisualIdentity] = None
) -> str:
    # Translate theme to English or use generic description
    theme_en = "the video topic"  # Generic fallback
    
    # Try to extract English keywords from theme
    import re
    english_words = re.findall(r'[a-zA-Z]+', theme)
    if english_words:
        theme_en = ' '.join(english_words)
    
    if visual_identity:
        color_desc = visual_identity.to_color_fragment()
        aesthetic_desc = visual_identity.to_aesthetic_fragment()
    else:
        color_desc = self.DEFAULT_COLOR_PALETTE
        aesthetic_desc = f"{DEFAULT_AESTHETIC} aesthetic"
    
    return (
        f"A dramatic scene representing {theme_en}, "
        f"bathed in {color_desc}, "
        f"{aesthetic_desc}, "
        f"dynamic composition with depth, "
        f"shot on Kodak Portra 400 film, subtle film grain, highly detailed, no text"
    )
```

---

## 推奨アクション

### 優先度1: 即座に実装すべき対策

1. **提案3: 出力後のサニタイゼーション**
   - 確実に日本語を除去
   - 実装が簡単
   - リスクが低い

2. **提案4: フォールバックプロンプトの修正**
   - フォールバック時の日本語混入を防止

### 優先度2: 中期的な改善

3. **提案2: システムプロンプトの強化**
   - LLMの出力品質を向上
   - 追加コストなし

### 優先度3: 長期的な改善

4. **提案1: 日本語→英語翻訳**
   - 最も根本的な解決策
   - コストとのトレードオフを検討

---

## 検証手順

### 1. 現状確認

```bash
# 画像生成を実行し、ログを確認
python app.py

# PromptOpsログを確認
cat output/[session_dir]/prompt_ops.jsonl | jq '.prompt'
```

### 2. サニタイゼーション実装後の検証

```bash
# 同じテーマで画像生成を実行
# プロンプトに日本語が含まれていないことを確認
```

### 3. 画像品質の確認

- 生成された画像が意図通りの内容か確認
- サニタイゼーションによって意味が損なわれていないか確認

---

## 関連ファイル

| ファイル | 役割 |
|---------|------|
| `services/media_processing/thumbnail_background_generator.py` | サムネイル背景生成のエントリーポイント |
| `services/script_generation/image_prompt_generator.py` | LLMによる英語プロンプト生成 |
| `services/media_processing/comfyui_client.py` | ComfyUI APIクライアント |
| `config/workflow_api.json` | ComfyUIワークフロー定義 |

---

## まとめ

**問題の本質:**
- 日本語の`theme`と`script_summary`がLLMに渡される
- LLMが日本語を引用または混入させる可能性
- フォールバック時に日本語がそのまま埋め込まれる

**推奨対策:**
1. **即座:** 出力後のサニタイゼーション + フォールバックプロンプト修正
2. **中期:** システムプロンプトの強化
3. **長期:** 日本語→英語翻訳の実装

これにより、ComfyUI使用時の画像生成プロンプトから日本語テキストの混入を防止できます。
