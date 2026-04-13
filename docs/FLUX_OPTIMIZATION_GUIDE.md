# FLUX.1 メモリ最適化ガイド

## 概要

FLUX.1画像生成でメモリ不足・タイムアウトが発生する場合の対策をまとめたガイドです。

## サポートされるバックエンド

本プロジェクトでは、以下の2つの画像生成バックエンドをサポートしています：

| バックエンド | APIタイプ | 設定キー | 特徴 |
|-----------|----------|---------|------|
| Stable Diffusion WebUI Forge | 同期API | `forge` | 既定のバックエンド。解像度フォールバック機能あり |
| ComfyUI | 非同期ポーリングAPI | `comfyui` | より柔軟なワークフロー設定可能 |

**切り替え方法** (`config.yaml`):
```yaml
image_provider: "forge"  # "forge" または "comfyui"
```

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

### ✅ 優先度4: VRAM事前クリーンアップ（新規実装）

**実装箇所**: `services/media_processing/flux_client.py`

```python
async def _cleanup_vram_before_generation(self) -> bool:
    """Request VRAM cleanup from Forge API before generation"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(f"{self.base_url}/sdapi/v1/unload-checkpoint")
```

**効果**:
- 生成開始前にForge APIにモデルアンロードを要求
- VRAMを事前に解放し、タイムアウトリスクを低減
- `config.yaml`の`enable_pre_generation_cleanup: true`で有効化

---

### ✅ 優先度5: 段階的解像度フォールバック（新規実装）

**実装箇所**: `services/media_processing/flux_client.py`

```python
# タイムアウト時に解像度を段階的に下げて再試行
resolutions_to_try = [[896, 504], [768, 432], [640, 360]]
```

**効果**:
- 1回目のタイムアウト時、自動的に解像度を下げて再試行
- 最大3回まで自動リトライ（896x504 → 768x432 → 640x360）
- `config.yaml`の`enable_resolution_fallback: true`で有効化

**設定箇所**: `config.yaml`

```yaml
flux:
  enable_resolution_fallback: true
  fallback_resolutions:
    - [896, 504]   # 1st attempt
    - [768, 432]   # 2nd attempt
    - [640, 360]   # 3rd attempt
```

---

## ComfyUIバックエンド設定

### 設定ファイル (`config.yaml`)

```yaml
comfyui:
  base_url: "http://127.0.0.1:8188"  # ComfyUI API URL
  workflow_path: "config/workflow_api.json"  # ワークフローJSONのパス
  timeout: 600  # API timeout (seconds)
  
  # FLUX.1 [schnell] 最適化設定
  steps: 4       # ComfyUI用schnell最適化
  width: 768     # 解像度幅
  height: 432    # 解像度高さ
  cfg: 1.0       # CFG Scale (schnell最適化)
```

### ComfyUIワークフロー設定

ComfyUIでは`config/workflow_api.json`でワークフローを定義します。ノードIDは`ComfyUIClient.NODE_IDS`で管理されており、ワークフロー構造を変更する場合は以下の定数を更新してください：

```python
NODE_IDS = {
    "ksampler": "3",
    "checkpoint": "4",
    "empty_latent": "5",
    "clip_text_pos": "6",
    "clip_text_neg": "7",
    "vae_decode": "8",
    "save_image": "9",
}
```

### ComfyUIとForgeの違い

| 特徴 | Forge | ComfyUI |
|------|-------|---------|
| APIタイプ | 同期API | 非同期ポーリングAPI |
| 解像度フォールバック | ✓ 自動フォールバック | ✗ 手動設定のみ |
| ワークフロー柔軟性 | 低（固定） | 高（JSONでカスタマイズ可能） |
| VRAM事前クリーンアップ | ✓ APIサポート | ✗ 手動管理 |
| 並列制御 | ImageProviderセマフォ | ImageProviderセマフォ |

### ComfyUI最適化推奨設定

**FLUX.1 [schnell]向け最適化**:
- `steps: 4` - schnellモデル向けの最適値
- `cfg: 1.0` - 低CFGスケールで高速化
- `width/height: 768x432` - HD動画向けアスペクト比

---

## 優先度6: Forge起動オプション最適化

### 推奨設定（中程度のVRAM環境: 8GB）

Stable Diffusion WebUI Forgeの起動スクリプト（`webui-user.bat`または`webui-user.sh`）に以下を追加:

```bash
# Windows (webui-user.bat)
set COMMANDLINE_ARGS=--medvram-sdxl --opt-split-attention --no-half-vae --api --port 7890

# Linux/Mac (webui-user.sh)
export COMMANDLINE_ARGS="--medvram-sdxl --opt-split-attention --no-half-vae --api --port 7890"
```

**各オプションの説明**:
- `--medvram-sdxl`: SDXL/FLUX向けVRAM最適化（8GB VRAM推奨）
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

1. **段階的フォールバックが有効か確認** (`config.yaml`):
   ```yaml
   flux:
     timeout: 900  # 15分に延長
     enable_pre_generation_cleanup: true
     enable_resolution_fallback: true
   ```

2. **Forgeの起動オプションを確認**:
   - `--medvram-sdxl`または`--lowvram`が設定されているか
   - Forgeを再起動して設定を反映

3. **最小解像度をさらに下げる** (`config.yaml`):
   ```yaml
   flux:
     fallback_resolutions:
       - [768, 432]   # 1st attempt
       - [640, 360]   # 2nd attempt
       - [512, 288]   # 3rd attempt (最終手段)
   ```

4. **システムメモリ（RAM）を確認**:
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

| VRAM | 推奨設定 | 生成時間（896x504, 8steps） | タイムアウトリスク |
|------|---------|---------------------------|------------------|
| 12GB+ | デフォルト | 8〜15秒 | 極めて低い |
| 8GB | `--medvram-sdxl` | 15〜30秒 | 低い |
| 6GB | `--lowvram` | 30〜60秒 | 中程度 |
| 4GB | `--lowvram --no-half` | 60〜120秒 | 高い（フォールバック推奨） |

**注**: 上記は1回目の生成時間。2回目以降はモデルキャッシュにより高速化されます。

---

## 関連ファイル

- `config.yaml`: タイムアウト・解像度・フォールバック設定、バックエンド選択（`image_provider`）
- `services/media_processing/image_provider.py`: Semaphore実装、バックエンド切り替えロジック
- `services/media_processing/flux_client.py`: Forge APIクライアント、VRAM自動クリーンアップ、段階的フォールバック
- `services/media_processing/comfyui_client.py`: ComfyUI APIクライアント、非同期ポーリング
- `services/media_processing/thumbnail_background_generator.py`: サムネイル生成
- `config/workflow_api.json`: ComfyUIワークフロー定義

---

## 更新履歴

- **2026-04-12 (v3)**: ComfyUIバックエンド対応、ノードID定数化、一時ファイルクリーンアップ強化
- **2026-04-10 (v2)**: VRAM事前クリーンアップ、段階的解像度フォールバック機能を追加
- **2026-04-10 (v1)**: 初版作成（優先度1〜3の対策実装完了）
