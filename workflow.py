"""自動ラジオ動画生成システム - 共通ワークフロー関数

このモジュールは、CLIとWeb UI両方から呼び出せる
動画生成ワークフローを提供します。
"""
import asyncio
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Literal

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.models import (
    load_config, Script, AppConfig,
    TotalUsage, PerplexityUsage, GeminiUsage, VoicevoxUsage, CostBreakdown
)
from core.interfaces import IScriptGenerator, SynthesisResult, RenderResult, ResearchMode, ChapterMarker
from services.script_generation import GeminiClient
from services.research import PerplexityResearcher
from services.audio_synthesis import VoicevoxClient
from services.video_rendering import FfmpegRenderer
from services.media_processing import ThumbnailGenerator
from services.cost_calculator import CostCalculator


@dataclass
class UIOverrides:
    """UIから渡されるパラメータのオーバーライド設定"""
    research_mode: Optional[ResearchMode] = None  # "debate", "voices", "trivia"
    enable_research: bool = True                   # リサーチを有効化
    bgm_volume: Optional[float] = None             # 0.0 - 0.5
    fade_in_sec: Optional[float] = None            # 1.0 - 10.0
    fade_out_sec: Optional[float] = None           # 1.0 - 10.0
    enable_spectrum: Optional[bool] = None         # スペクトラム表示
    speed_scale: Optional[float] = None            # 音声スピード (0.8 - 1.5)
    # 素材選択
    background_image: Optional[str] = None         # 背景画像ファイル名
    bgm_file: Optional[str] = None                 # BGMファイル名


@dataclass
class WorkflowResult:
    """ワークフロー実行結果"""
    success: bool
    video_path: Optional[Path] = None
    script: Optional[Script] = None
    audio_path: Optional[Path] = None
    subtitle_path: Optional[Path] = None
    duration_sec: float = 0.0
    file_size_mb: float = 0.0
    error_message: Optional[str] = None
    # 使用量・コスト情報
    usage: Optional[TotalUsage] = None
    cost: Optional[CostBreakdown] = None
    cost_report: str = ""
    # メタデータ情報
    metadata_content: str = ""
    formatted_title: str = ""  # 日付入りタイトル（コピー用）
    formatted_description: str = ""  # 概要欄・チャプター結合版（コピー用）


@dataclass
class ProgressCallback:
    """進捗コールバック用クラス"""
    log_callback: Optional[Callable[[str], None]] = None
    progress_callback: Optional[Callable[[float, str], None]] = None
    
    def log(self, msg: str):
        """ログメッセージを送信"""
        if self.log_callback:
            self.log_callback(msg)
    
    def progress(self, ratio: float, description: str):
        """進捗を送信 (0.0〜1.0)"""
        if self.progress_callback:
            self.progress_callback(ratio, description)


class LogFileWriter:
    """ログをファイルに書き込むクラス"""
    
    def __init__(self, output_dir: Path):
        """初期化
        
        Args:
            output_dir: ログファイルを保存するディレクトリ
        """
        self.output_dir = output_dir
        self.log_path = output_dir / "processing_log.txt"
        self.logs: list[str] = []
        
        # ログファイルを初期化
        self.log_path.write_text(
            f"=== 自動ラジオ生成ログ ===\n"
            f"開始時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n",
            encoding="utf-8"
        )
    
    def write(self, msg: str):
        """ログメッセージを追記
        
        Args:
            msg: ログメッセージ
        """
        self.logs.append(msg)
        
        # ファイルに追記
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    
    def finalize(self):
        """ログファイルを完了"""
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(f"\n終了時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")


def create_script_generator(config: AppConfig) -> GeminiClient:
    """台本生成エンジン（Gemini）を作成"""
    return GeminiClient(config)


def create_researcher(config: AppConfig) -> PerplexityResearcher:
    """リサーチャー（Perplexity）を作成"""
    return PerplexityResearcher(config)


def apply_overrides(config: AppConfig, overrides: UIOverrides) -> AppConfig:
    """UIオーバーライドを設定に適用
    
    注意: Pydanticモデルはimmutableなので、新しい値で上書きする
    """
    if overrides.bgm_volume is not None:
        config.yaml.video_renderer.bgm_volume = overrides.bgm_volume
    
    if overrides.fade_in_sec is not None:
        config.yaml.video_renderer.bgm_fade_in_sec = overrides.fade_in_sec
    
    if overrides.fade_out_sec is not None:
        config.yaml.video_renderer.bgm_fade_out_sec = overrides.fade_out_sec
    
    if overrides.enable_spectrum is not None:
        config.yaml.video_renderer.enable_spectrum = overrides.enable_spectrum
    
    return config


async def check_prerequisites(
    config: AppConfig,
    log_callback: Optional[Callable[[str], None]] = None
) -> tuple[bool, str]:
    """前提条件をチェック
    
    Returns:
        (success, error_message)
    """
    def log(msg: str):
        if log_callback:
            log_callback(msg)
    
    # VOICEVOX確認
    log("VOICEVOXエンジンの接続を確認中...")
    voicevox = VoicevoxClient(config)
    if not await voicevox.check_engine_status():
        return False, "VOICEVOXエンジンに接続できません。エンジンを起動してください。"
    log("✓ VOICEVOXエンジン接続OK")
    
    # FFmpeg確認
    log("FFmpegの利用可能性を確認中...")
    ffmpeg = FfmpegRenderer(config)
    if not ffmpeg.check_ffmpeg_available():
        return False, "FFmpegが見つかりません。インストールしてください。"
    log("✓ FFmpeg利用可能")
    
    # アセット確認
    background_image = PROJECT_ROOT / config.yaml.paths.background_image
    bgm_file = PROJECT_ROOT / config.yaml.paths.bgm_file
    
    if not background_image.exists():
        return False, f"背景画像が見つかりません: {background_image}"
    log(f"✓ 背景画像: {background_image.name}")
    
    if not bgm_file.exists():
        return False, f"BGMファイルが見つかりません: {bgm_file}"
    log(f"✓ BGMファイル: {bgm_file.name}")
    
    return True, ""


async def generate_video_workflow(
    theme: str,
    overrides: Optional[UIOverrides] = None,
    log_callback: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None,
    project_root: Optional[Path] = None
) -> WorkflowResult:
    """動画生成ワークフローを実行
    
    Args:
        theme: 動画のテーマ
        overrides: UIからのパラメータオーバーライド
        log_callback: ログ出力用コールバック関数
        progress_callback: 進捗コールバック (ratio, description)
        project_root: プロジェクトルートパス
    
    Returns:
        WorkflowResult: 実行結果（Usage/Cost情報含む）
    """
    root = project_root or PROJECT_ROOT
    overrides = overrides or UIOverrides()
    workflow_start = time.time()
    
    # Usage集約用
    total_usage = TotalUsage()
    
    # ログファイルライター（出力ディレクトリ作成後に初期化）
    log_writer: Optional[LogFileWriter] = None
    
    def log(msg: str):
        if log_callback:
            log_callback(msg)
        # ログファイルにも書き込み
        if log_writer:
            log_writer.write(msg)
    
    def progress(ratio: float, desc: str):
        if progress_callback:
            progress_callback(ratio, desc)
    
    try:
        # ========== Phase 0: 設定読み込み (0-5%) ==========
        progress(0.0, "設定を読み込み中...")
        log("設定を読み込み中...")
        config = load_config(root)
        config = apply_overrides(config, overrides)
        
        # 素材パスのオーバーライド
        if overrides.background_image:
            config.yaml.paths.background_image = f"assets/backgrounds/{overrides.background_image}"
        if overrides.bgm_file:
            config.yaml.paths.bgm_file = f"assets/bgm/{overrides.bgm_file}"
        
        # 前提条件チェック
        progress(0.02, "前提条件を確認中...")
        success, error = await check_prerequisites(config, log_callback)
        if not success:
            return WorkflowResult(success=False, error_message=error)
        progress(0.05, "前提条件OK")
        
        # 出力ディレクトリを準備（リサーチ結果保存のため早期に作成）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_base = root / config.yaml.paths.output_dir / timestamp
        output_base.mkdir(parents=True, exist_ok=True)
        
        # ログファイルライターを初期化
        log_writer = LogFileWriter(output_base)
        log(f"出力ディレクトリ: {output_base}")
        
        # ========== Phase 1: リサーチ (5-20%) ==========
        research_data = None
        if overrides.enable_research and overrides.research_mode:
            progress(0.05, f"リサーチ中 ({overrides.research_mode})...")
            log(f"\n== リサーチ ==")
            log(f"テーマ: {theme}")
            log(f"モード: {overrides.research_mode}")
            log(f"[DEBUG] enable_research: {overrides.enable_research}")
            log(f"[DEBUG] research_mode: {overrides.research_mode}")
            
            research_start = time.time()
            try:
                researcher = create_researcher(config)
                research_data = await researcher.research(theme, overrides.research_mode)
                
                log(f"[DEBUG] リサーチAPI呼び出し完了")
                log(f"[DEBUG] research_data is None: {research_data is None}")
                
                # Usage記録
                if research_data and research_data.usage:
                    total_usage.perplexity = research_data.usage
                
                total_usage.research_duration_sec = time.time() - research_start
                
                if research_data:
                    log(f"✓ リサーチ完了: {len(research_data.content)}文字 ({total_usage.research_duration_sec:.1f}秒)")
                else:
                    log(f"⚠ リサーチデータがNullです")
                
                progress(0.20, "リサーチ完了")
                
            except Exception as e:
                log(f"⚠ リサーチスキップ（エラー）: {e}")
                import traceback
                log(f"[DEBUG] Traceback: {traceback.format_exc()}")
        else:
            log(f"[DEBUG] リサーチスキップ条件:")
            log(f"[DEBUG]   enable_research: {overrides.enable_research}")
            log(f"[DEBUG]   research_mode: {overrides.research_mode}")
            progress(0.20, "リサーチスキップ")
        
        # リサーチ結果をJSONで保存（リサーチブロックの外で実行）
        if research_data:
            try:
                from dataclasses import asdict
                import json
                
                log(f"[DEBUG] research.json保存処理開始")
                log(f"[DEBUG] research_data type: {type(research_data)}")
                log(f"[DEBUG] output_base: {output_base}")
                
                research_path = output_base / "research.json"
                research_path.parent.mkdir(parents=True, exist_ok=True)
                
                log(f"[DEBUG] 保存先パス: {research_path}")
                log(f"[DEBUG] ディレクトリ存在: {research_path.parent.exists()}")
                
                research_dict = asdict(research_data)
                log(f"[DEBUG] dataclass→dict変換完了")
                
                # usageは既にasdict()により辞書化済み
                if research_dict.get('usage'):
                    log(f"[DEBUG] usage type: {type(research_dict['usage'])}")
                    log(f"[DEBUG] usage辞書化済み（asdict()により自動変換）")
                
                json_str = json.dumps(research_dict, ensure_ascii=False, indent=2)
                log(f"[DEBUG] JSON文字列化完了 ({len(json_str)} 文字)")
                
                research_path.write_text(json_str, encoding="utf-8")
                log(f"✓ リサーチ結果保存: {research_path}")
                log(f"[DEBUG] ファイルサイズ: {research_path.stat().st_size} bytes")
                
                # Markdownレポートも保存（人間が読みやすい形式）
                report_path = output_base / "research_report.md"
                report_content = f"""# リサーチレポート

**テーマ**: {research_data.topic}
**モード**: {research_data.mode}
**生成日時**: {datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}

---

{research_data.content}
"""
                report_path.write_text(report_content, encoding="utf-8")
                log(f"✓ リサーチレポート保存: {report_path}")
                log(f"[DEBUG] レポートサイズ: {report_path.stat().st_size} bytes")
                
                # Perplexityの生データを全文保存（加工なし）
                full_report_path = output_base / "full_research_report.md"
                full_report_path.write_text(research_data.content, encoding="utf-8")
                log(f"✓ Perplexity全文レポート保存: {full_report_path}")
                log(f"[DEBUG] 全文レポートサイズ: {full_report_path.stat().st_size} bytes")
                
            except Exception as save_error:
                log(f"⚠ リサーチ結果保存エラー: {save_error}")
                import traceback
                log(f"[DEBUG] Traceback: {traceback.format_exc()}")
        else:
            log(f"[DEBUG] research_dataがNullのため保存スキップ")
        
        # ========== Phase 2: 台本生成 (20-35%) ==========
        progress(0.20, "台本を生成中...")
        log(f"\n== 台本生成 ==")
        log(f"テーマ: {theme}")
        log(f"使用エンジン: Gemini")
        
        script_start = time.time()
        script_generator = create_script_generator(config)
        script = script_generator.generate(theme, research_data)
        
        # Usage記録
        if script_generator.last_usage:
            total_usage.gemini = script_generator.last_usage
        
        total_usage.script_duration_sec = time.time() - script_start
        log(f"✓ 台本生成完了: {len(script.dialogue)}フレーズ ({total_usage.script_duration_sec:.1f}秒)")
        log(f"タイトル: {script.title}")
        progress(0.35, "台本生成完了")
        
        # 音声出力ディレクトリを準備
        audio_output_dir = output_base / "audio"
        video_output_path = output_base / "videos" / f"radio_{timestamp}.mp4"
        
        # ========== Phase 3: 音声合成 (35-75%) ==========
        progress(0.35, "音声合成中...")
        log(f"\n== 音声合成 ==")
        log(f"フレーズ数: {len(script.dialogue)}")
        
        audio_start = time.time()
        voicevox = VoicevoxClient(config)
        
        # 音声合成（進捗を更新）
        total_phrases = len(script.dialogue)
        synthesis_result = await voicevox.synthesize(
            script, 
            audio_output_dir,
            speed_scale_override=overrides.speed_scale
        )
        
        # Usage記録
        total_usage.voicevox = VoicevoxUsage(
            phrase_count=total_phrases,
            total_duration_sec=synthesis_result.total_duration_sec
        )
        total_usage.audio_duration_sec = time.time() - audio_start
        
        log(f"✓ 音声合成完了: {synthesis_result.total_duration_sec:.1f}秒 ({total_usage.audio_duration_sec:.1f}秒)")
        progress(0.75, "音声合成完了")
        
        # ========== Phase 4: 動画生成 (75-95%) ==========
        progress(0.75, "動画を生成中...")
        log(f"\n== 動画生成 ==")
        log(f"BGM音量: {config.yaml.video_renderer.bgm_volume}")
        log(f"フェードイン: {config.yaml.video_renderer.bgm_fade_in_sec}秒")
        log(f"フェードアウト: {config.yaml.video_renderer.bgm_fade_out_sec}秒")
        log(f"スペクトラム: {'ON' if config.yaml.video_renderer.enable_spectrum else 'OFF'}")
        
        render_start = time.time()
        background_image = root / config.yaml.paths.background_image
        bgm_file = root / config.yaml.paths.bgm_file
        
        ffmpeg = FfmpegRenderer(config)
        render_result = await ffmpeg.render(
            synthesis_result=synthesis_result,
            background_image=background_image,
            bgm_file=bgm_file,
            output_path=video_output_path,
            subtitle_path=synthesis_result.subtitle_path
        )
        
        total_usage.render_duration_sec = time.time() - render_start
        log(f"✓ 動画生成完了: {render_result.file_size_mb:.1f}MB ({total_usage.render_duration_sec:.1f}秒)")
        progress(0.95, "動画生成完了")
        
        # ========== Phase 5: 後処理 (95-100%) ==========
        progress(0.95, "後処理中...")
        
        # 台本をファイルに保存
        script_path = output_base / "script.json"
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(script.model_dump_json(indent=2), encoding="utf-8")
        
        # YouTube用メタデータを生成
        metadata_path = output_base / "metadata.txt"
        _generate_youtube_metadata(
            script=script,
            chapters=synthesis_result.chapters,
            output_path=metadata_path
        )
        log(f"✓ YouTubeメタデータ生成: {metadata_path.name}")
        
        # ログファイルを完了
        if log_writer:
            log_writer.finalize()
            log(f"✓ 処理ログ保存: {log_writer.log_path.name}")
        
        # メタデータの内容を読み込んでUIへ渡す
        metadata_content = metadata_path.read_text(encoding="utf-8")
        
        # 日付入りタイトルと概要欄結合版を生成
        creation_date = datetime.now().strftime("%Y.%m.%d")
        formatted_title = f"{script.title} ({creation_date}制作)"
        
        # チャプターリストを生成
        chapter_lines = []
        if synthesis_result.chapters:
            for chapter in synthesis_result.chapters:
                total_seconds = int(chapter.start_time_sec)
                minutes = total_seconds // 60
                seconds = total_seconds % 60
                timestamp = f"{minutes:02d}:{seconds:02d}"
                chapter_lines.append(f"{timestamp} {chapter.title}")
        
        # 概要欄結合（チャプター + 概要文 + ハッシュタグ）
        formatted_description_parts = []
        if chapter_lines:
            formatted_description_parts.append("\n".join(chapter_lines))
        formatted_description_parts.append(script.description)
        formatted_description_parts.append("#ずんだもん #VOICEVOX #AI #ラジオ")
        formatted_description = "\n\n".join(formatted_description_parts)
        
        # サムネイル画像を生成
        thumbnail_generator = ThumbnailGenerator()
        thumbnail_path = output_base / "thumbnail.png"
        thumbnail_generator.generate(
            title=script.title,
            thumbnail_title=script.thumbnail_title,
            background_path=background_image,
            output_path=thumbnail_path
        )
        log(f"✓ サムネイル画像生成: {thumbnail_path.name}")
        
        # 総所要時間
        total_usage.total_duration_sec = time.time() - workflow_start
        
        # コスト計算
        cost_calculator = CostCalculator()
        cost = cost_calculator.calculate(total_usage)
        cost_report = cost_calculator.format_cost_report(total_usage, cost)
        
        log(f"\n== 完了 ==")
        log(f"動画: {render_result.video_path}")
        log(f"総所要時間: {total_usage.total_duration_sec:.1f}秒")
        progress(1.0, "完了!")
        
        return WorkflowResult(
            success=True,
            video_path=render_result.video_path,
            script=script,
            audio_path=synthesis_result.audio_path,
            subtitle_path=synthesis_result.subtitle_path,
            duration_sec=render_result.duration_sec,
            file_size_mb=render_result.file_size_mb,
            usage=total_usage,
            cost=cost,
            cost_report=cost_report,
            metadata_content=metadata_content,
            formatted_title=formatted_title,
            formatted_description=formatted_description
        )
        
    except Exception as e:
        error_msg = f"エラーが発生しました: {str(e)}"
        log(f"\n❌ {error_msg}")
        
        # エラー時もログファイルを完了
        if log_writer:
            log_writer.finalize()
        
        return WorkflowResult(success=False, error_message=error_msg)


def run_workflow_sync(
    theme: str,
    overrides: Optional[UIOverrides] = None,
    log_callback: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None
) -> WorkflowResult:
    """同期版ワークフロー実行（Gradioから呼び出し用）"""
    return asyncio.run(generate_video_workflow(
        theme, overrides, log_callback, progress_callback
    ))


def scan_assets(project_root: Optional[Path] = None) -> dict[str, list[str]]:
    """アセットフォルダをスキャンしてファイル一覧を取得
    
    Args:
        project_root: プロジェクトルートパス
    
    Returns:
        dict: {"backgrounds": [...], "bgm": [...]}
    """
    root = project_root or PROJECT_ROOT
    
    backgrounds_dir = root / "assets" / "backgrounds"
    bgm_dir = root / "assets" / "bgm"
    
    # 背景画像 (png, jpg, jpeg)
    backgrounds = []
    if backgrounds_dir.exists():
        for ext in ["*.png", "*.jpg", "*.jpeg", "*.webp"]:
            backgrounds.extend([f.name for f in backgrounds_dir.glob(ext)])
    backgrounds.sort()
    
    # BGM (mp3, wav, m4a)
    bgm_files = []
    if bgm_dir.exists():
        for ext in ["*.mp3", "*.wav", "*.m4a", "*.ogg"]:
            bgm_files.extend([f.name for f in bgm_dir.glob(ext)])
    bgm_files.sort()
    
    return {
        "backgrounds": backgrounds,
        "bgm": bgm_files
    }


def _generate_youtube_metadata(
    script: Script,
    chapters: list[ChapterMarker],
    output_path: Path
) -> None:
    """YouTube投稿用のメタデータファイルを生成
    
    Args:
        script: 台本データ
        chapters: チャプターマーカーリスト
        output_path: 出力パス
    """
    lines = [
        "=" * 50,
        "YouTube 投稿用メタデータ",
        "=" * 50,
        "",
        "【タイトル】",
        script.title,
        "",
        "【説明文】",
        script.description,
        "",
    ]
    
    # チャプター情報を追加
    if chapters:
        lines.extend([
            "【チャプター】",
            "※ 以下をYouTubeの説明欄にコピー＆ペーストしてください",
            "",
        ])
        
        for chapter in chapters:
            # 秒をMM:SS形式に変換
            total_seconds = int(chapter.start_time_sec)
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            timestamp = f"{minutes:02d}:{seconds:02d}"
            
            lines.append(f"{timestamp} {chapter.title}")
        
        lines.append("")
    
    # ハッシュタグ候補
    lines.extend([
        "【ハッシュタグ候補】",
        "#ずんだもん #VOICEVOX #AI #ラジオ",
        "",
    ])
    
    # VOICEVOXクレジット表記（利用規約準拠）
    lines.extend([
        "【概要欄用テキスト】",
        "※ 以下をYouTubeの概要欄にコピー＆ペーストしてください",
        "",
        script.description,
        "",
        "-----------------------------------",
        "■使用音声",
        "VOICEVOX:ずんだもん",
        "VOICEVOX:四国めたん",
        "-----------------------------------",
        "",
        "=" * 50,
    ])
    
    output_path.write_text("\n".join(lines), encoding="utf-8")
