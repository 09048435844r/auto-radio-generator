"""リサーチフェーズ実行サービス

企画（検索計画作成）とリサーチ（情報収集）を実行し、ResearchBriefを生成する。

Step 4 v2 (2026-05-10): Gemini ベースの AI 検索計画作成は廃止。
入力 theme をそのまま 1 件の Perplexity クエリとして渡すシンプルな経路に変更。
"""
import time
from typing import Optional
from dataclasses import asdict

from core.models import AppConfig
from core.models.artifacts import ResearchBrief
from core.interfaces import ResearchMode
from core.session_manager import SessionManager
from workflow import (
    ProgressCallback,
    create_researcher,
    _to_json_safe,
)


async def execute_research_phase(
    theme: str,
    mode: ResearchMode,
    session_manager: SessionManager,
    config: AppConfig,
    instruction: Optional[str] = None,
    avoid_topics: Optional[str] = None,
    callbacks: Optional[ProgressCallback] = None
) -> ResearchBrief:
    """Execute research phase and generate ResearchBrief

    Step 4 v2 (2026-05-10): GeminiClient.create_research_plan を経由した
    AI 検索計画作成は削除。`queries=[theme]` の単純経路で Perplexity を呼ぶ。
    instruction 引数は互換性のため残置（現状は未使用）。

    Args:
        theme: Research theme
        mode: Research mode (debate/voices/trivia/lecture/weekly_digest)
        session_manager: SessionManager instance
        config: Application config
        instruction: 互換のため残置（Step 4 v2 で未使用）
        avoid_topics: Topics to avoid (Negative Prompt, optional)
        callbacks: Progress callback

    Returns:
        ResearchBrief: Research phase output artifact
    """
    cb = callbacks or ProgressCallback()

    # Step 1: Plan (Step 4 v2 簡略化: theme をそのままクエリに使う)
    cb.log(f"\n== Research Phase: Plan ==")
    cb.log(f"Theme: {theme}")
    cb.log(f"Mode: {mode}")
    cb.progress(0.10, "📝 Preparing search query (single-query mode)...")

    planning_start = time.time()
    queries = [theme]
    angle = "（自動: テーマをそのまま単一クエリに使用 / Step 4 v2）"
    cb.log(f"✓ Plan ready (Step 4 v2: AI 検索計画作成は廃止)")
    cb.log(f"Angle: {angle}")
    cb.log(f"\nSearch queries:")
    for i, q in enumerate(queries, 1):
        cb.log(f"  {i}. {q}")

    # Step 2: Research (collect information)
    cb.log(f"\n== Research Phase: Information Collection ==")
    cb.progress(0.30, "🔍 Executing research (Perplexity)...")

    research_start = time.time()

    try:
        researcher = create_researcher(config)
        research_data = await researcher.research_multi(queries, mode, avoid_topics=avoid_topics)

        cb.log(f"✓ Research completed")
        cb.log(f"Collected content: {len(research_data.content)} characters")

        perplexity_usage = research_data.usage

    except Exception as e:
        cb.log(f"❌ Research error: {e}")
        raise

    cb.progress(0.50, "✅ Research phase completed")

    # Step 3: Build ResearchBrief
    research_brief = ResearchBrief(
        session_id=session_manager.session_id,
        theme=theme,
        research_mode=mode,
        research_content=research_data.content,
        research_sources=[
            _to_json_safe(source.model_dump()) for source in (research_data.sources or [])
        ],
        queries=queries,
        angle=angle,
        curated_topics=None,
        perplexity_usage=_to_json_safe(asdict(perplexity_usage)) if perplexity_usage else None,
        gemini_usage_planning=None,  # Step 4 v2: planning step is gone
    )

    # Save ResearchBrief
    saved_path = session_manager.save_research_brief(research_brief)
    cb.log(f"✓ ResearchBrief saved: {saved_path}")

    # Also save research report (backward compatibility)
    report_path = session_manager.session_dir / "research_report.md"
    report_content = f"""# Research Report

**Theme**: {theme}
**Mode**: {mode}
**Angle**: {angle}

## Search Queries
{chr(10).join([f"{i+1}. {q}" for i, q in enumerate(queries)])}

## Research Content
{research_data.content}
"""
    report_path.write_text(report_content, encoding="utf-8")
    cb.log(f"✓ Research report saved: {report_path}")

    total_duration = time.time() - planning_start
    cb.log(f"✓ Research phase completed ({total_duration:.1f}s)")

    return research_brief
