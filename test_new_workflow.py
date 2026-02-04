"""リファクタリング版ワークフローの動作検証スクリプト

3つの独立したフェーズ関数を順番に実行し、エラーなく完走することを確認する。
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

# WindowsコンソールでのUnicode出力を強制的にUTF-8にする
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from workflow import (
    execute_planning_phase,
    execute_scripting_phase,
    execute_production_phase,
    ProgressCallback,
    apply_overrides,
    UIOverrides,
    check_prerequisites
)
from core.models import load_config


def print_separator(title: str):
    """セクション区切りを表示"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


async def test_workflow():
    """3つのフェーズを順次実行してテスト"""
    
    # テスト設定
    THEME = "猫が液体である科学的根拠"
    MODE = "trivia"
    
    print_separator("リファクタリング版ワークフロー動作検証")
    print(f"テーマ: {THEME}")
    print(f"モード: {MODE}")
    print(f"開始時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # ログコールバック（標準出力に表示）
    def log_callback(msg: str):
        print(f"[LOG] {msg}")
    
    # 進捗コールバック
    def progress_callback(ratio: float, desc: str):
        percentage = int(ratio * 100)
        print(f"[PROGRESS] {percentage}% - {desc}")
    
    callbacks = ProgressCallback(log_callback, progress_callback)
    
    try:
        # ========== Phase 0: 設定読み込み・前提条件チェック ==========
        print_separator("Phase 0: 設定読み込み・前提条件チェック")
        
        config = load_config(PROJECT_ROOT)
        overrides = UIOverrides(
            research_mode=MODE, 
            enable_research=True,
            background_image="technology_radio_broadcast_s_6ca1924d-1442-4288-9185-c0b981bcc42f_2.png"
        )
        config = apply_overrides(config, overrides)
        
        # 背景画像・BGMパスを手動設定（テスト用）
        config.yaml.paths.background_image = "assets/backgrounds/technology_radio_broadcast_s_6ca1924d-1442-4288-9185-c0b981bcc42f_2.png"
        config.yaml.paths.bgm_file = "assets/bgm/【万能型】おしゃれなLo-Fi Hip Hop.mp3"
        
        # 前提条件チェック
        success, error = await check_prerequisites(config, log_callback)
        if not success:
            print(f"[ERROR] 前提条件チェック失敗: {error}")
            return
        print("[OK] 前提条件チェックOK")
        
        # 出力ディレクトリを準備
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_base = PROJECT_ROOT / config.yaml.paths.output_dir / f"test_{timestamp}"
        output_base.mkdir(parents=True, exist_ok=True)
        print(f"[OK] 出力ディレクトリ: {output_base}")
        
        # ========== Phase 1: 企画（検索計画作成） ==========
        print_separator("Phase 1: 企画（検索計画作成）")
        
        planning_result = await execute_planning_phase(
            theme=THEME,
            mode=MODE,
            config=config,
            callbacks=callbacks
        )
        
        print("\n【企画フェーズ結果】")
        print(f"切り口: {planning_result.angle}")
        print(f"検索クエリ数: {len(planning_result.queries)}")
        for i, query in enumerate(planning_result.queries, 1):
            print(f"  {i}. {query}")
        print(f"所要時間: {planning_result.duration_sec:.1f}秒")
        if planning_result.gemini_usage:
            print(f"Gemini使用量: {planning_result.gemini_usage.total_tokens} tokens")
        
        # ========== Phase 2: 台本作成（リサーチ → 台本生成） ==========
        print_separator("Phase 2: 台本作成（リサーチ → 台本生成）")
        
        scripting_result = await execute_scripting_phase(
            theme=THEME,
            mode=MODE,
            queries=planning_result.queries,
            config=config,
            output_dir=output_base,
            enable_research=True,
            callbacks=callbacks
        )
        
        print("\n【台本作成フェーズ結果】")
        print(f"タイトル: {scripting_result.script.title}")
        print(f"サムネイルテキスト: {scripting_result.script.thumbnail_title}")
        print(f"台本フレーズ数: {len(scripting_result.script.dialogue)}")
        print(f"台本冒頭3行:")
        for i, line in enumerate(scripting_result.script.dialogue[:3], 1):
            speaker = "ずんだもん" if line.speaker_id == 1 else "めたん"
            print(f"  {i}. [{speaker}] {line.text[:50]}...")
        
        if scripting_result.research_content:
            print(f"リサーチ文字数: {len(scripting_result.research_content)}文字")
        print(f"リサーチ所要時間: {scripting_result.research_duration_sec:.1f}秒")
        print(f"台本生成所要時間: {scripting_result.script_duration_sec:.1f}秒")
        
        if scripting_result.perplexity_usage:
            print(f"Perplexity使用量: {scripting_result.perplexity_usage.request_count} リクエスト")
        if scripting_result.gemini_usage:
            print(f"Gemini使用量: {scripting_result.gemini_usage.total_tokens} tokens")
        
        # ========== Phase 3: 制作（音声合成 → 動画生成） ==========
        print_separator("Phase 3: 制作（音声合成 → 動画生成）")
        
        production_result = await execute_production_phase(
            script=scripting_result.script,
            config=config,
            output_dir=output_base,
            project_root=PROJECT_ROOT,
            callbacks=callbacks
        )
        
        print("\n【制作フェーズ結果】")
        print(f"動画ファイル: {production_result.video_path}")
        print(f"音声ファイル: {production_result.audio_path}")
        print(f"字幕ファイル: {production_result.subtitle_path}")
        print(f"動画時間: {production_result.duration_sec:.1f}秒")
        print(f"ファイルサイズ: {production_result.file_size_mb:.1f}MB")
        print(f"チャプター数: {len(production_result.chapters)}")
        
        if production_result.chapters:
            print("チャプター一覧:")
            for chapter in production_result.chapters[:5]:  # 最初の5つのみ表示
                print(f"  {chapter.start_time_sec:.1f}秒 - {chapter.title}")
        
        print(f"音声合成所要時間: {production_result.audio_duration_sec:.1f}秒")
        print(f"動画生成所要時間: {production_result.render_duration_sec:.1f}秒")
        print(f"VOICEVOX使用量: {production_result.voicevox_usage.phrase_count}フレーズ")
        
        # ========== 完了 ==========
        print_separator("テスト完了")
        print("[SUCCESS] 全フェーズが正常に完了しました！")
        print(f"\n出力ディレクトリ: {output_base}")
        print(f"動画ファイル: {production_result.video_path}")
        
        # ファイルの存在確認
        if production_result.video_path.exists():
            print(f"[OK] 動画ファイル存在確認OK ({production_result.video_path.stat().st_size / 1024 / 1024:.1f}MB)")
        else:
            print("[WARN] 動画ファイルが見つかりません")
        
        if production_result.audio_path.exists():
            print(f"[OK] 音声ファイル存在確認OK")
        else:
            print("[WARN] 音声ファイルが見つかりません")
        
        print(f"\n終了時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
    except Exception as e:
        print_separator("エラー発生")
        print(f"[ERROR] テスト失敗: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    print("=" * 80)
    print("  リファクタリング版ワークフロー動作検証スクリプト")
    print("=" * 80)
    print("\nこのスクリプトは、workflow.pyの3つの独立したフェーズ関数を")
    print("順次実行し、エラーなく完走することを確認します。\n")
    
    asyncio.run(test_workflow())
