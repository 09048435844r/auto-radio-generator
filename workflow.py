"""自動ラジオ動画生成システム - 共通ワークフロー関数

このモジュールは、CLIとWeb UI両方から呼び出せる
動画生成ワークフローを提供します。
"""
import asyncio
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.models import (
    load_config, Script, AppConfig,
    TotalUsage, PerplexityUsage, GeminiUsage, VoicevoxUsage, CostBreakdown,
    ExecutionLogEntry, PromptRecord, ConfigSnapshot, CostLogEntry
)
from core.interfaces import ResearchMode, ChapterMarker
from services.script_generation import GeminiClient
from services.research import PerplexityResearcher
from services.audio_synthesis import VoicevoxClient
from services.video_rendering import FfmpegRenderer
from services.media_processing import ThumbnailGenerator
from services.cost_calculator import CostCalculator
from services.publishing import YouTubeClient, build_video_description
from services.publishing.text_sanitizer import validate_url, normalize_url
from core.models.research import ResearchSource
from services.execution_logger import ExecutionLogger

# アプリケーションバージョン
APP_VERSION = "v3.3.0"


ReferenceEntry = str | ResearchSource


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
    uploaded_video_url: Optional[str] = None  # YouTubeアップロードURL（成功時）


@dataclass
class PlanningPhaseResult:
    """企画フェーズの実行結果"""
    queries: list[str]
    angle: str
    gemini_usage: Optional[GeminiUsage] = None
    duration_sec: float = 0.0


@dataclass
class ScriptingPhaseResult:
    """台本作成フェーズの実行結果"""
    script: Script
    research_content: Optional[str] = None
    research_sources: Optional[list[ResearchSource]] = None
    perplexity_usage: Optional[PerplexityUsage] = None
    gemini_usage: Optional[GeminiUsage] = None
    research_duration_sec: float = 0.0
    script_duration_sec: float = 0.0


@dataclass
class ProductionPhaseResult:
    """制作フェーズの実行結果"""
    video_path: Path
    audio_path: Path
    subtitle_path: Path
    duration_sec: float
    file_size_mb: float
    chapters: list[ChapterMarker]
    voicevox_usage: VoicevoxUsage
    audio_duration_sec: float = 0.0
    render_duration_sec: float = 0.0


def _normalize_non_empty_strings(values: list[str]) -> list[str]:
    """空要素を除去しつつ順序を維持して重複排除する。"""
    seen = set()
    result: list[str] = []
    for value in values:
        text = (value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _to_json_safe(value: Any) -> Any:
    """Pydanticモデル等をJSONシリアライズ可能な形に再帰変換する。"""
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return _to_json_safe(value.model_dump())
    if isinstance(value, dict):
        return {k: _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_to_json_safe(item) for item in value]
    return value


def _format_chapter_lines(chapters: list[ChapterMarker]) -> list[str]:
    """チャプター情報を `MM:SS タイトル` 形式に整形する。"""
    chapter_lines: list[str] = []
    for chapter in chapters or []:
        total_seconds = int(chapter.start_time_sec)
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        timestamp_str = f"{minutes:02d}:{seconds:02d}"
        chapter_lines.append(f"{timestamp_str} {chapter.title}")
    return chapter_lines


def _extract_urls(text: str) -> list[str]:
    """テキスト中のURLを抽出する。"""
    if not text:
        return []
    return re.findall(r"https?://[^\s\)\]]+", text)


def _resolve_dynamic_tags(script: Script, fallback_description: str) -> list[str]:
    """台本ハッシュタグを優先し、未設定時は説明文から抽出する。"""
    if script.hashtags:
        return _normalize_non_empty_strings(script.hashtags)
    extracted = re.findall(r"#\S+", fallback_description or "")
    return _normalize_non_empty_strings(extracted)


def _resolve_references(
    script: Script,
    theme: str,
    fallback_description: str,
    research_sources: Optional[list[ResearchSource]] = None,
) -> list[ReferenceEntry]:
    """参考文献リストを解決し、可能ならタイトル付きソースを優先する。
    
    AI Editor方式: Geminiが選択したURLとResearchSourceを突き合わせて、
    選択されたURLのみをタイトル付きで表示する。
    """
    import logging
    logger = logging.getLogger(__name__)
    
    references: list[ReferenceEntry] = []

    # Geminiが選択したURLを取得（優先度最高）
    selected_urls = _normalize_non_empty_strings(list(script.references or []))
    
    if selected_urls and research_sources:
        # AI Editor方式: Geminiが選択したURLに対応するResearchSourceのみを抽出
        url_to_source = {}
        for source in research_sources:
            if source.url and source.url.strip():
                normalized_url = normalize_url(source.url.strip())
                if validate_url(normalized_url):
                    url_to_source[normalized_url] = source
        
        for url in selected_urls:
            normalized_url = normalize_url(url.strip())
            
            if not validate_url(normalized_url):
                logger.warning(f"Geminiから無効なURL: {url}")
                continue
                
            if normalized_url in url_to_source:
                # 選択されたURLに対応するResearchSourceを追加
                references.append(url_to_source[normalized_url])
            else:
                # 選択されたURLがResearchSourceにない場合は文字列として追加
                logger.info(f"Geminiが候補にないURLを選択: {url}")
                references.append(url)
    else:
        # 従来方式: 選択がない場合は全リサーチソースを使用
        for source in research_sources or []:
            url = (source.url or "").strip()
            if url and validate_url(url):
                references.append(source)

        # 台本に含まれるURL文字列を追加
        for url in _normalize_non_empty_strings(list(script.references or [])):
            if validate_url(url):
                references.append(url)

    # 生成概要文から抽出したURLを追加
    for url in _extract_urls(fallback_description or ""):
        if validate_url(url):
            references.append(url)

    # テーマ入力がURLなら追加
    stripped_theme = (theme or "").strip()
    if stripped_theme.startswith(("http://", "https://")) and validate_url(stripped_theme):
        references.append(stripped_theme)

    # URL基準で重複排除（ResearchSourceを優先保持）
    seen_urls: set[str] = set()
    deduped: list[ReferenceEntry] = []
    for ref in references:
        if isinstance(ref, ResearchSource):
            key = normalize_url((ref.url or "").strip())
        else:
            key = normalize_url((ref or "").strip())

        if not key or key in seen_urls:
            continue

        seen_urls.add(key)
        deduped.append(ref)

    return deduped


def _capture_config_snapshot(config: AppConfig, overrides: UIOverrides) -> ConfigSnapshot:
    """設定スナップショットをキャプチャ（再現性確保用）
    
    Args:
        config: アプリケーション設定
        overrides: UI上書き設定
    
    Returns:
        ConfigSnapshot: 設定スナップショット
    """
    from dataclasses import asdict
    
    return ConfigSnapshot(
        yaml_config=config.yaml.model_dump(),
        ui_overrides=asdict(overrides),
        env_vars={
            "VOICEVOX_BASE_URL": config.env.voicevox_base_url,
            "GEMINI_API_KEY": "***MASKED***",
            "PERPLEXITY_API_KEY": "***MASKED***"
        }
    )


def _build_speaker_diagnostics(script: Script) -> tuple[list[str], bool]:
    """話者分布と口調ヒントの診断ログを作成する。"""
    lines = list(script.dialogue)
    count_a = sum(1 for line in lines if line.speaker == "A")
    count_b = sum(1 for line in lines if line.speaker == "B")

    a_nanoda = sum(1 for line in lines if line.speaker == "A" and "なのだ" in line.text)
    b_nanoda = sum(1 for line in lines if line.speaker == "B" and "なのだ" in line.text)
    a_wayo = sum(
        1 for line in lines if line.speaker == "A" and ("わよ" in line.text or "かしら" in line.text)
    )
    b_wayo = sum(
        1 for line in lines if line.speaker == "B" and ("わよ" in line.text or "かしら" in line.text)
    )

    diagnostics = [
        "[DEBUG] 話者分布診断:",
        f"  - A行数: {count_a}, B行数: {count_b}",
        f"  - 「なのだ」検出: A={a_nanoda}, B={b_nanoda}",
        f"  - 「わよ/かしら」検出: A={a_wayo}, B={b_wayo}",
    ]

    suspected_swap = (b_nanoda > a_nanoda) and (a_wayo > b_wayo)
    return diagnostics, suspected_swap


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


async def execute_planning_phase(
    theme: str,
    mode: ResearchMode,
    config: AppConfig,
    instruction: Optional[str] = None,
    callbacks: Optional[ProgressCallback] = None
) -> PlanningPhaseResult:
    """企画フェーズ: AIプロデューサーが検索計画を作成
    
    Args:
        theme: 動画のテーマ
        mode: リサーチモード
        config: アプリケーション設定
        instruction: 追加指示（オプション）
        callbacks: 進捗コールバック
    
    Returns:
        PlanningPhaseResult: 検索クエリリストと切り口
    """
    cb = callbacks or ProgressCallback()
    start_time = time.time()
    
    cb.log(f"\n== Phase 1: 企画（検索計画作成） ==")
    cb.log(f"テーマ: {theme}")
    cb.log(f"モード: {mode}")
    cb.progress(0.10, "🤔 企画・検索計画を作成中...")
    
    try:
        script_generator = create_script_generator(config)
        plan = await script_generator.create_research_plan(theme, mode, instruction)
        
        cb.log(f"✓ 検索計画作成完了")
        cb.log(f"切り口: {plan.angle}")
        cb.log(f"\n検索クエリ:")
        for i, q in enumerate(plan.queries, 1):
            cb.log(f"  {i}. {q}")
        
        # Usage記録
        gemini_usage = script_generator.last_usage
        
        duration = time.time() - start_time
        cb.log(f"✓ 企画フェーズ完了 ({duration:.1f}秒)")
        
        return PlanningPhaseResult(
            queries=plan.queries,
            angle=plan.angle,
            gemini_usage=gemini_usage,
            duration_sec=duration
        )
    
    except Exception as e:
        cb.log(f"❌ 企画フェーズエラー: {e}")
        raise


async def execute_scripting_phase(
    theme: str,
    mode: ResearchMode,
    queries: list[str],
    config: AppConfig,
    output_dir: Path,
    enable_research: bool = True,
    excluded_topics: Optional[str] = None,
    avoid_topics: Optional[str] = None,
    callbacks: Optional[ProgressCallback] = None
) -> ScriptingPhaseResult:
    """台本作成フェーズ: リサーチ → 台本生成
    
    Args:
        theme: 動画のテーマ
        mode: リサーチモード
        queries: 検索クエリリスト（企画フェーズの出力）
        config: アプリケーション設定
        output_dir: 出力ディレクトリ（リサーチ結果保存用）
        enable_research: リサーチを実行するか
        excluded_topics: 除外すべき既出情報（オプション）
        avoid_topics: 避けてほしい話題（Negative Prompt、オプション）
        callbacks: 進捗コールバック
    
    Returns:
        ScriptingPhaseResult: 台本とリサーチ結果
    """
    cb = callbacks or ProgressCallback()
    research_start = time.time()
    research_data = None
    research_content = None
    perplexity_usage = None
    research_duration = 0.0
    
    # Step 1: リサーチ
    if enable_research and queries:
        cb.log(f"\n== Phase 2-1: リサーチ ==")
        cb.log(f"モード: {mode}")
        if excluded_topics:
            cb.log(f"除外トピック: {excluded_topics[:100]}..." if len(excluded_topics) > 100 else f"除外トピック: {excluded_topics}")
        cb.progress(0.30, "🔍 リサーチを実行中 (Perplexity)...")
        
        try:
            researcher = create_researcher(config)
            # 除外トピックをリサーチャーに渡す（今後の拡張用）
            research_data = await researcher.research_multi(queries, mode)
            
            cb.log(f"✓ リサーチ完了")
            cb.log(f"収集した情報: {len(research_data.content)}文字")
            
            research_content = research_data.content
            perplexity_usage = research_data.usage
            research_duration = time.time() - research_start
            
            # リサーチ結果を保存
            _save_research_results(research_data, output_dir, cb)
            
        except Exception as e:
            cb.log(f"⚠ リサーチエラー（スキップ）: {e}")
            import traceback
            cb.log(f"[DEBUG] {traceback.format_exc()}")
    else:
        cb.log(f"[INFO] リサーチスキップ")
    
    cb.progress(0.45, "✅ リサーチ完了")
    
    # Step 2: 台本生成
    cb.log(f"\n== Phase 2-2: 台本生成 ==")
    cb.log(f"テーマ: {theme}")
    cb.progress(0.50, "📝 台本を執筆中 (Gemini Pro)...")
    
    script_start = time.time()
    script_generator = create_script_generator(config)
    script = script_generator.generate(theme, research_data, avoid_topics=avoid_topics)

    diagnostics, suspected_swap = _build_speaker_diagnostics(script)
    for msg in diagnostics:
        cb.log(msg)
    if suspected_swap:
        cb.log("[yellow][WARN] 口調ヒント上、A/B話者の役割逆転の疑いがあります[/yellow]")
    
    gemini_usage = script_generator.last_usage
    script_duration = time.time() - script_start
    
    cb.log(f"✓ 台本生成完了: {len(script.dialogue)}フレーズ ({script_duration:.1f}秒)")
    cb.log(f"タイトル: {script.title}")
    cb.progress(0.65, "✅ 台本生成完了")
    
    # 台本を保存
    script_path = output_dir / "script.json"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script.model_dump_json(indent=2), encoding="utf-8")
    cb.log(f"✓ 台本保存: {script_path.name}")
    
    return ScriptingPhaseResult(
        script=script,
        research_content=research_content,
        research_sources=getattr(research_data, "sources", None),
        perplexity_usage=perplexity_usage,
        gemini_usage=gemini_usage,
        research_duration_sec=research_duration,
        script_duration_sec=script_duration
    )


async def execute_production_phase(
    script: Script,
    config: AppConfig,
    output_dir: Path,
    project_root: Path,
    speed_scale: Optional[float] = None,
    callbacks: Optional[ProgressCallback] = None
) -> ProductionPhaseResult:
    """制作フェーズ: 音声合成 → 動画生成
    
    Args:
        script: 台本データ（台本作成フェーズの出力）
        config: アプリケーション設定
        output_dir: 出力ディレクトリ
        project_root: プロジェクトルート
        speed_scale: 音声スピード倍率（オプション）
        callbacks: 進捗コールバック
    
    Returns:
        ProductionPhaseResult: 動画ファイルパスと各種メタデータ
    """
    cb = callbacks or ProgressCallback()
    
    # ========== Step 1: 音声合成 ==========
    cb.log(f"\n== Phase 3-1: 音声合成 ==")
    cb.log(f"フレーズ数: {len(script.dialogue)}")
    cb.progress(0.70, "🗣️ 音声を合成中 (VOICEVOX)...")
    
    audio_start = time.time()
    audio_output_dir = output_dir / "audio"
    
    voicevox = VoicevoxClient(config)
    synthesis_result = await voicevox.synthesize(
        script,
        audio_output_dir,
        speed_scale_override=speed_scale
    )
    
    voicevox_usage = VoicevoxUsage(
        phrase_count=len(script.dialogue),
        total_duration_sec=synthesis_result.total_duration_sec
    )
    audio_duration = time.time() - audio_start
    
    cb.log(f"✓ 音声合成完了: {synthesis_result.total_duration_sec:.1f}秒 ({audio_duration:.1f}秒)")
    cb.progress(0.85, "✅ 音声合成完了")
    
    # ========== Step 2: 動画生成 ==========
    cb.log(f"\n== Phase 3-2: 動画生成 ==")
    cb.log(f"BGM音量: {config.yaml.video_renderer.bgm_volume}")
    cb.log(f"フェードイン: {config.yaml.video_renderer.bgm_fade_in_sec}秒")
    cb.log(f"フェードアウト: {config.yaml.video_renderer.bgm_fade_out_sec}秒")
    cb.log(f"スペクトラム: {'ON' if config.yaml.video_renderer.enable_spectrum else 'OFF'}")
    cb.progress(0.90, "🎬 動画をレンダリング中 (FFmpeg)...")
    
    render_start = time.time()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_output_path = output_dir / "videos" / f"radio_{timestamp}.mp4"
    
    background_image = project_root / config.yaml.paths.background_image
    bgm_file = project_root / config.yaml.paths.bgm_file
    
    ffmpeg = FfmpegRenderer(config)
    render_result = await ffmpeg.render(
        synthesis_result=synthesis_result,
        background_image=background_image,
        bgm_file=bgm_file,
        output_path=video_output_path,
        subtitle_path=synthesis_result.subtitle_path
    )
    
    render_duration = time.time() - render_start
    
    cb.log(f"✓ 動画生成完了: {render_result.file_size_mb:.1f}MB ({render_duration:.1f}秒)")
    cb.progress(0.95, "✅ 動画生成完了")
    
    # ========== Step 3: サムネイル生成 ==========
    cb.log(f"\n== Phase 3-3: サムネイル生成 ==")
    thumbnail_generator = ThumbnailGenerator()
    thumbnail_path = output_dir / "thumbnail.png"
    thumbnail_generator.generate(
        title=script.title,
        thumbnail_title=script.thumbnail_title,
        background_path=background_image,
        output_path=thumbnail_path
    )
    cb.log(f"✓ サムネイル画像生成: {thumbnail_path.name}")
    
    return ProductionPhaseResult(
        video_path=render_result.video_path,
        audio_path=synthesis_result.audio_path,
        subtitle_path=synthesis_result.subtitle_path,
        duration_sec=render_result.duration_sec,
        file_size_mb=render_result.file_size_mb,
        chapters=synthesis_result.chapters,
        voicevox_usage=voicevox_usage,
        audio_duration_sec=audio_duration,
        render_duration_sec=render_duration
    )


def _save_research_results(
    research_data,
    output_dir: Path,
    callbacks: ProgressCallback
) -> None:
    """リサーチ結果をファイルに保存
    
    Args:
        research_data: リサーチ結果
        output_dir: 出力ディレクトリ
        callbacks: 進捗コールバック
    """
    try:
        from dataclasses import asdict
        import json
        
        callbacks.log(f"[DEBUG] research.json保存処理開始")
        
        research_path = output_dir / "research.json"
        research_path.parent.mkdir(parents=True, exist_ok=True)
        
        research_dict = _to_json_safe(asdict(research_data))
        json_str = json.dumps(research_dict, ensure_ascii=False, indent=2)
        research_path.write_text(json_str, encoding="utf-8")
        
        callbacks.log(f"✓ リサーチ結果保存: {research_path}")
        
        # Markdownレポートも保存
        report_path = output_dir / "research_report.md"
        report_content = f"""# リサーチレポート

**テーマ**: {research_data.topic}
**モード**: {research_data.mode}
**生成日時**: {datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}

---

{research_data.content}
"""
        report_path.write_text(report_content, encoding="utf-8")
        callbacks.log(f"✓ リサーチレポート保存: {report_path}")
        
        # Perplexityの生データを全文保存
        full_report_path = output_dir / "full_research_report.md"
        full_report_path.write_text(research_data.content, encoding="utf-8")
        callbacks.log(f"✓ Perplexity全文レポート保存: {full_report_path}")
        
    except Exception as save_error:
        callbacks.log(f"⚠ リサーチ結果保存エラー: {save_error}")
        import traceback
        callbacks.log(f"[DEBUG] Traceback: {traceback.format_exc()}")


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
        
        # ========== Phase 1: リサーチ (5-20%) - AIプロデューサーモード ==========
        research_data = None
        if overrides.enable_research and overrides.research_mode:
            progress(0.05, f"リサーチ中 ({overrides.research_mode})...")
            log(f"\n== リサーチ (AIプロデューサーモード) ==")
            log(f"テーマ: {theme}")
            log(f"モード: {overrides.research_mode}")
            
            research_start = time.time()
            try:
                # Step 0: AIプロデューサーが検索計画を作成
                progress(0.05, "Step 0: AIが検索計画を作成中...")
                log(f"\n== Step 0: 検索計画作成 ==")
                
                script_generator = create_script_generator(config)
                plan = await script_generator.create_research_plan(theme, overrides.research_mode, instruction=None)
                
                log(f"✓ 検索計画作成完了")
                log(f"切り口: {plan.angle}")
                log(f"\n検索クエリ:")
                for i, q in enumerate(plan.queries, 1):
                    log(f"  {i}. {q}")
                
                # Step 1: 複数クエリで並列リサーチ
                progress(0.10, "Step 1: 並列リサーチ中...")
                log(f"\n== Step 1: 並列リサーチ ({overrides.research_mode}) ==")
                
                researcher = create_researcher(config)
                research_data = await researcher.research_multi(plan.queries, overrides.research_mode)
                
                log(f"\n✓ 並列リサーチ完了")
                log(f"収集した情報: {len(research_data.content)}文字")
                
                # Usage記録
                if research_data and research_data.usage:
                    total_usage.perplexity = research_data.usage
                
                total_usage.research_duration_sec = time.time() - research_start
                log(f"✓ リサーチ完了: {len(research_data.content)}文字 ({total_usage.research_duration_sec:.1f}秒)")
                
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
                
                research_dict = _to_json_safe(asdict(research_data))
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

        diagnostics, suspected_swap = _build_speaker_diagnostics(script)
        for msg in diagnostics:
            log(msg)
        if suspected_swap:
            log("[yellow][WARN] 口調ヒント上、A/B話者の役割逆転の疑いがあります[/yellow]")
        
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
        generated_metadata = _generate_youtube_metadata(
            script=script,
            chapters=synthesis_result.chapters,
            output_path=metadata_path,
            theme=theme
        )
        log(f"✓ YouTubeメタデータ生成: {metadata_path.name}")
        
        # サムネイル画像を生成（AI生成のthumbnail_titleを使用）
        thumbnail_generator = ThumbnailGenerator()
        thumbnail_path = output_base / "thumbnail.png"
        thumbnail_generator.generate(
            title=generated_metadata.get("title", script.title),
            thumbnail_title=generated_metadata.get("thumbnail_title", ""),
            background_path=background_image,
            output_path=thumbnail_path
        )
        log(f"✓ サムネイル画像生成: {thumbnail_path.name}")
        
        # ログファイルを完了
        if log_writer:
            log_writer.finalize()
            log(f"✓ 処理ログ保存: {log_writer.log_path.name}")
        
        # メタデータの内容を読み込んでUIへ渡す
        metadata_content = metadata_path.read_text(encoding="utf-8")
        
        # 日付入りタイトルを生成（AI生成タイトル + 日付）
        creation_date = datetime.now().strftime("%Y.%m.%d")
        ai_title = generated_metadata.get("title", script.title)
        formatted_title = f"{ai_title} ({creation_date}制作)"
        
        publishing_config = getattr(config.yaml, "publishing", None)
        chapter_lines = _format_chapter_lines(synthesis_result.chapters)

        script_description = (
            generated_metadata.get("description")
            or script.description
            or ""
        )
        dynamic_tags = _resolve_dynamic_tags(script, fallback_description=script_description)
        references = _resolve_references(
            script,
            theme=theme,
            fallback_description=script_description,
            research_sources=getattr(research_data, "sources", None),
        )

        configured_tags = getattr(publishing_config, "default_tags", []) if publishing_config else []
        if not isinstance(configured_tags, list):
            configured_tags = []
        fixed_tags = _normalize_non_empty_strings([str(tag) for tag in configured_tags])

        configured_footer = (
            getattr(publishing_config, "footer_text", "") if publishing_config else ""
        )

        formatted_description = build_video_description(
            script_description=script_description,
            chapters=chapter_lines,
            references=references,
            dynamic_tags=dynamic_tags,
            fixed_tags=fixed_tags,
            footer_text=(configured_footer or "").strip(),
        )
        
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
            duration_sec=total_usage.total_duration_sec,
            file_size_mb=render_result.file_size_mb,
            usage=total_usage,
            cost=cost,
            cost_report=cost_report,
            metadata_content=metadata_path.read_text(encoding="utf-8") if metadata_path.exists() else "",
            formatted_title=formatted_title,
            formatted_description=generated_metadata.get("description", script.description)
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
    progress_callback: Optional[Callable[[float, str], None]] = None,
    use_mock: bool = False,
    avoid_topics: Optional[str] = None,
    upload_override: Optional[bool] = None,
    footer_text_override: Optional[str] = None,
) -> WorkflowResult:
    """同期版ワークフロー実行（Gradioから呼び出し用）
    
    3つの独立したフェーズ関数を順次呼び出すシンプルなラッパー。
    これにより、自動モードが「手動工程の連続実行」と等価であることを保証します。
    
    Args:
        theme: 動画のテーマ
        overrides: UIからのパラメータオーバーライド
        log_callback: ログ出力用コールバック関数
        progress_callback: 進捗コールバック (ratio, description)
        use_mock: Mockモードを使用するか（開発・テスト用）
        avoid_topics: 避けてほしい話題（Negative Prompt、オプション）
        upload_override: YouTubeアップロード実行のUI優先フラグ
        footer_text_override: 概要欄フッター文（UI入力優先）
    
    Returns:
        WorkflowResult: 実行結果（Usage/Cost情報含む）
    """
    async def _run_phases():
        workflow_start = time.time()
        overrides_obj = overrides or UIOverrides()
        callbacks = ProgressCallback(log_callback, progress_callback)
        log_writer: Optional[LogFileWriter] = None
        original_mock_mode = None  # 元のmock_mode設定を保存
        
        try:
            # ========== Phase 0: 設定読み込み・前提条件チェック ==========
            callbacks.progress(0.0, "🚀 生成プロセスを開始します...")
            callbacks.log("設定を読み込み中...")
            
            config = load_config(PROJECT_ROOT)
            
            # Mockモードのオーバーライド
            if use_mock:
                callbacks.log("🔴 Mockモードが有効化されました")
                # 元の設定を保存
                if hasattr(config.yaml, 'dev'):
                    original_mock_mode = config.yaml.dev.mock_mode
                else:
                    # devセクションが存在しない場合は作成
                    from types import SimpleNamespace
                    config.yaml.dev = SimpleNamespace(mock_mode=False, mock_data_path="tests/mock_data")
                    original_mock_mode = False
                # mock_modeをTrueにオーバーライド
                config.yaml.dev.mock_mode = True
            
            config = apply_overrides(config, overrides_obj)
            
            # 素材パスのオーバーライド
            if overrides_obj.background_image:
                config.yaml.paths.background_image = f"assets/backgrounds/{overrides_obj.background_image}"
            if overrides_obj.bgm_file:
                config.yaml.paths.bgm_file = f"assets/bgm/{overrides_obj.bgm_file}"
            
            # 前提条件チェック
            callbacks.progress(0.02, "前提条件を確認中...")
            success, error = await check_prerequisites(config, log_callback)
            if not success:
                return WorkflowResult(success=False, error_message=error)
            callbacks.progress(0.05, "✅ 前提条件OK")
            
            # 出力ディレクトリを準備
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_base = PROJECT_ROOT / config.yaml.paths.output_dir / timestamp
            output_base.mkdir(parents=True, exist_ok=True)
            
            # ログファイルライターを初期化
            log_writer = LogFileWriter(output_base)
            callbacks.log(f"出力ディレクトリ: {output_base}")
            
            # Usage集約用
            total_usage = TotalUsage()
            
            # 実行ログ用: API クライアントインスタンスを保持
            api_clients = {
                'script_generator': None,
                'researcher': None
            }
            
            # ========== Phase 1: 企画（検索計画作成） ==========
            planning_result = None
            queries = []
            
            # Mockモード判定
            if config.yaml.dev.mock_mode:
                callbacks.log("[yellow]⚠ MOCK MODE: Skipping planning phase[/yellow]")
                # ダミーの検索クエリを設定
                queries = [
                    "Mock Query 1: テーマに関する一般的な調査",
                    "Mock Query 2: トレンドと背景",
                    "Mock Query 3: 面白い雑学"
                ]
                angle = "Mock Mode: 既存のデータを使用して高速に動画生成をテストする"
                callbacks.log(f"切り口: {angle}")
            elif overrides_obj.enable_research and overrides_obj.research_mode:
                planning_result = await execute_planning_phase(
                    theme=theme,
                    mode=overrides_obj.research_mode,
                    config=config,
                    callbacks=callbacks
                )
                queries = planning_result.queries
                if planning_result.gemini_usage:
                    total_usage.gemini = planning_result.gemini_usage
            else:
                callbacks.log("[INFO] 企画フェーズスキップ（リサーチ無効）")
            
            # ========== Phase 2: 台本作成（リサーチ → 台本生成） ==========
            scripting_result = await execute_scripting_phase(
                theme=theme,
                mode=overrides_obj.research_mode or "trivia",
                queries=queries,
                config=config,
                output_dir=output_base,
                enable_research=overrides_obj.enable_research,
                avoid_topics=avoid_topics,
                callbacks=callbacks
            )
            
            # Usage記録
            if scripting_result.perplexity_usage:
                total_usage.perplexity = scripting_result.perplexity_usage
            if scripting_result.gemini_usage:
                total_usage.gemini = scripting_result.gemini_usage
            total_usage.research_duration_sec = scripting_result.research_duration_sec
            total_usage.script_duration_sec = scripting_result.script_duration_sec
            
            # ========== Phase 3: 制作（音声合成 → 動画生成） ==========
            production_result = await execute_production_phase(
                script=scripting_result.script,
                config=config,
                output_dir=output_base,
                project_root=PROJECT_ROOT,
                speed_scale=overrides_obj.speed_scale,
                callbacks=callbacks
            )
            
            # Usage記録
            total_usage.voicevox = production_result.voicevox_usage
            total_usage.audio_duration_sec = production_result.audio_duration_sec
            total_usage.render_duration_sec = production_result.render_duration_sec
            
            # ========== Phase 4: 後処理（メタデータ生成） ==========
            callbacks.progress(0.97, "📦 後処理中...")
            
            # YouTube用メタデータを生成
            metadata_path = output_base / "metadata.txt"
            generated_metadata = _generate_youtube_metadata(
                script=scripting_result.script,
                chapters=production_result.chapters,
                output_path=metadata_path,
                theme=theme
            )
            callbacks.log(f"✓ YouTubeメタデータ生成: {metadata_path.name}")
            
            # サムネイル画像を生成（AI生成のthumbnail_titleを使用）
            background_image = PROJECT_ROOT / config.yaml.paths.background_image
            thumbnail_generator = ThumbnailGenerator()
            thumbnail_path = output_base / "thumbnail.png"
            thumbnail_generator.generate(
                title=generated_metadata.get("title", scripting_result.script.title),
                thumbnail_title=generated_metadata.get("thumbnail_title", ""),
                background_path=background_image,
                output_path=thumbnail_path
            )
            callbacks.log(f"✓ サムネイル画像生成: {thumbnail_path.name}")
            
            # ログファイルを完了
            if log_writer:
                log_writer.finalize()
                callbacks.log(f"✓ 処理ログ保存: {log_writer.log_path.name}")
            
            # メタデータの内容を読み込んでUIへ渡す
            metadata_content = metadata_path.read_text(encoding="utf-8")
            
            # 日付入りタイトルを生成（AI生成タイトル + 日付）
            creation_date = datetime.now().strftime("%Y.%m.%d")
            ai_title = generated_metadata.get("title", scripting_result.script.title)
            formatted_title = f"{ai_title} ({creation_date}制作)"

            publishing_config = getattr(config.yaml, "publishing", None)
            chapter_lines = _format_chapter_lines(production_result.chapters)

            script_description = (
                generated_metadata.get("description")
                or scripting_result.script.description
                or ""
            )

            dynamic_tags = _resolve_dynamic_tags(
                scripting_result.script,
                fallback_description=script_description,
            )
            references = _resolve_references(
                scripting_result.script,
                theme=theme,
                fallback_description=script_description,
                research_sources=scripting_result.research_sources,
            )

            configured_tags = getattr(publishing_config, "default_tags", []) if publishing_config else []
            if not isinstance(configured_tags, list):
                configured_tags = []
            fixed_tags = _normalize_non_empty_strings([str(tag) for tag in configured_tags])

            configured_footer = (
                getattr(publishing_config, "footer_text", "") if publishing_config else ""
            )
            resolved_footer = (
                (footer_text_override or "").strip()
                if isinstance(footer_text_override, str) and footer_text_override.strip()
                else (configured_footer or "").strip()
            )

            formatted_description = build_video_description(
                script_description=script_description,
                chapters=chapter_lines,
                references=references,
                dynamic_tags=dynamic_tags,
                fixed_tags=fixed_tags,
                footer_text=resolved_footer,
            )
            
            # 総所要時間
            total_usage.total_duration_sec = time.time() - workflow_start
            
            # コスト計算
            cost_calculator = CostCalculator()
            cost = cost_calculator.calculate(total_usage)
            cost_report = cost_calculator.format_cost_report(total_usage, cost)

            # YouTubeアップロード（失敗しても動画生成結果は成功扱い）
            uploaded_video_url: Optional[str] = None
            should_upload = (
                upload_override
                if upload_override is not None
                else bool(publishing_config and getattr(publishing_config, "enable_upload", False))
            )

            # Safety guard: never upload during mock executions.
            if use_mock and should_upload:
                should_upload = False
                callbacks.log("[INFO] MockモードのためYouTubeアップロードを強制的に無効化しました")

            if should_upload:
                callbacks.log("[INFO] YouTubeアップロードを開始します...")
                try:
                    youtube_client = YouTubeClient(config)
                    uploaded_video_url = youtube_client.upload_video(
                        file_path=production_result.video_path,
                        title=formatted_title,
                        description=formatted_description,
                        thumbnail_path=thumbnail_path,
                    )
                    callbacks.log(f"✓ YouTubeアップロード完了: {uploaded_video_url}")

                    # 設定されている場合は再生リストへ追加（失敗しても非致命）
                    playlist_id = getattr(publishing_config, "playlist_id", None)
                    if isinstance(playlist_id, str):
                        playlist_id = playlist_id.strip()

                    if playlist_id:
                        callbacks.log(f"[INFO] 再生リスト追加設定: {playlist_id}")
                        try:
                            parsed_url = urlparse(uploaded_video_url)
                            video_id = parse_qs(parsed_url.query).get("v", [None])[0]
                            if video_id:
                                youtube_client.add_video_to_playlist(
                                    video_id=video_id,
                                    playlist_id=playlist_id,
                                )
                                callbacks.log(f"✓ 再生リストへ追加完了: {playlist_id}")
                            else:
                                callbacks.log(
                                    "⚠ 再生リスト追加をスキップ: 動画IDの抽出に失敗しました"
                                )
                        except Exception as playlist_error:
                            callbacks.log(
                                f"⚠ 再生リストへの追加に失敗しました（動画生成は成功）: {playlist_error}"
                            )
                    else:
                        callbacks.log("[INFO] 再生リスト追加設定: 未設定（playlist_id が空のためスキップ）")
                except Exception as upload_error:
                    callbacks.log(
                        f"⚠ YouTubeアップロードに失敗しました（動画生成は成功）: {upload_error}"
                    )
            else:
                callbacks.log("[INFO] YouTubeアップロード設定: 無効（UI設定優先）")
            
            # ========== 実行ログ・コスト履歴の記録 ==========
            try:
                from uuid import uuid4
                execution_id = str(uuid4())
                
                # プロンプト記録を収集（実際に使用されたインスタンスから）
                all_prompt_records = []
                
                # Note: Mock モードではプロンプト記録が空の場合がある
                # 実際のAPI呼び出しがあった場合のみ記録される
                
                # 設定スナップショットをキャプチャ
                config_snapshot = _capture_config_snapshot(config, overrides_obj)
                
                # 生成ファイルパスを記録
                from pathlib import Path as PathLib
                generated_files = {
                    "script": str(output_base / "script.json"),
                    "video": str(production_result.video_path),
                    "audio": str(production_result.audio_path),
                    "subtitle": str(production_result.subtitle_path),
                    "thumbnail": str(thumbnail_path),
                    "metadata": str(metadata_path)
                }
                
                # ExecutionLogEntryを作成
                execution_log = ExecutionLogEntry(
                    execution_id=execution_id,
                    app_version=APP_VERSION,
                    timestamp=datetime.now().isoformat(),
                    output_directory=str(output_base),
                    theme=theme,
                    config_snapshot=config_snapshot,
                    prompts=[PromptRecord(**rec) for rec in all_prompt_records],
                    generated_files=generated_files,
                    success=True,
                    error_message=None,
                    total_duration_sec=total_usage.total_duration_sec
                )
                
                # CostLogEntryを作成
                cost_log = CostLogEntry(
                    execution_id=execution_id,
                    timestamp=datetime.now().isoformat(),
                    output_directory=str(output_base),
                    perplexity_requests=total_usage.perplexity.request_count,
                    perplexity_model_name=config.yaml.researcher.model,
                    gemini_input_tokens=total_usage.gemini.input_tokens,
                    gemini_output_tokens=total_usage.gemini.output_tokens,
                    gemini_model_name=total_usage.gemini.model_name,
                    voicevox_phrases=total_usage.voicevox.phrase_count,
                    voicevox_duration_sec=total_usage.voicevox.total_duration_sec,
                    perplexity_usd=cost.perplexity_usd,
                    gemini_input_usd=cost.gemini_input_usd,
                    gemini_output_usd=cost.gemini_output_usd,
                    total_usd=cost.total_usd,
                    total_jpy=cost.total_jpy,
                    is_free_tier=cost.is_free_tier,
                    research_duration_sec=total_usage.research_duration_sec,
                    script_duration_sec=total_usage.script_duration_sec,
                    audio_duration_sec=total_usage.audio_duration_sec,
                    render_duration_sec=total_usage.render_duration_sec,
                    total_duration_sec=total_usage.total_duration_sec
                )
                
                # ログを書き込み
                logger = ExecutionLogger(PROJECT_ROOT / "logs")
                logger.append_execution_log(execution_log)
                logger.append_cost_log(cost_log)
                
                callbacks.log(f"✓ 実行ログ記録完了: execution_id={execution_id}")
            
            except Exception as log_error:
                import traceback
                callbacks.log(f"⚠ 実行ログ記録エラー（動画生成は成功）: {log_error}")
                callbacks.log(f"[DEBUG] Traceback: {traceback.format_exc()}")
            
            callbacks.log(f"\n== 完了 ==")
            callbacks.log(f"動画: {production_result.video_path}")
            callbacks.log(f"総所要時間: {total_usage.total_duration_sec:.1f}秒")
            callbacks.progress(1.0, "✨ すべて完了しました！")
            
            return WorkflowResult(
                success=True,
                video_path=production_result.video_path,
                script=scripting_result.script,
                audio_path=production_result.audio_path,
                subtitle_path=production_result.subtitle_path,
                duration_sec=production_result.duration_sec,
                file_size_mb=production_result.file_size_mb,
                usage=total_usage,
                cost=cost,
                cost_report=cost_report,
                metadata_content=metadata_content,
                formatted_title=formatted_title,
                formatted_description=formatted_description,
                uploaded_video_url=uploaded_video_url,
            )
            
        except Exception as e:
            error_msg = f"エラーが発生しました: {str(e)}"
            callbacks.log(f"\n❌ {error_msg}")
            
            # エラー時もログファイルを完了
            if log_writer:
                log_writer.finalize()
            
            # エラー時も実行ログを記録（失敗として）
            try:
                from uuid import uuid4
                execution_id = str(uuid4())
                
                config_snapshot = _capture_config_snapshot(config, overrides_obj)
                
                execution_log = ExecutionLogEntry(
                    execution_id=execution_id,
                    app_version=APP_VERSION,
                    timestamp=datetime.now().isoformat(),
                    output_directory=str(output_base) if 'output_base' in locals() else "",
                    theme=theme,
                    config_snapshot=config_snapshot,
                    prompts=[],
                    generated_files={},
                    success=False,
                    error_message=error_msg,
                    total_duration_sec=time.time() - workflow_start
                )
                
                logger = ExecutionLogger(PROJECT_ROOT / "logs")
                logger.append_execution_log(execution_log)
                
                callbacks.log(f"✓ エラーログ記録完了: execution_id={execution_id}")
            
            except Exception as log_error:
                callbacks.log(f"⚠ エラーログ記録失敗: {log_error}")
            
            return WorkflowResult(success=False, error_message=error_msg)
        
        finally:
            # Mockモード設定を元に戻す
            if use_mock and original_mock_mode is not None:
                config.yaml.dev.mock_mode = original_mock_mode
                callbacks.log("🔴 Mockモード設定を元に戻しました")
    
    return asyncio.run(_run_phases())


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
    output_path: Path,
    theme: str = ""
) -> dict:
    """YouTube投稿用のメタデータファイルを生成（packagingプロンプト使用）
    
    Args:
        script: 台本データ
        chapters: チャプターマーカーリスト
        output_path: 出力パス
        theme: 元のテーマ（script.titleが空の場合に使用）
        
    Returns:
        生成されたメタデータ辞書 {"title": str, "thumbnail_title": str, "description": str}
    """
    from services.script_generation.gemini_client import GeminiClient
    from core.settings_manager import SettingsManager
    from core.models.config import load_config
    
    # 設定をロード
    config = load_config()
    
    # Geminiクライアントを初期化（configを渡す）
    gemini_client = GeminiClient(config)
    settings = SettingsManager().load()
    
    # 台本の要約を生成
    script_summary = ""
    if script.dialogue:
        # ダイアログから主要な内容を要約
        dialogue_texts = [d.text for d in script.dialogue[:10]]  # 最初の10セリフで要約
        script_summary = " ".join(dialogue_texts)[:200] + "..." if len(" ".join(dialogue_texts)) > 200 else " ".join(dialogue_texts)
    
    # packagingプロンプトでメタデータを生成
    import json
    metadata = {}
    try:
        # script.titleが空の場合は元のthemeを使用
        effective_theme = script.title or theme or "テーマ不明"
        
        print(f"[DEBUG] メタデータ生成開始")
        print(f"[DEBUG] テーマ: {effective_theme}")
        print(f"[DEBUG] 台本要約: {script_summary[:100]}...")
        
        metadata_result = gemini_client.generate_packaging_prompt(
            theme=effective_theme,
            script_summary=script_summary
        )
        
        print(f"[DEBUG] Geminiレスポンス受信: {len(metadata_result)} chars")
        print(f"[DEBUG] レスポンス内容: {metadata_result[:200]}...")
        
        if metadata_result:
            # JSONモードでは、レスポンスは常に正しいJSON形式
            print(f"[DEBUG] JSONレスポンス: {metadata_result[:200]}...")
            metadata = json.loads(metadata_result.strip())
            
            # 概要欄は後工程のmetadata_builderで構造化するため、ここではAI生成本文のみ保持
            metadata["description"] = (metadata.get("description", "") or "").strip()
            
            lines = [
                "=" * 50,
                "YouTube 投稿用メタデータ (AI生成)",
                "=" * 50,
                "",
                "【タイトル】",
                metadata.get("title", script.title or ""),
                "",
                "【サムネイル文字】",
                metadata.get("thumbnail_title", ""),
                "",
                "【説明文】",
                metadata.get("description", ""),
                "",
            ]
            
            # ハッシュタグ候補（説明文から抽出）
            description = metadata.get("description", "")
            hashtags = []
            if "#" in description:
                # 説明文からハッシュタグを抽出
                import re
                hashtags = re.findall(r"#\w+", description)
            
            if not hashtags:
                hashtags = ["#ずんだもん", "#VOICEVOX", "#AI", "#ラジオ"]
            
            lines.extend([
                "【ハッシュタグ候補】",
                " ".join(hashtags),
                "",
            ])
            
        else:
            # フォールバック：従来方式
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
            
    except Exception as e:
        # エラー時はフォールバックし、詳細をログ出力
        import traceback
        error_detail = traceback.format_exc()
        print(f"[ERROR] メタデータ生成エラー: {str(e)}")
        print(f"[ERROR] Traceback:\n{error_detail}")
        
        # フォールバック: 台本のタイトル・概要をmetadataに格納
        metadata = {
            "title": script.title or theme or "無題",
            "thumbnail_title": script.title or theme or "",
            "description": script.description or "",
        }
        
        lines = [
            "=" * 50,
            "YouTube 投稿用メタデータ",
            "=" * 50,
            "",
            "【タイトル】",
            metadata["title"],
            "",
            "【説明文】",
            metadata["description"],
            "",
            f"※ メタデータ生成エラー: {str(e)}",
            "",
        ]
    
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
    
    # video_metadata.jsonとして保存
    metadata_json_path = output_path.parent / "video_metadata.json"
    metadata_json_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    
    return metadata
