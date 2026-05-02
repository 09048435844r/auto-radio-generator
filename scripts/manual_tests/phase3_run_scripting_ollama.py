"""Phase 3 実機検証ランナー: Ollama provider で execute_scripting_phase を直接呼ぶ

main.py の --provider choices には ollama が含まれないため、本スクリプトで
直接 pipeline を呼び出して structured_facts → TopicCurator 経路を実機検証する。

期待する観察ポイント:
  1. Step 0.5 が "structured_facts から変換、FactExtractor スキップ" と出る
  2. Curator → ShowRunner → SegmentGenerator が完走し script.json が生成される
  3. fact_sheet.json は出力されない（FactExtractor が走っていないため）
"""
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console

from core.models.config import load_config
from core.models.artifacts import ResearchBrief
from core.session_manager import SessionManager
from services.pipeline import execute_scripting_phase
from workflow import ProgressCallback


async def main():
    console = Console()
    app_config = load_config(PROJECT_ROOT)

    # Use a brand-new session dir
    session_manager = SessionManager(project_root=PROJECT_ROOT, session_id=None)
    console.print(f"[bold]Session:[/bold] {session_manager.session_id}")
    console.print(f"[bold]Dir:    [/bold] {session_manager.session_dir}")

    brief_path = PROJECT_ROOT / "output" / "_phase3_test" / "research_brief.json"
    research_brief = ResearchBrief.model_validate_json(
        brief_path.read_text(encoding="utf-8")
    )
    console.print(f"[dim]Loaded brief: {brief_path}[/dim]")
    sf = research_brief.structured_facts or {}
    console.print(
        f"[dim]structured_facts: key_numbers={len(sf.get('key_numbers', []))} "
        f"key_entities={len(sf.get('key_entities', []))} "
        f"surprising_claims={len(sf.get('surprising_claims', []))} "
        f"controversies={len(sf.get('controversies', []))}[/dim]"
    )

    callbacks = ProgressCallback(
        log_callback=lambda msg: console.print(msg),
        progress_callback=lambda r, d: console.print(f"[dim]({r * 100:.0f}%) {d}[/dim]"),
    )

    script_artifact = await execute_scripting_phase(
        research_brief=research_brief,
        session_manager=session_manager,
        config=app_config,
        provider="ollama",
        callbacks=callbacks,
    )

    console.print("\n" + "=" * 60)
    console.print(f"[bold green]✓ scripting phase 完了[/bold green]")
    console.print(f"  Title       : {script_artifact.script.title}")
    console.print(f"  Sections    : {len(script_artifact.script.sections)}")
    console.print(f"  Hashtags    : {script_artifact.script.hashtags}")
    console.print(f"  Output dir  : {session_manager.session_dir}")


if __name__ == "__main__":
    asyncio.run(main())
