# Mock Mode - 開発用固定データモード

このディレクトリは、APIを使用せずにローカルの固定データで動作する「Mockモード」用のデータ格納場所です。

---

## 📋 概要

**Mock Mode**を有効にすると、以下のメリットがあります：

1. **API課金の節約**: Perplexity/Gemini APIを呼び出さずに開発・テストが可能
2. **高速な反復開発**: ネットワーク遅延・音声合成待ちなしで即座に結果を確認
3. **再現性の確保**: 同じデータで何度でもテストできる
4. **オフライン開発**: インターネット接続・VOICEVOXエンジン不要

---

## 🚀 使用方法

### 1. モックデータの準備

`output/` フォルダから過去の実行結果をコピーします：

```bash
# 例: 過去の実行結果からコピー
copy output\20260205_203915\research.json tests\mock_data\research.json
copy output\20260205_203915\script.json tests\mock_data\script.json
copy output\20260205_203915\combined_audio.wav tests\mock_data\audio\combined_audio.wav
```

**必要なファイル:**
- `research.json` - リサーチ結果データ
- `script.json` - 台本データ
- `audio/combined_audio.wav` - 音声データ（音声合成をスキップ）

### 2. Mock Modeの有効化

**方法A: UIスイッチを使用（推奨）**

Web UIの自動生成タブで、Mockモードチェックボックスをオンにします：

```
🔴【開発用】Mockモード (リサーチ・台本・音声を固定データでスキップ) ☑
```

このチェックボックスをオンにすると、`config.yaml` の設定に関係なく、その実行のみMockモードが有効になります。

**方法B: config.yamlを編集**

`config.yaml` を編集して、`dev.mock_mode` を `true` に変更します：

```yaml
dev:
  mock_mode: true  # ← falseからtrueに変更
  mock_data_path: "tests/mock_data"
```

この方法では、すべての実行でMockモードが有効になります。

### 3. 通常通り実行

Web UIまたはCLIから通常通り実行します。APIは呼び出されず、モックデータが使用されます。

```bash
# Web UI起動
python app.py
```

**実行時の表示:**
```
🔴 Mockモードが有効化されました
⚠ MOCK MODE: Using data from tests\mock_data\research.json
⚠ MOCK MODE: Using data from tests\mock_data\script.json
⚠ MOCK MODE: Using audio from tests\mock_data\audio\combined_audio.wav
✓ Mock音声を使用しました (120.5秒)
```

---

## 📁 ファイル形式

### `research.json`

Perplexity APIのリサーチ結果を格納します。

**必須フィールド:**
```json
{
  "query": "検索クエリ",
  "raw_content": "リサーチ結果のテキスト",
  "sources": [
    {
      "title": "ソースのタイトル",
      "url": "https://example.com",
      "snippet": "引用スニペット（オプション）"
    }
  ],
  "timestamp": "2026-02-05T23:00:00",
  "provider": "perplexity"
}
```

**後方互換性フィールド（旧形式も対応）:**
- `mode`: リサーチモード（例: "trivia", "debate"）
- `content`: `raw_content` の別名

### `script.json`

Gemini APIの台本生成結果を格納します。

**必須フィールド:**
```json
{
  "title": "動画タイトル",
  "theme": "テーマ",
  "sections": [
    {
      "speaker": "A",
      "text": "セリフ本文",
      "emotion": "joy"
    }
  ],
  "thumbnail_title": "サムネイル用タイトル",
  "description": "概要欄テキスト"
}
```

**後方互換性フィールド（旧形式も対応）:**
- `dialogue`: `sections` の別名
- `speaker_id`: `"main"` → `"A"`, `"sub"` → `"B"` に自動変換

### `audio/combined_audio.wav`

VOICEVOX音声合成の結果を格納します。

**形式:**
- WAV形式（16bit PCM推奨）
- サンプリングレート: 任意（24000Hz推奨）
- チャンネル数: モノラル/ステレオどちらでも可

**取得方法:**
```bash
# 過去の実行結果からコピー
copy output\20260205_203915\combined_audio.wav tests\mock_data\audio\combined_audio.wav
```

**注意:**
- Mockモードでは、チャプター情報は生成されません
- 字幕ファイル（.srt）も生成されません
- 音声の長さは自動的に検出されます

---

## ⚙️ 設定詳細

### `config.yaml` の `dev` セクション

```yaml
dev:
  mock_mode: false  # trueでMockモード有効化
  mock_data_path: "tests/mock_data"  # モックデータの格納ディレクトリ
```

**デフォルト動作:**
- `mock_mode: false` - 通常のAPI実行
- `mock_mode: true` - モックデータを使用

**フォールバック:**
- モックファイルが見つからない場合、自動的に通常のAPI実行にフォールバック
- エラーログが表示されますが、処理は継続します

---

## 🔍 デバッグ情報

### Mock Mode有効時の出力例

```
🔴 Mockモードが有効化されました

[yellow]⚠ MOCK MODE: Using data from tests\mock_data\research.json[/yellow]
[green]✓ リサーチ完了[/green] (1234文字)

[yellow]⚠ MOCK MODE: Using data from tests\mock_data\script.json[/yellow]
[green]✓ Pydanticバリデーション成功[/green]
  総ターン数: 52
[green]✓ 台本生成完了[/green] 対話数: 52
  トークン: 入力 0 / 出力 0

[yellow]⚠ MOCK MODE: Using audio from tests\mock_data\audio\combined_audio.wav[/yellow]
[green]✓ Mock音声を使用しました[/green] (120.5秒)

🔴 Mockモード設定を元に戻しました
```

### モックファイルが見つからない場合

```
[red]✗ Mock data not found at tests\mock_data\research.json[/red]
[yellow]  Falling back to normal API execution...[/yellow]
[cyan]Perplexity でリサーチ中...[/cyan]
```

---

## 🧪 テストシナリオ

### 1. 基本的な動作確認（UIスイッチ使用）

```bash
# 1. モックデータをコピー
copy output\最新のフォルダ\research.json tests\mock_data\
copy output\最新のフォルダ\script.json tests\mock_data\
copy output\最新のフォルダ\combined_audio.wav tests\mock_data\audio\

# 2. Web UI起動
python app.py

# 3. 自動生成タブで以下を設定:
#    - テーマ: 任意のテーマを入力
#    - Mockモードチェックボックス: ☑ オン
#    - 「動画を生成する」ボタンをクリック

# 4. 確認事項:
#    - リサーチ、台本、音声がすべてMockデータから読み込まれる
#    - API呼び出しが発生しない（トークン使用量が0）
#    - 数秒で動画生成が完了する
```

### 2. Pydanticバリデーションのテスト

```bash
# 不正なデータでバリデーションエラーを確認
# script.json の sections を空配列にする
# → "最低10ターン以上" のエラーが表示されるはず
```

### 3. 後方互換性のテスト

```bash
# 旧形式のデータを使用
# dialogue フィールドを使用した古い script.json
# → 自動的に sections に変換される
```

---

## 📝 注意事項

1. **本番環境では無効化**: `config.yaml` の `mock_mode` を必ず `false` に戻してください
2. **データの更新**: モックデータは定期的に最新の実行結果で更新することを推奨
3. **バージョン管理**: モックデータは `.gitignore` に含まれていないため、必要に応じて Git に追加してください
4. **セキュリティ**: モックデータに機密情報が含まれていないか確認してください

---

## 🔧 トラブルシューティング

### Q: Mock Modeが有効にならない

**A:** 以下を確認してください：
1. `config.yaml` の `dev.mock_mode` が `true` になっているか
2. `tests/mock_data/` ディレクトリが存在するか
3. `research.json` と `script.json` が正しい形式か

### Q: バリデーションエラーが発生する

**A:** モックデータが新しいPydanticスキーマに準拠しているか確認してください：
- `sections` フィールドが存在し、最低10ターン以上あるか
- `speaker` フィールドが `"A"` または `"B"` か
- `text` フィールドが空文字でないか

### Q: 旧形式のデータを使いたい

**A:** 後方互換性があるため、そのまま使用できます：
- `dialogue` → `sections` 自動変換
- `speaker_id: "main"` → `speaker: "A"` 自動変換
- `content` → `raw_content` 自動変換

---

## 📚 関連ファイル

- `config.yaml` - Mock Mode設定
- `app.py` - UIスイッチ（Mockモードチェックボックス）
- `workflow.py` - Mockモード設定のオーバーライド処理
- `services/research/perplexity_client.py` - リサーチのMockロジック
- `services/script_generation/gemini_client.py` - 台本生成のMockロジック
- `services/audio_synthesis/voicevox_client.py` - 音声合成のMockロジック
- `core/models/script.py` - 台本データモデル（Pydantic）
- `core/models/research.py` - リサーチ結果モデル（Pydantic）

---

## 🎯 開発効率の最大化

**Mock Modeを活用すると:**
- ⚡ **リサーチ**: 数秒 → 即座（ファイル読み込み）
- ⚡ **台本生成**: 30秒 → 即座（ファイル読み込み）
- ⚡ **音声合成**: 2-5分 → 即座（ファイルコピー）
- 💰 **API課金**: あり → なし
- 🔌 **依存関係**: VOICEVOX必須 → 不要

**合計時間短縮: 3-6分 → 数秒**

開発・テスト・デバッグの反復速度が劇的に向上します！

---

**開発効率を高めるため、積極的にMock Modeを活用してください！**
