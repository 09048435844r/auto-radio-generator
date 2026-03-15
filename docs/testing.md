# テストドキュメント

## 概要
Auto Radio Generator プロジェクトのテスト戦略と実行方法について説明します。

## テスト構成

### 1. サムネイル再作成機能テスト
- **ファイル**: `tests/test_thumbnail_regeneration.py`
- **目的**: `generate_video_mock` のState生成とサムネイル再作成ロジックを保護
- **実行**: `python -m pytest tests/test_thumbnail_regeneration.py -v`

#### テストクラス
- `TestThumbnailRegenerationState`: Stateデータクラスの基本機能
- `TestGenerateVideoMock`: generate_video_mock の戻り値と呼び出し引数
- `TestThumbnailRegeneration`: サムネイル再作成の成功・失敗ケース

#### モック対象
- GeminiClient（外部API）
- Pillow Image（画像処理）
- os.path/os.makedirs（ファイルシステム）
- PromptManager（プロンプト管理）
- 内部メソッド（`_apply_effects`, `_draw_title_text`, `_draw_date_badge`）

## テスト実行

### 基本コマンド
```bash
# 全テスト実行
python -m pytest tests/ -v

# 特定のテストファイル
python -m pytest tests/test_thumbnail_regeneration.py -v

# カバレッジ付き
python -m pytest tests/ --cov=. --cov-report=html
```

### CI/CDでの実行
- GitHub Actionsで自動実行
- プルリクエストごとにテスト実行
- カバレッジレポートの生成

## テスト戦略

### 単体テスト
- 個別の関数やクラスの機能テスト
- 外部依存をモック化して高速実行

### 統合テスト
- 複数のコンポーネント連携テスト
- 実際のAPIやファイルシステムを使用

### 回帰テスト
- 既存機能が破壊されていないことを確認
- Gradio 4.0アップデート時の検証

## テストガイドライン

### 新機能開発時
1. 機能実装前にテストケースを定義
2. TDD（テスト駆動開発）を推奨
3. カバレッジ80%以上を目標

### 既存機能変更時
1. 既存テストがPASSすることを確認
2. 必要に応じてテストを更新
3. レグレッションバグを防ぐ

### テスト命名規則
- テストクラス: `Test{ClassName}`
- テストメソッド: `test_{functionality}_{scenario}`
- ファイル名: `test_{module_name}.py`

## トラブルシューティング

### よくある問題
1. **Import Error**: モジュールパスの確認
2. **Mock Failure**: モック設定の見直し
3. **Async Test**: pytest-asyncioの使用

### デバッグ方法
```bash
# 詳細出力
pytest -v -s tests/

# 特定テストのデバッグ
pytest tests/test_file.py::TestClass::test_method -v -s --pdb

# カバレッジレポート
pytest --cov=. --cov-report=term-missing
```

## 継続的インテグレーション

### GitHub Actions設定
- Python 3.10+ のサポート
- 依存関係の自動インストール
- テスト並列実行による高速化
- カバレッジバッジの生成

### 品質ゲート
- 全テストPASS
- カバレッジ率80%以上
- リントチェック（flake8, black）
- セキュリティスキャン（bandit）
