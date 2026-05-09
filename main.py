"""自動ラジオ動画生成システム - メインエントリーポイント

パイプライン分離アーキテクチャ対応:
- --phase all: 一気通貫モード（デフォルト、旧 LLM 経路）
- --phase research: リサーチフェーズのみ実行（旧 LLM 経路）
- --phase script: 台本作成フェーズのみ実行（旧 LLM 経路）
- --phase render: 動画生成フェーズのみ実行
- --phase external: 外部台本モード（推奨）

Step 3 (2026-05-09): Mac 側 radio_director の VerifiedScript JSON を読み込み、
Phase 1 (planning) + Phase 2 (scripting) を完全 bypass する `--phase external` を追加。
旧 LLM 経路 (research/script/all) は deprecated 注記付きで残置、Step 4 (v2) で
削除予定。
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
from core.models.artifacts import ResearchBrief
from core.models.script import RadioScriptArtifact
from core.session_manager import SessionManager
from core.interfaces import ResearchMode
from services.pipeline import (
    execute_research_phase,
    execute_scripting_phase,
    execute_production_phase
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
  # 一気通貫モード（全フェーズ実行）
  python main.py --theme "持続血糖測定器CGMについて"
  
  # リサーチフェーズのみ実行
  python main.py --phase research --theme "持続血糖測定器CGMについて" --mode lecture
  
  # 台本作成フェーズのみ実行（既存セッション使用）
  python main.py --phase script --session 20260404_065500
  
  # 動画生成フェーズのみ実行（既存セッション使用）
  python main.py --phase render --session 20260404_065500
  
  # 外部ファイルから読み込んで実行
  python main.py --phase script --research-brief workspace/20260404_065500/research_brief.json
  python main.py --phase render --script workspace/20260404_065500/script_artifact.json

  # Step 3 (2026-05-09): 外部台本モード（推奨）
  python main.py --phase external --verified-script output/imports/run_001/verified_script.json
"""
    )

    # Phase selection (external is Step 3 推奨経路)
    parser.add_argument(
        "--phase",
        choices=["all", "research", "script", "render", "external"],
        default="all",
        help=(
            "実行するフェーズ "
            "(all: 全フェーズ, research: リサーチのみ, script: 台本作成のみ, "
            "render: 動画生成のみ, external: 外部台本モード [推奨])"
        )
    )
    
    # Session management
    parser.add_argument(
        "--session",
        type=str,
        help="既存セッションID（指定した場合は続きから実行）"
    )
    
    # Input files (for phase-specific execution)
    parser.add_argument(
        "--research-brief",
        type=str,
        help="ResearchBriefファイルのパス（--phase script時に使用）"
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
    
    # Theme (for new execution)
    parser.add_argument(
        "--theme",
        type=str,
        help="動画のテーマ（--phase all または research時に必須）"
    )
    
    # Research mode
    parser.add_argument(
        "--mode",
        choices=["debate", "voices", "trivia", "lecture", "weekly_digest"],
        default="trivia",
        help="リサーチモード（デフォルト: trivia）"
    )
    
    # LLM provider
    parser.add_argument(
        "--provider",
        choices=["gemini", "openai", "anthropic"],
        default="gemini",
        help="LLMプロバイダー（デフォルト: gemini）"
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
    if args.phase == "all":
        # All-in-one mode (backward compatible)
        if not args.theme:
            console.print("[red]Error: --theme is required for --phase all[/red]")
            return
        
        # Research phase
        research_brief = await execute_research_phase(
            theme=args.theme,
            mode=args.mode,
            session_manager=session_manager,
            config=app_config,
            callbacks=callbacks
        )
        
        # Scripting phase
        script_artifact = await execute_scripting_phase(
            research_brief=research_brief,
            session_manager=session_manager,
            config=app_config,
            provider=args.provider,
            callbacks=callbacks
        )
        
        # Production phase
        result = await execute_production_phase(
            script_artifact=script_artifact,
            session_manager=session_manager,
            config=app_config,
            project_root=PROJECT_ROOT,
            callbacks=callbacks
        )
        
        console.print("\n" + "=" * 50)
        console.print(Panel.fit(
            f"""[bold green]✓ 動画生成完了！[/bold green]

[bold]出力ファイル:[/bold]
  📹 動画: {result.video_path}
  📝 台本: {session_manager.session_dir / 'script.json'}
  🎵 音声: {result.audio_path}
  📄 字幕: {result.subtitle_path}

[bold]動画情報:[/bold]
  ⏱️ 長さ: {result.duration_sec:.1f}秒
  📦 サイズ: {result.file_size_mb:.1f}MB
  🎬 タイトル: {script_artifact.script.title}""",
            title="完了",
            border_style="green"
        ))
    
    elif args.phase == "research":
        # Research phase only
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
  台本作成: python main.py --phase script --session {session_manager.session_id}""",
            title="完了",
            border_style="green"
        ))
    
    elif args.phase == "script":
        # Scripting phase only
        if args.research_brief:
            # Load from external file
            research_brief = ResearchBrief.model_validate_json(
                Path(args.research_brief).read_text(encoding="utf-8")
            )
            console.print(f"[dim]Loaded ResearchBrief from: {args.research_brief}[/dim]")
        else:
            # Load from session
            research_brief = session_manager.load_research_brief()
        
        script_artifact = await execute_scripting_phase(
            research_brief=research_brief,
            session_manager=session_manager,
            config=app_config,
            provider=args.provider,
            callbacks=callbacks
        )
        
        console.print("\n" + "=" * 50)
        console.print(Panel.fit(
            f"""[bold green]✓ 台本作成フェーズ完了！[/bold green]

[bold]出力ファイル:[/bold]
  📋 RadioScriptArtifact: {session_manager.get_script_artifact_path()}
  📝 Script: {session_manager.session_dir / 'script.json'}

[bold]台本情報:[/bold]
  🎬 タイトル: {script_artifact.script.title}
  📊 フレーズ数: {len(script_artifact.script.sections)}

[bold]次のステップ:[/bold]
  動画生成: python main.py --phase render --session {session_manager.session_id}""",
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
