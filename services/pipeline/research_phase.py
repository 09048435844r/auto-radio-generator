"""リサーチフェーズ実行サービス

企画（検索計画作成）とリサーチ（情報収集）を実行し、ResearchBriefを生成する。
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
    create_script_generator,
    create_researcher,
    _to_json_safe
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
    
    Args:
        theme: Research theme
        mode: Research mode (debate/voices/trivia/lecture/weekly_digest)
        session_manager: SessionManager instance
        config: Application config
        instruction: Additional instruction (optional)
        avoid_topics: Topics to avoid (Negative Prompt, optional)
        callbacks: Progress callback
        
    Returns:
        ResearchBrief: Research phase output artifact
    """
    cb = callbacks or ProgressCallback()
    
    # Step 1: Planning (create search queries)
    cb.log(f"\n== Research Phase: Planning ==")
    cb.log(f"Theme: {theme}")
    cb.log(f"Mode: {mode}")
    cb.progress(0.10, "🤔 Creating search plan...")
    
    planning_start = time.time()
    
    try:
        # Create search plan using Gemini
        script_generator = create_script_generator(config, provider="gemini")
        plan = await script_generator.create_research_plan(theme, mode, instruction)
        
        max_queries = max(1, int(getattr(config.yaml.researcher, "max_queries_per_plan", 3)))
        if len(plan.queries) > max_queries:
            cb.log(f"[WARN] Limited queries to {max_queries} (generated: {len(plan.queries)})")
            plan.queries = plan.queries[:max_queries]
        
        cb.log(f"✓ Planning completed")
        cb.log(f"Angle: {plan.angle}")
        cb.log(f"\nSearch queries:")
        for i, q in enumerate(plan.queries, 1):
            cb.log(f"  {i}. {q}")
        
        gemini_usage_planning = script_generator.last_usage
        
    except Exception as e:
        cb.log(f"❌ Planning phase error: {e}")
        raise
    
    # Step 2: Research (collect information)
    cb.log(f"\n== Research Phase: Information Collection ==")
    cb.progress(0.30, "🔍 Executing research (Perplexity)...")
    
    research_start = time.time()
    
    try:
        researcher = create_researcher(config)
        research_data = await researcher.research_multi(plan.queries, mode, avoid_topics=avoid_topics)
        
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
            _to_json_safe(asdict(source)) for source in (research_data.sources or [])
        ],
        queries=plan.queries,
        angle=plan.angle,
        curated_topics=None,  # Will be populated by scripting phase if Orchestrator is used
        perplexity_usage=_to_json_safe(asdict(perplexity_usage)) if perplexity_usage else None,
        gemini_usage_planning=_to_json_safe(asdict(gemini_usage_planning)) if gemini_usage_planning else None,
    )
    
    # Save ResearchBrief
    saved_path = session_manager.save_research_brief(research_brief)
    cb.log(f"✓ ResearchBrief saved: {saved_path}")
    
    # Also save research report (backward compatibility)
    report_path = session_manager.session_dir / "research_report.md"
    report_content = f"""# Research Report

**Theme**: {theme}
**Mode**: {mode}
**Angle**: {plan.angle}

## Search Queries
{chr(10).join([f"{i+1}. {q}" for i, q in enumerate(plan.queries)])}

## Research Content
{research_data.content}
"""
    report_path.write_text(report_content, encoding="utf-8")
    cb.log(f"✓ Research report saved: {report_path}")
    
    total_duration = time.time() - planning_start
    cb.log(f"✓ Research phase completed ({total_duration:.1f}s)")
    
    return research_brief
