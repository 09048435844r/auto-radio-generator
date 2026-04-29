# セグメント単位の動画レンダリング機能

## 概要

v3.5.0で実装された、セグメント単位での背景画像切り替えとジングル挿入機能のドキュメントです。

## アーキテクチャ

### 3フェーズパイプライン

従来のモノリシックなFFmpegコマンドを廃止し、以下の3フェーズに分割：

```
Phase A: Timeline Calculation
  ↓ VideoTimeline
Phase B: Independent Rendering (並列実行可能)
  ├─ Video Track (無音映像、セグメント単位で背景切り替え)
  └─ Audio Track (完全ミックス済み音声: メイン + BGM + ジングル)
  ↓
Phase C: Muxing (再エンコードなし、高速結合)
  ↓
Final Video
```

### 主要コンポーネント

#### 1. データモデル (`core/models/timeline.py`)
- `SegmentTimelineEntry`: 1セグメントのタイムライン情報
- `VideoTimeline`: 動画全体のタイムライン
- `SegmentTiming`: セグメント単位の音声タイミング情報

#### 2. プロバイダー
- `ImageProvider` (`services/media_processing/image_provider.py`): 背景画像提供
  - 静的モード: `assets/backgrounds/`から選択
  - 動的モード: FLUX.1で生成（ForgeまたはComfyUIバックエンド）
- `JingleProvider` (`services/media_processing/jingle_provider.py`): ジングル音声提供
  - `assets/jingles/`からランダム選択

#### 3. レンダラー
- `TimelineCalculator` (`services/video_rendering/timeline_calculator.py`): Phase A
- `VideoTrackRenderer` (`services/video_rendering/video_track_renderer.py`): Phase B (Video)
- `AudioTrackRenderer` (`services/video_rendering/audio_track_renderer.py`): Phase B (Audio)
- `FfmpegRenderer` (リファクタリング済み): 3フェーズパイプラインのオーケストレーター

## 使用方法

### 設定ファイル (`config.yaml`)

```yaml
video_renderer:
  # セグメント単位の背景画像切り替え設定
  background_mode: "static"  # "static": ローカルアセット選択 | "dynamic": DALL-E 3動的生成
  
  # ジングル設定（セグメント境界での演出）
  enable_jingles: true       # ジングル挿入を有効化
  jingle_overlap_sec: 3.0    # ジングルをセグメント終了の何秒前から被せるか

dev:
  keep_temp_files: false     # true: 中間ファイルを削除しない（デバッグ用）
```

### ジングルファイルの配置

```
assets/
  jingles/
    transition_01.mp3
    transition_02.mp3
    transition_03.wav
    ...
```

対応フォーマット: `.mp3`, `.wav`, `.ogg`, `.m4a`

### 背景画像の配置（静的モード）

```
assets/
  backgrounds/
    intro_01.png          # イントロ用
    intro_02.png
    deep_dive_01.png      # 深掘りセグメント用
    deep_dive_02.png
    conclusion_01.png     # 結論用
    default_01.png        # フォールバック用
```

命名規則: `{segment_type}_{番号}.png`

## データフロー

```
ScriptOrchestrator
  ↓ segments (ScriptSegment[])
VoicevoxClient.synthesize()
  ↓ SynthesisResult (segment_timings含む)
TimelineCalculator.calculate_timeline()
  ↓ VideoTimeline
┌─────────────────┴─────────────────┐
VideoTrackRenderer          AudioTrackRenderer
  ↓ video_track.mp4           ↓ audio_track.wav
└─────────────────┬─────────────────┘
                  ↓
            Muxing (再エンコードなし)
                  ↓
            final_video.mp4
```

## デバッグ

### 中間ファイルの確認

`config.yaml`で`dev.keep_temp_files: true`に設定すると、中間ファイルが保持されます：

```
output/{timestamp}/.temp/
  video_track.mp4   # 無音の映像トラック
  audio_track.wav   # 完全ミックス済み音声トラック
```

### ログ出力

各フェーズの進捗がコンソールに出力されます：

```
[cyan]Phase A: タイムライン計算中...[/cyan]
[green]✓ タイムライン計算完了: 3セグメント[/green]

[cyan]Phase B: 映像・音声トラック生成中...[/cyan]
[green]✓ 映像トラック生成完了: video_track.mp4[/green]
[green]✓ 音声トラック生成完了: audio_track.wav[/green]

[cyan]Phase C: 最終結合中...[/cyan]
[green]OK 動画生成完了[/green] radio_20260328_224500.mp4
  → サイズ: 45.2 MB, 長さ: 180.5秒
  → セグメント数: 3
```

## 後方互換性

`segments`パラメータが`None`の場合、自動的に単一背景画像モードで動作します（後方互換フォールバック）。

## トラブルシューティング

### ジングルが再生されない
- `assets/jingles/`ディレクトリが存在するか確認
- 対応フォーマット（.mp3, .wav, .ogg, .m4a）のファイルが配置されているか確認
- `config.yaml`で`enable_jingles: true`になっているか確認

### 背景画像が切り替わらない
- `ScriptOrchestrator`が有効になっているか確認（`config.yaml`の`script_generator.orchestrator.enabled: true`）
- セグメント情報が正しく生成されているか確認（ログに「セグメント数: X」が表示される）

### 音ズレが発生する
- 中間ファイルを確認（`keep_temp_files: true`）
- `video_track.mp4`と`audio_track.wav`を個別に再生して問題を切り分け
- タイムライン計算が正しいか確認（ログ出力を確認）

## パフォーマンス

- **Phase B**: 映像トラックと音声トラックを並列生成（約30-50%高速化）
- **Phase C**: 再エンコードなしで結合（数秒で完了）
- **全体**: 従来比で約20-40%の高速化を実現

## 将来の拡張

- [x] FLUX.1による動的背景画像生成（Forge/ComfyUIバックエンド対応済み）
- [ ] セグメント種別別のジングル選択
- [ ] トランジションエフェクト（クロスフェード等）
- [ ] セグメント単位のBGM変更
