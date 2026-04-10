# FLUX.1 メモリ最適化ガイド

## 概要

FLUX.1画像生成でメモリ不足・タイムアウトが発生する場合の対策をまとめたガイドです。

---

## 実装済み対策

### ✅ 優先度1: 並列生成の制限（Semaphore）

**実装箇所**: `services/media_processing/image_provider.py`

```python
class ImageProvider:
    # クラスレベルのセマフォで同時生成数を1に制限
    _generation_semaphore = asyncio.Semaphore(1)
```

**効果**:
- 複数セグメントの並列処理時でも、FLUX.1生成は1つずつ順番に実行
- VRAM競合を完全に防止
- タイムアウト発生率が大幅に低下

---

### ✅ 優先度2: メモリ解放の強制

**実装箇所**: `services/media_processing/flux_client.py`

```python
finally:
    # VRAM自動クリーンアップ
    import torch
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
    gc.collect()
```

**効果**:
- 各生成完了後、VRAMを明示的に解放
- 次の生成に向けてメモリを確保
- 長時間実行時のメモリリーク防止

---

### ✅ 優先度3: タイムアウト延長

**設定箇所**: `config.yaml`

```yaml
flux:
  timeout: 600  # 300秒 → 600秒に延長
```

**効果**:
- 初回モデルロード時の余裕を確保
- 低VRAM環境でのスワップ処理に対応

---

## 優先度4: Forge起動オプション最適化

### 推奨設定（中程度のVRAM環境）

Stable Diffusion WebUI Forgeの起動スクリプト（`webui-user.bat`または`webui-user.sh`）に以下を追加:

```bash
# Windows (webui-user.bat)
set COMMANDLINE_ARGS=--medvram --opt-split-attention --no-half-vae --api --port 7890

# Linux/Mac (webui-user.sh)
export COMMANDLINE_ARGS="--medvram --opt-split-attention --no-half-vae --api --port 7890"
```

**各オプションの説明**:
- `--medvram`: 中程度のVRAM最適化（8GB VRAM推奨）
- `--opt-split-attention`: Attention計算の最適化（メモリ効率向上）
- `--no-half-vae`: VAEの精度を保ちつつメモリ節約
- `--api`: API機能を有効化（必須）
- `--port 7890`: APIポート指定

---

### 低VRAM環境向け設定（6GB以下）

```bash
# より積極的なメモリ最適化
set COMMANDLINE_ARGS=--lowvram --opt-sdp-attention --no-half-vae --api --port 7890
```

**追加オプション**:
- `--lowvram`: 低VRAM環境向け最適化（速度は犠牲になる）
- `--opt-sdp-attention`: Scaled Dot Product Attention（PyTorch 2.0+で高速化）

---

### 超低VRAM環境向け設定（4GB以下）

```bash
# 最大限のメモリ節約（生成速度は大幅に低下）
set COMMANDLINE_ARGS=--lowvram --opt-sdp-attention --no-half --precision full --api --port 7890
```

**追加オプション**:
- `--no-half`: 半精度演算を無効化（メモリ消費増だが安定性向上）
- `--precision full`: 完全精度モード（メモリ節約優先）

---

## トラブルシューティング

### タイムアウトが依然として発生する場合

1. **解像度をさらに下げる** (`config.yaml`):
   ```yaml
   flux:
     width: 896   # 1024 → 896
     height: 504  # 576 → 504
     steps: 8     # 10 → 8
   ```

2. **Forgeのモデルキャッシュをクリア**:
   - Forge WebUIの設定から「Unload SD checkpoint to free VRAM」を有効化

3. **システムメモリ（RAM）を確認**:
   - VRAMが不足するとシステムRAMにスワップされ、極端に遅くなる
   - 最低16GB RAM推奨

---

### 生成が途中で停止する場合

1. **Forgeのログを確認**:
   ```bash
   # Forgeコンソールで以下のエラーを確認
   CUDA out of memory
   RuntimeError: CUDA error
   ```

2. **Windowsタスクマネージャー / nvidia-smiでVRAM使用量を監視**:
   ```bash
   nvidia-smi -l 1  # 1秒ごとに更新
   ```

3. **他のGPUプロセスを終了**:
   - ブラウザのハードウェアアクセラレーション
   - ゲーム・動画編集ソフト
   - 他のAIモデル

---

## パフォーマンス目安

| VRAM | 推奨設定 | 生成時間（1024x576, 10steps） |
|------|---------|------------------------------|
| 12GB+ | デフォルト | 10〜20秒 |
| 8GB | `--medvram` | 20〜40秒 |
| 6GB | `--lowvram` | 40〜80秒 |
| 4GB | `--lowvram --no-half` | 80〜180秒 |

---

## 関連ファイル

- `config.yaml`: タイムアウト・解像度設定
- `services/media_processing/image_provider.py`: Semaphore実装
- `services/media_processing/flux_client.py`: VRAM自動クリーンアップ
- `services/media_processing/thumbnail_background_generator.py`: サムネイル生成

---

## 更新履歴

- **2026-04-10**: 初版作成（優先度1〜4の対策実装完了）
