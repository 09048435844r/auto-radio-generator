---
description: サムネイル再作成機能の自動テスト実行
---

# サムネイル再作成機能のテスト

## 概要
`generate_video_mock` のState生成と `ThumbnailGenerator.regenerate_with_new_title` の再作成ロジックを保護するための自動テストを実行します。

## 実行手順

### 1. テストファイルの場所
```
tests/test_thumbnail_regeneration.py
```

### 2. pytest でテスト実行
```bash
# プロジェクトルートで実行
python -m pytest tests/test_thumbnail_regeneration.py -v

# 特定のテストクラスのみ実行
python -m pytest tests/test_thumbnail_regeneration.py::TestThumbnailRegeneration -v

# カバレッジを含めて実行
python -m pytest tests/test_thumbnail_regeneration.py --cov=services.media_processing.thumbnail_generator --cov=app -v
```

### 3. テスト内容の確認

#### TestThumbnailRegenerationState
- Stateデータクラスの基本機能をテスト

#### TestGenerateVideoMock  
- `generate_video_mock` が7要素のタプルを返すことを確認
- 最後の要素が `ThumbnailRegenerationState` インスタンスであることを確認
- `use_mock=True` 引数が正しく渡されることを確認

#### TestThumbnailRegeneration
- `regenerate_with_new_title` の成功ケースをテスト
- GeminiClient API呼び出しが正しい引数で実行されることを確認
- 戻り値の形式 `(thumbnail_path, video_title, thumbnail_title)` を検証
- APIエラー時の例外処理をテスト

## テストの特徴

### モック化対象
- GeminiClient（外部API通信）
- Pillow Image（画像処理）
- os.path / os.makedirs（ファイルシステム）
- PromptManager（プロンプト管理）
- 内部メソッド（`_apply_effects`, `_draw_title_text`, `_draw_date_badge`）

### 高速実行
すべての外部依存がモック化されているため、数秒で全テストが完了します。

### 回帰テストとしての役割
Gradio 4.0アップデート時や将来の機能変更時に、既存のロジックが破壊されていないことを確認します。

## 実行頻度
- コミット前のローカルテスト
- CI/CDパイプラインでの自動実行
- 大規模なリファクタリング前後の確認

## トラブルシューティング

### テスト失敗時の確認点
1. importパスが正しいか（モジュール構成の変更）
2. メソッドシグネチャの変更（引数の追加/削除）
3. 戻り値の形式変更
4. 外部ライブラリのバージョンアップによる影響

### デバッグ方法
```bash
# 詳細な出力でテスト実行
python -m pytest tests/test_thumbnail_regeneration.py -v -s

# 特定のテストをデバッグモードで実行
python -m pytest tests/test_thumbnail_regeneration.py::TestThumbnailRegeneration::test_regenerate_with_new_title_success -v -s --pdb
```
