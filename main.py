"""自動ラジオ動画生成システム - メインエントリーポイント

パイプライン分離アーキテクチャ対応 (Step 4 v2 / 2026-05-10):
- --phase research: リサーチフェーズのみ実行（Perplexity ベンチマーク用途）
- --phase render: 動画生成フェーズのみ実行
- --phase external: 外部台本モード（推奨 / Mac 側 radio_director の VerifiedScript JSON）

Step 4 v2 で削除:
- --phase all / --phase script: Gemini 自動台本生成経路は廃止
- --provider 引数: Gemini 経路の指定パラメータは不要に
- --research-brief 引数: --phase script 用だったため不要
"""
import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.models import load_config
from core.models.script import RadioScriptArtifact
from core.session_manager import SessionManager
from core.interfaces import ResearchMode
from services.pipeline import (
    execute_research_phase,
    execute_production_phase,
)
from workflow import ProgressCallback

console = Console()


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="自動ラジオ動画生成システム - パイプライン分離対応",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 外部台本モード（推奨経路 / Mac 側 radio_director の VerifiedScript JSON）
  python main.py --phase external --verified-script output/imports/run_001/verified_script.json

  # リサーチフェーズのみ実行（Perplexity ベンチマーク）
  python main.py --phase research --theme "持続血糖測定器CGMについて" --mode lecture

  # 動画生成フェーズのみ実行（既存セッション使用）
  python main.py --phase render --session 20260404_065500
"""
    )

    # Phase selection (external が推奨経路)
    parser.add_argument(
        "--phase",
        choices=["research", "render", "external"],
        default="external",
        help=(
            "実行するフェーズ "
            "(external: 外部台本モード [推奨], research: Perplexity リサーチのみ, "
            "render: 動画生成のみ)"
        )
    )

    # Session management
    parser.add_argument(
        "--session",
        type=str,
        help="既存セッションID（指定した場合は続きから実行）"
    )

    parser.add_argument(
        "--script",
        type=str,
        help="RadioScriptArtifactファイルのパス（--phase render時に使用）"
    )

    # Step 3: VerifiedScript path (for --phase external)
    parser.add_argument(
        "--verified-script",
        type=str,
        help="VerifiedScript JSON のパス（--phase external 時に必須）"
    )

    # Theme (for research execution)
    parser.add_argument(
        "--theme",
        type=str,
        help="動画のテーマ（--phase research 時に必須）"
    )

    # Research mode
    parser.add_argument(
        "--mode",
        choices=["debate", "voices", "trivia", "lecture", "weekly_digest"],
        default="trivia",
        help="リサーチモード（デフォルト: trivia）"
    )

    return parser.parse_args()


async def main():
    """メイン処理 - パイプライン分離対応"""
    args = parse_args()

    console.print(Panel.fit(
        "[bold cyan]🎙️ 自動ラジオ動画生成システム[/bold cyan]\n" +
        f"[dim]Phase: {args.phase}[/dim]",
        border_style="cyan"
    ))

    # Load config
    app_config = load_config(PROJECT_ROOT)

    # Initialize SessionManager
    session_manager = SessionManager(
        project_root=PROJECT_ROOT,
        session_id=args.session
    )

    console.print(f"\n[bold]Session ID:[/bold] {session_manager.session_id}")
    console.print(f"[bold]Session Dir:[/bold] {session_manager.session_dir}")

    # Progress callback for console output
    def log_callback(msg: str):
        console.print(msg)

    def progress_callback(ratio: float, description: str):
        console.print(f"[dim]{description} ({ratio*100:.0f}%)[/dim]")

    callbacks = ProgressCallback(
        log_callback=log_callback,
        progress_callback=progress_callback
    )

    # Execute phase-specific workflow
    if args.phase == "research":
        # Research phase only (Perplexity ベンチマーク用途)
        if not args.theme:
            console.print("[red]Error: --theme is required for --phase research[/red]")
            return

        research_brief = await execute_research_phase(
            theme=args.theme,
            mode=args.mode,
            session_manager=session_manager,
            config=app_config,
            callbacks=callbacks
        )

        console.print("\n" + "=" * 50)
        console.print(Panel.fit(
            f"""[bold green]✓ リサーチフェーズ完了！[/bold green]

[bold]出力ファイル:[/bold]
  📋 ResearchBrief: {session_manager.get_research_brief_path()}
  📄 Report: {session_manager.session_dir / 'research_report.md'}

[bold]次のステップ:[/bold]
  外部台本モードで動画生成: python main.py --phase external --verified-script <path>""",
            title="完了",
            border_style="green"
        ))

    elif args.phase == "external":
        # Step 3 (2026-05-09): 外部台本モード（推奨）
        # Mac 側 radio_director の VerifiedScript JSON を読み込み、
        # Phase 1 (planning) + Phase 2 (scripting) を完全 bypass。
        # その後 Phase 3 (production) を実行する。
        if not args.verified_script:
            console.print("[red]Error: --verified-script <path> is required for --phase external[/red]")
            return

        from services.pipeline import execute_external_script_phase

        ext_phase_result = await execute_external_script_phase(
            verified_script_path=Path(args.verified_script),
            session_manager=session_manager,
            config=app_config,
            callbacks=callbacks,
        )

        # ExternalScriptPhaseResult を RadioScriptArtifact 互換に組み立てて
        # 既存 execute_production_phase を呼ぶ
        script_artifact = RadioScriptArtifact(
            session_id=session_manager.session_id,
            script=ext_phase_result.script,
            segments=[seg.model_dump() for seg in ext_phase_result.segments],
            visual_identity=None,
            research_brief_path=None,
            llm_usage=None,
        )

        result = await execute_production_phase(
            script_artifact=script_artifact,
            session_manager=session_manager,
            config=app_config,
            project_root=PROJECT_ROOT,
            callbacks=callbacks,
        )

        console.print("\n" + "=" * 50)
        console.print(Panel.fit(
            f"""[bold green]✓ 動画生成完了！（外部台本モード / LLM コスト ¥0）[/bold green]

[bold]入力 VerifiedScript:[/bold] {args.verified_script}

[bold]出力ファイル:[/bold]
  📹 動画: {result.video_path}
  🎵 音声: {result.audio_path}
  📄 字幕: {result.subtitle_path}

[bold]動画情報:[/bold]
  ⏱️ 長さ: {result.duration_sec:.1f}秒
  📦 サイズ: {result.file_size_mb:.1f}MB
  🎬 タイトル: {script_artifact.script.title}""",
            title="完了 (Step 3: 外部台本モード)",
            border_style="green"
        ))

    elif args.phase == "render":
        # Production phase only
        if args.script:
            # Load from external file
            script_artifact = RadioScriptArtifact.model_validate_json(
                Path(args.script).read_text(encoding="utf-8")
            )
            console.print(f"[dim]Loaded RadioScriptArtifact from: {args.script}[/dim]")
        else:
            # Load from session
            script_artifact = session_manager.load_script_artifact()

        result = await execute_production_phase(
            script_artifact=script_artifact,
            session_manager=session_manager,
            config=app_config,
            project_root=PROJECT_ROOT,
            callbacks=callbacks
        )

        console.print("\n" + "=" * 50)
        console.print(Panel.fit(
            f"""[bold green]✓ 動画生成フェーズ完了！[/bold green]

[bold]出力ファイル:[/bold]
  📹 動画: {result.video_path}
  🎵 音声: {result.audio_path}
  📄 字幕: {result.subtitle_path}

[bold]動画情報:[/bold]
  ⏱️ 長さ: {result.duration_sec:.1f}秒
  📦 サイズ: {result.file_size_mb:.1f}MB
  🎬 タイトル: {script_artifact.script.title}""",
            title="完了",
            border_style="green"
        ))


if __name__ == "__main__":
    asyncio.run(main())
