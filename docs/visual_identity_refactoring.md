# Visual Identity & Dynamic Composition Architecture - Implementation Summary

**実装日**: 2026-03-30  
**バージョン**: v3.5.0+

## 概要

FLUX.1画像生成パイプラインを、統一されたビジュアルアイデンティティ（Color Palette + Aesthetic Style）と動的な映像表現を両立させるアーキテクチャへリファクタリングしました。

## 実装内容

### Phase 1: Data Model Extension

**ファイル**: `core/models/visual.py`

- **`VisualIdentity`** クラスを新規追加
  - Color Palette: `primary_color`, `secondary_color`, `color_mood`
  - Aesthetic Style: `aesthetic`, `visual_keywords`
  - メソッド: `to_color_fragment()`, `to_aesthetic_fragment()`, `to_prompt_fragment()`

- **`VisualPalette`** を `VisualIdentity` のサブクラスとして再定義
  - 後方互換性を完全に維持
  - `mood` フィールドを `color_mood` に自動マッピング
  - 新規フィールド（`aesthetic`, `visual_keywords`）にデフォルト値を提供

### Phase 2: Generator Enhancement

**ファイル**: `services/script_generation/visual_palette_generator.py`

- **`VisualPaletteGenerator`** を拡張
  - `generate_identity()`: 完全な `VisualIdentity` を生成（新規）
  - `generate_palette()`: 後方互換性ラッパー（既存コードとの互換性維持）
  
- **SYSTEM_PROMPT** を拡張
  - Aesthetic Style の選択肢を追加
    - Clean Minimalist Modern
    - Cozy Lo-fi Studio
    - Dystopian Industrial
    - Retro Arcade
    - Clinical Futuristic
    - Neon Cyberpunk
    - Warm Analog
  - Visual Keywords（3-5個）の生成を追加

- **例**: 医学テーマ → `"Clean Minimalist Modern"` + `["clinical", "sterile", "high-tech"]`

### Phase 3: Prompt Generator Refactoring

**ファイル**: `services/script_generation/image_prompt_generator.py`

#### 3.1 Dynamic Aesthetic Injection

- **SYSTEM_PROMPT_TEMPLATE** を更新
  - `{aesthetic}` プレースホルダーを追加
  - 固定の `"vaporwave / cyberpunk fusion"` を動的な aesthetic に置き換え

#### 3.2 Decoupled Composition Guidance

**Before (過剰に具体的):**
```
- Camera: Wide establishing shot, aerial or distant perspective
- Lighting: Dawn or dusk lighting for dramatic introduction
```

**After (ムードとフォーカスのみ):**
```
- Narrative Role: Scene-setting, establishing context
- Emotional Tone: Inviting, atmospheric, welcoming
- Visual Focus: Overall environment and spatial context
- Suggested Approach: Create a sense of place
```

**削除した要素:**
- ❌ 具体的な構図指示（`"Wide shot"`, `"aerial perspective"`）
- ❌ 具体的なライティング指示（`"Dawn lighting"`, `"Focused spotlights"`）
- ❌ カメラワーク強制（`"close-up"`, `"pull-back"`）

**保持した要素:**
- ✅ Film quality keywords（`"shot on Kodak Portra 400 film, subtle film grain, highly detailed"`）
- ✅ `"no text"` (必須)

#### 3.3 Creative Freedom Declaration

新しいプロンプトテンプレートに明示的な創造的自由を宣言：
```
CREATIVE FREEDOM:
- Camera angles, distances, and framing: YOUR CHOICE
- Lighting style and mood: YOUR CHOICE
- Composition and visual storytelling: YOUR CHOICE
```

### Phase 4: Component Integration

**ファイル**: 
- `services/media_processing/image_provider.py`
- `services/media_processing/thumbnail_background_generator.py`

- **`ImageProvider`** を更新
  - `visual_identity` パラメータを追加
  - `visual_palette` との後方互換性を維持
  - プロンプト生成時に `visual_identity` を渡す

- **`ThumbnailBackgroundGenerator`** を更新
  - `visual_identity` パラメータを追加
  - サムネイル生成時に統一されたブランドを適用

## 後方互換性

すべての変更は**完全な後方互換性**を維持しています：

1. **`VisualPalette`** は引き続き使用可能
   - `VisualIdentity` のサブクラスとして実装
   - 既存の `mood` フィールドは `color_mood` に自動マッピング
   - 新規フィールドにはデフォルト値を自動設定

2. **既存のメソッドシグネチャ**
   - `generate_palette()` は引き続き動作
   - `visual_palette` パラメータは引き続きサポート
   - 新しい `visual_identity` パラメータはオプショナル

3. **段階的移行が可能**
   - 既存コードは無変更で動作
   - 新機能は `visual_identity` を使用することで利用可能

## 期待される効果

### Before (リファクタリング前)

❌ **固定された画風**
- 全動画が `"vaporwave / cyberpunk fusion"` で統一
- テーマに応じた画風の変化がない

❌ **過剰な構図制約**
- `"Wide establishing shot"` などの具体的な指示でLLMの創造性を制限
- 全セグメントが似た絵面になる

### After (リファクタリング後)

✅ **テーマごとの固有ブランド**
- 医学テーマ → `"Clean Minimalist Modern"` + `["clinical", "sterile", "high-tech"]`
- 音楽テーマ → `"Cozy Lo-fi Studio"` + `["warm", "analog", "intimate"]`
- 都市伝説 → `"Dystopian Industrial"` + `["gritty", "dark", "ominous"]`

✅ **動的な映像表現**
- LLMが創造的に構図を選択
- ナラティブに応じたカメラワーク（intro: 引き、deep_dive: 寄り、conclusion: 余韻）
- セグメント間で視覚的多様性を保ちつつ、動画全体の統一感を維持

✅ **ブランドの一貫性**
- Color Palette と Aesthetic が全セグメント・サムネイルに統一適用
- 動画ごとの独自のビジュアルアイデンティティを確立

## 技術的詳細

### VisualIdentity データ構造

```python
class VisualIdentity(BaseModel):
    # Color Palette
    primary_color: str          # "electric cyan"
    secondary_color: str        # "hot magenta"
    color_mood: str            # "futuristic medical"
    
    # Aesthetic Style
    aesthetic: str             # "Clean Minimalist Modern"
    visual_keywords: list[str] # ["clinical", "sterile", "high-tech"]
    
    # Metadata
    reasoning: str             # LLM reasoning
    
    # Methods
    def to_color_fragment() -> str
    def to_aesthetic_fragment() -> str
    def to_prompt_fragment() -> str
```

### Composition Guidance マッピング

| Segment Type | Narrative Role | Emotional Tone | Visual Focus |
|--------------|----------------|----------------|--------------|
| `intro` | Scene-setting | Inviting, atmospheric | Overall environment |
| `deep_dive` | Investigation | Intense, analytical | Specific details |
| `conclusion` | Reflection | Contemplative, hopeful | Emotional resonance |

### LLM Prompt 構造

```
UNIFIED VISUAL BRAND (MANDATORY):
- Color Palette: {primary_color} and {secondary_color} neon lighting
- Aesthetic: {aesthetic} aesthetic, {visual_keywords}
- Film Quality: shot on Kodak Portra 400 film, subtle film grain, highly detailed

NARRATIVE GUIDANCE (FLEXIBLE):
- Narrative Role: [role based on segment type]
- Emotional Tone: [tone based on segment type]
- Visual Focus: [focus based on segment type]

CREATIVE FREEDOM:
- Camera angles, distances, and framing: YOUR CHOICE
- Lighting style and mood: YOUR CHOICE
- Composition and visual storytelling: YOUR CHOICE
```

## 検証

すべての修正ファイルが Python コンパイルテストに合格：
- ✅ `core/models/visual.py`
- ✅ `services/script_generation/visual_palette_generator.py`
- ✅ `services/script_generation/image_prompt_generator.py`
- ✅ `services/media_processing/image_provider.py`
- ✅ `services/media_processing/thumbnail_background_generator.py`

## 次のステップ

1. **実際の動画生成でテスト**
   - 異なるテーマで動画を生成し、Aesthetic の多様性を確認
   - セグメント間の視覚的多様性を確認

2. **Aesthetic のバリエーション拡張**
   - ユーザーフィードバックに基づいて新しい Aesthetic スタイルを追加
   - テーマと Aesthetic のマッピングを最適化

3. **パフォーマンス監視**
   - LLM による Aesthetic 生成の品質を監視
   - フォールバック頻度を確認

## 関連ドキュメント

- 設計計画: `C:\Users\09048\.windsurf\plans\visual-identity-refactor-dcc621.md`
- CHANGELOG: `CHANGELOG.md` (Unreleased セクション)
- プロジェクト現況: `PROJECT_CURRENT_STATUS.md`
