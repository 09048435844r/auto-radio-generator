"""台本作成フェーズ実行サービス（@deprecated / HITL 用に残置）

Step 4 v2 (2026-05-10): Generator タブの自動経路 + main.py --phase script は削除済み。
このモジュールが提供する execute_fact_extraction_only / execute_curation_only /
execute_scripting_phase は **HITL タブからのみ呼ばれる**ため物理保持されている。

外部台本モード（VerifiedScript JSON）が推奨経路。本モジュールの全 public 関数は
将来削除候補（Step 5 で HITL 自体の見直しが入る場合に再評価）。

ResearchBriefを入力として台本を生成し、RadioScriptArtifactを生成する。
"""
import asyncio
import logging
import time
from typing import Optional
from dataclasses import asdict

from core.models import AppConfig
from core.models.artifacts import ResearchBrief
from core.models.script import RadioScriptArtifact
from core.models.execution_context import ExecutionContext
from core.session_manager import SessionManager
from core.interfaces import ResearchResult
from workflow import (
    ProgressCallback,
    create_script_generator,
    _build_speaker_diagnostics,
    _swap_script_speakers,
    _to_json_safe
)

# PR-F: モジュールレベル logger を新設し、上位 catch から logger.error を呼べるように。
# PR-C の LogFileWriter が root logger に attach した FileHandler 経由で、
# `>>> [ERROR] [services.pipeline.scripting_phase] ...` が processing_log.txt に残る。
logger = logging.getLogger(__name__)


async def execute_fact_extraction_only(
    research_brief: ResearchBrief,
    session_manager: SessionManager,
    config: AppConfig,
    provider: str = "gemini",
    callbacks: Optional[ProgressCallback] = None,
    force: bool = False,
):
    """FactExtractor 単独実行（Phase 4 施策③）

    リサーチ生文字列から構造化 FactSheet を抽出し session に保存する。
    HITL (Gate 1.5) での事前確認、ないし Curator の判断材料キャッシュ用途。

    ## 上書きポリシー（Phase 4 review #2 対応 / Append-Only 思想）
    既存の fact_sheet.json が存在する場合のデフォルト挙動は**拒否**。
    HITL で人間が編集した成果物を無言で消さないため、明示的な上書き許可が必要:

      - `force=False`（既定）: 既存ファイルがあれば `FileExistsError` を送出。
      - `force=True`: 既存ファイルを `fact_sheet.bak.<timestamp>.json` に退避してから
        新しい抽出結果で上書き（バックアップは同一セッションディレクトリに残る）。

    session に fact_sheet.json が存在しない場合は `force` の値に関わらず通常実行。

    Args:
        research_brief: ResearchBrief from research phase
        session_manager: SessionManager instance (saves fact_sheet.json)
        config: Application config
        provider: LLM provider
        callbacks: Progress callback
        force: True なら既存の fact_sheet.json をバックアップして上書き。
               False（既定）なら既存ファイルがあれば FileExistsError。

    Returns:
        FactSheet: 抽出された事実シート（session にも保存済み）

    Raises:
        FileExistsError: force=False かつ既存 fact_sheet.json が存在する場合
    """
    from datetime import datetime
    from services.script_generation.fact_extractor import FactExtractor
    from services.script_generation.adapters.factory import LLMAdapterFactory
    from core.models.research import ResearchSource

    cb = callbacks or ProgressCallback()

    # Phase 4 review #2: guard against silent overwrite of human-edited fact sheets.
    # This check runs BEFORE the expensive LLM call so we never waste tokens on a
    # run that would be rejected at save time.
    fact_sheet_path = session_manager.get_fact_sheet_path()
    if fact_sheet_path.exists() and not force:
        raise FileExistsError(
            f"FactSheet already exists at {fact_sheet_path}. "
            f"Refusing to overwrite (HITL edits may be present). "
            f"Pass force=True to backup + overwrite, or delete the file manually."
        )

    research_sources = [
        ResearchSource.model_validate(source_dict)
        for source_dict in research_brief.research_sources
    ]
    research_data = ResearchResult(
        topic=research_brief.theme,
        mode=research_brief.research_mode,
        content=research_brief.research_content,
        sources=research_sources,
        usage=None,
    )

    cb.log(f"\n== Fact Extraction Only Phase: FactExtractor ==")
    cb.log(f"Theme: {research_brief.theme}")
    cb.log(f"Provider: {provider}")
    cb.progress(0.10, "📋 ファクト抽出中...")

    orch_cfg = config.yaml.script_generator.orchestrator
    fe_cfg = getattr(orch_cfg, "fact_extractor", None)
    fact_extractor_model = (getattr(fe_cfg, "model", "") or "").strip() or orch_cfg.curator_model
    llm_port = LLMAdapterFactory.create(
        config,
        provider,
        model_override=fact_extractor_model,
    )
    extractor = FactExtractor(llm_port, config)

    fact_sheet = await extractor.extract_facts(
        theme=research_brief.theme,
        research_data=research_data,
        progress_log=cb.log,
    )

    # Phase 4 review #2: if we reach here with force=True AND the file still exists,
    # back it up before overwriting so the previous (possibly human-edited) content
    # is never lost. Timestamp resolution is seconds which is enough: concurrent
    # overwrites on the same session are outside our threat model.
    if fact_sheet_path.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = fact_sheet_path.with_name(f"fact_sheet.bak.{ts}.json")
        backup_path.write_bytes(fact_sheet_path.read_bytes())
        cb.log(f"ℹ Previous fact_sheet.json backed up to: {backup_path.name}")

    saved_path = session_manager.save_fact_sheet(fact_sheet)
    cb.log(f"✓ FactSheet saved: {saved_path}")
    cb.progress(1.0, "✅ ファクト抽出完了")

    return fact_sheet


async def execute_curation_only(
    research_brief: ResearchBrief,
    session_manager: SessionManager,
    config: AppConfig,
    provider: str = "gemini",
    callbacks: Optional[ProgressCallback] = None,
):
    """Curator 単独実行: リサーチ結果からトピックを選定し CurationResult を session に保存する

    HITL (Gate 2a) で使用する。ユーザーが編集する前の生の Curator 出力を取得する。
    Phase 4: session に fact_sheet.json が存在すれば自動ロードして Curator に渡す。

    Args:
        research_brief: ResearchBrief from research phase
        session_manager: SessionManager instance (saves curation_result.json)
        config: Application config
        provider: LLM provider
        callbacks: Progress callback

    Returns:
        CurationResult: トピック選定結果（session にも保存済み）
    """
    from services.script_generation.topic_curator import TopicCurator
    from services.script_generation.adapters.factory import LLMAdapterFactory
    from core.models.research import ResearchSource

    cb = callbacks or ProgressCallback()

    # Build ExecutionContext just to get the LLM port wiring (same as scripting_phase)
    context = ExecutionContext(
        provider=provider,
        config=config,
        log_callback=cb.log if cb else None,
        progress_callback=cb.progress if cb else None,
        use_orchestrator=True,
        enable_research=True,
        session_dir=session_manager.session_dir,
    )

    # Convert ResearchBrief to ResearchResult for the curator
    research_sources = [
        ResearchSource.model_validate(source_dict)
        for source_dict in research_brief.research_sources
    ]
    research_data = ResearchResult(
        topic=research_brief.theme,
        mode=research_brief.research_mode,
        content=research_brief.research_content,
        sources=research_sources,
        usage=None,
    )

    cb.log(f"\n== Curation Only Phase: TopicCurator ==")
    cb.log(f"Theme: {research_brief.theme}")
    cb.log(f"Provider: {provider}")
    cb.progress(0.10, "🔍 トピック選定中...")

    # Create curator-specific LLM port via LLMAdapterFactory (same pattern as ScriptOrchestrator).
    # ExecutionContext does not expose a factory method; we use the adapter factory directly.
    curator_model = config.yaml.script_generator.orchestrator.curator_model
    llm_port = LLMAdapterFactory.create(
        config,
        provider,
        model_override=curator_model,
    )
    curator = TopicCurator(llm_port, config)

    # Phase 4: auto-load FactSheet from session if present (fall through gracefully on any error)
    fact_sheet = None
    if session_manager.has_fact_sheet():
        try:
            fact_sheet = session_manager.load_fact_sheet()
            cb.log(
                f"[Curation] Auto-loaded FactSheet from session "
                f"({len(fact_sheet.facts)} facts); will be used as judgment material"
            )
        except Exception as e:
            cb.log(f"[WARN] Failed to load fact_sheet.json ({e}); running Curator without FactSheet")
            fact_sheet = None

    curation_result = await curator.curate_topics(
        research_data=research_data,
        progress_log=cb.log,
        fact_sheet=fact_sheet,
    )

    # Persist to session
    saved_path = session_manager.save_curation_result(curation_result)
    cb.log(f"✓ CurationResult saved: {saved_path}")
    cb.progress(1.0, "✅ トピック選定完了")

    return curation_result


async def execute_scripting_phase(
    research_brief: ResearchBrief,
    session_manager: SessionManager,
    config: AppConfig,
    excluded_topics: Optional[str] = None,
    avoid_topics: Optional[str] = None,
    provider: str = "gemini",
    callbacks: Optional[ProgressCallback] = None,
    preset_curation=None,
    preset_show_plan=None,
    preset_fact_sheet=None,
) -> RadioScriptArtifact:
    """Execute scripting phase and generate RadioScriptArtifact

    Args:
        research_brief: ResearchBrief from research phase
        session_manager: SessionManager instance
        config: Application config
        excluded_topics: Topics to exclude (for multi-part scripts)
        avoid_topics: Topics to avoid (Negative Prompt, optional)
        provider: LLM provider ("gemini" | "openai" | "anthropic" | "ollama")
        callbacks: Progress callback
        preset_curation: Optional CurationResult from HITL (human-edited topics).
                         If provided, skip Curator invocation inside orchestrator.
                         If None and session has curation_result.json, it will be loaded automatically.
        preset_show_plan: Optional ShowPlan from HITL (human-edited show plan, Phase 3).
                          If provided, skip ShowRunner invocation inside orchestrator.
                          If None and session has show_plan.json, it will be loaded automatically.
        preset_fact_sheet: Optional FactSheet from HITL/cache (Phase 4 施策③).
                           If provided, skip FactExtractor invocation inside orchestrator.
                           If None and session has fact_sheet.json, it will be loaded automatically.

    Returns:
        RadioScriptArtifact: Scripting phase output artifact
    """
    cb = callbacks or ProgressCallback()
    
    # Create ExecutionContext for provider-agnostic workflow
    context = ExecutionContext(
        provider=provider,
        config=config,
        log_callback=cb.log if cb else None,
        progress_callback=cb.progress if cb else None,
        use_orchestrator=config.yaml.script_generator.orchestrator.enabled,
        enable_research=True,
        session_dir=session_manager.session_dir  # For markdown script saving
    )
    
    # Convert ResearchBrief to ResearchResult (for backward compatibility)
    from core.models.research import ResearchSource
    
    research_sources = [
        ResearchSource.model_validate(source_dict) 
        for source_dict in research_brief.research_sources
    ]
    
    research_data = ResearchResult(
        topic=research_brief.theme,
        mode=research_brief.research_mode,
        content=research_brief.research_content,
        sources=research_sources,
        usage=None,  # Usage already tracked in ResearchBrief
        # Phase 3 (interface_spec.md v1.0): research_brief.structured_facts を
        # ResearchResult に乗せ、ScriptOrchestrator Step 0.5 で FactExtractor を
        # スキップする際の入力として伝播させる。None / 不在なら従来動作。
        structured_facts=getattr(research_brief, "structured_facts", None),
    )

    # Step 1: Script generation
    cb.log(f"\n== Scripting Phase: Script Generation ==")
    cb.log(f"Theme: {research_brief.theme}")
    cb.log(f"Provider: {context.provider}")
    
    cb.log(f"Engine: {'ScriptOrchestrator (Agentic)' if context.use_orchestrator else 'Direct LLM'}")
    cb.progress(0.50, f"📝 Generating script ({'Orchestrator' if context.use_orchestrator else 'Direct'} - {context.provider})...")
    
    script_start = time.time()
    segments = None
    
    if context.use_orchestrator and research_data is not None:
        # Hierarchical Agentic Workflow with ExecutionContext
        from services.script_generation.orchestrator import ScriptOrchestrator

        # HITL Gate 2a support: auto-load curation_result.json if present and not explicitly passed
        effective_preset = preset_curation
        if effective_preset is None and session_manager.has_curation_result():
            try:
                effective_preset = session_manager.load_curation_result()
                cb.log(
                    f"[Orchestrator] Auto-loaded human-edited CurationResult from session "
                    f"({len(effective_preset.topics)} topics); Curator will be skipped"
                )
            except Exception as e:
                # Defensive: if load fails, fall through to normal Curator execution
                cb.log(f"[WARN] Failed to load curation_result.json ({e}); running Curator normally")
                effective_preset = None

        # HITL Phase 3 support: auto-load show_plan.json if present and not explicitly passed
        effective_show_plan = preset_show_plan
        if effective_show_plan is None and session_manager.has_show_plan():
            try:
                effective_show_plan = session_manager.load_show_plan()
                cb.log(
                    f"[Orchestrator] Auto-loaded ShowPlan from session "
                    f"(bridges={len(effective_show_plan.topic_bridges)}); ShowRunner will be skipped"
                )
            except Exception as e:
                cb.log(f"[WARN] Failed to load show_plan.json ({e}); ShowRunner will run if enabled")
                effective_show_plan = None

        # Phase 4 support: auto-load fact_sheet.json if present and not explicitly passed
        effective_fact_sheet = preset_fact_sheet
        if effective_fact_sheet is None and session_manager.has_fact_sheet():
            try:
                effective_fact_sheet = session_manager.load_fact_sheet()
                cb.log(
                    f"[Orchestrator] Auto-loaded FactSheet from session "
                    f"({len(effective_fact_sheet.facts)} facts); FactExtractor will be skipped"
                )
            except Exception as e:
                cb.log(f"[WARN] Failed to load fact_sheet.json ({e}); FactExtractor will run if enabled")
                effective_fact_sheet = None

        cb.log(f"[Orchestrator] Long-form script generation with {context.provider} (TopicCuration → SegmentGeneration)")
        orchestrator = ScriptOrchestrator(context)
        script = await orchestrator.generate_script(
            theme=research_brief.theme,
            research_data=research_data,
            avoid_topics=avoid_topics,
            excluded_topics=excluded_topics,
            progress_callback=cb,
            preset_curation=effective_preset,
            preset_show_plan=effective_show_plan,
            preset_fact_sheet=effective_fact_sheet,
        )
        llm_usage = orchestrator.get_total_usage()
        segments = orchestrator.segments

        # Phase 3: Persist the ShowPlan that was actually used (if any), so downstream
        # steps (HITL, debug, re-runs) can inspect it. This is purely additive.
        try:
            actually_used_show_plan = effective_show_plan
            if actually_used_show_plan is None:
                # ShowRunner ran inside the orchestrator; pull it from the agent
                actually_used_show_plan = getattr(
                    getattr(orchestrator, "show_runner", None), "last_show_plan", None
                )
            if actually_used_show_plan is not None and not session_manager.has_show_plan():
                session_manager.save_show_plan(actually_used_show_plan)
                cb.log(f"✓ ShowPlan saved: {session_manager.get_show_plan_path().name}")
        except Exception as e:
            cb.log(f"[WARN] Failed to save show_plan.json (non-fatal): {e}")

        # Phase 4: Persist the FactSheet that was actually used (if any), so downstream
        # re-runs can skip FactExtractor. Purely additive; failure is non-fatal.
        try:
            actually_used_fact_sheet = effective_fact_sheet
            if actually_used_fact_sheet is None:
                actually_used_fact_sheet = getattr(
                    getattr(orchestrator, "fact_extractor", None), "last_fact_sheet", None
                )
            if actually_used_fact_sheet is not None and not session_manager.has_fact_sheet():
                session_manager.save_fact_sheet(actually_used_fact_sheet)
                cb.log(f"✓ FactSheet saved: {session_manager.get_fact_sheet_path().name}")
        except Exception as e:
            cb.log(f"[WARN] Failed to save fact_sheet.json (non-fatal): {e}")
    else:
        # Single API call (fallback) - still uses provider selection
        script_generator = create_script_generator(config, provider=context.provider)
        script = await script_generator.generate(
            research_brief.theme,
            research_data,
            avoid_topics=avoid_topics,
            excluded_topics=excluded_topics
        )
        llm_usage = script_generator.last_usage
    
    # Speaker diagnostics and auto-correction
    phase_label = "Part 2" if excluded_topics and excluded_topics.strip() else "Part 1/Single"
    diagnostics, suspected_swap = _build_speaker_diagnostics(script, label=phase_label)
    for msg in diagnostics:
        cb.log(msg)
    
    if suspected_swap:
        cb.log("[WARN] Detected speaker role swap based on speech patterns. Applying auto-correction...")
        script = _swap_script_speakers(script)
        fixed_diagnostics, _ = _build_speaker_diagnostics(script, label=f"{phase_label} (fixed)")
        for msg in fixed_diagnostics:
            cb.log(msg)
    
    script_duration = time.time() - script_start
    cb.log(f"✓ Script generation completed: {len(script.sections)} phrases ({script_duration:.1f}s)")
    cb.log(f"Title: {script.title}")
    cb.progress(0.65, "✅ Script generation completed")
    await asyncio.sleep(0)  # Yield to event loop for Gradio progress flush
    
    # Save script (backward compatibility)
    script_path = session_manager.session_dir / "script.json"
    script_path.write_text(script.model_dump_json(indent=2), encoding="utf-8")
    cb.log(f"✓ Script saved: {script_path.name}")
    
    # Step 2: Visual Identity Generation (for dynamic background mode)
    visual_identity = None
    video_config = getattr(config.yaml, "video_renderer", None)
    background_mode = getattr(video_config, "background_mode", "static") if video_config else "static"
    
    if background_mode == "dynamic":
        # Skip VisualPaletteGenerator for Ollama (Gemini-only feature)
        if provider.lower() == "ollama":
            cb.log("\n== Scripting Phase: Visual Identity Generation ==")
            cb.log("[INFO] Ollama provider detected: Skipping visual identity generation (Gemini-only feature)")
            cb.log("[INFO] Using default visual identity")
            cb.progress(0.70, "⚡ Using default visual identity (Ollama)")
            await asyncio.sleep(0)
            
            from core.models.visual import (
                VisualIdentity,
                DEFAULT_PRIMARY_COLOR,
                DEFAULT_SECONDARY_COLOR,
                DEFAULT_COLOR_MOOD,
                DEFAULT_AESTHETIC,
                DEFAULT_VISUAL_KEYWORDS
            )
            visual_identity = VisualIdentity(
                primary_color=DEFAULT_PRIMARY_COLOR,
                secondary_color=DEFAULT_SECONDARY_COLOR,
                color_mood=DEFAULT_COLOR_MOOD,
                aesthetic=DEFAULT_AESTHETIC,
                visual_keywords=list(DEFAULT_VISUAL_KEYWORDS)  # Convert tuple to list
            )
        else:
            try:
                cb.log("\n== Scripting Phase: Visual Identity Generation ==")
                cb.log("[INFO] Generating visual brand (color + style) for FLUX.1...")
                cb.progress(0.70, "🎨 Generating visual identity...")
                await asyncio.sleep(0)  # Yield to event loop for Gradio progress flush
                
                from services.script_generation.visual_palette_generator import VisualPaletteGenerator
                
                palette_generator = VisualPaletteGenerator(config)
                script_summary = script.description[:300] if script.description else research_brief.theme
                
                visual_identity = await palette_generator.generate_palette(
                    theme=research_brief.theme,
                    script_summary=script_summary
                )
                
                cb.log(f"✓ Visual identity determined: {visual_identity}")
                cb.progress(0.80, "✅ Visual identity generated")
                await asyncio.sleep(0)  # Yield to event loop for Gradio progress flush
            except Exception as e:
                # PR-F: logger.error も併用して PR-C の processing_log.txt 収集に乗せる。
                logger.error("Visual identity generation failed: %s", e, exc_info=True)
                cb.log(f"⚠ Visual identity generation failed: {e}")
                cb.log("[INFO] Using default visual identity")
                from core.models.visual import (
                    VisualIdentity,
                    DEFAULT_PRIMARY_COLOR,
                    DEFAULT_SECONDARY_COLOR,
                    DEFAULT_COLOR_MOOD,
                    DEFAULT_AESTHETIC,
                    DEFAULT_VISUAL_KEYWORDS
                )
                visual_identity = VisualIdentity(
                    primary_color=DEFAULT_PRIMARY_COLOR,
                    secondary_color=DEFAULT_SECONDARY_COLOR,
                    color_mood=DEFAULT_COLOR_MOOD,
                    aesthetic=DEFAULT_AESTHETIC,
                    visual_keywords=list(DEFAULT_VISUAL_KEYWORDS)  # Convert tuple to list
                )
                cb.progress(0.80, "⚠️ Using default visual identity")
                await asyncio.sleep(0)  # Yield to event loop for Gradio progress flush
    else:
        cb.log("[INFO] Static mode: Skipping visual identity generation")
        cb.progress(0.80, "⏭️ Skipping visual identity generation")
    
    # Step 3: Metadata Generation
    # use_orchestrator=True の場合、ScriptOrchestrator.generate_script() の
    # Step 4 (orchestrator.py:447-454) で MetadataGenerator が curator_model
    # で既に実行済みであり、戻り値の Script に title/description が充填されている。
    # ここで再実行すると LLM コールが冗長になり、出力も上書きされるため、
    # use_orchestrator=False の旧経路（create_script_generator）でのみ実行する。
    if context.use_orchestrator:
        cb.log("\n== Scripting Phase: Metadata Generation (skipped: handled by orchestrator) ==")
        cb.log(f"✓ Metadata already generated by orchestrator: {script.title}")
        cb.progress(0.90, "✅ Metadata (from orchestrator)")
        await asyncio.sleep(0)  # Yield to event loop for Gradio progress flush
    else:
        cb.log("\n== Scripting Phase: Metadata Generation ==")
        cb.progress(0.85, "🔖 Generating metadata...")
        await asyncio.sleep(0)  # Yield to event loop for Gradio progress flush

        try:
            from services.script_generation.metadata_generator import MetadataGenerator
            from services.script_generation.adapters.factory import LLMAdapterFactory

            # Create LLM port for metadata generation.
            # 2026-05-01: model_override に curator_model を渡す。これが無いと
            # Ollama provider のとき script_generator.ollama.model（運用上は
            # 大型モデル名）にフォールバックしてしまうため、curator_model 統一で
            # SSOT を保つ。
            curator_model = config.yaml.script_generator.orchestrator.curator_model
            llm_port = LLMAdapterFactory.create(
                config,
                context.provider,
                model_override=curator_model or None,
            )

            metadata_generator = MetadataGenerator(llm_port, config)
            script = await metadata_generator.generate(
                theme=research_brief.theme,
                script=script,
                research_data=research_data,
                progress_log=cb.log
            )

            cb.log(f"✓ Metadata generated: {script.title}")
            cb.progress(0.90, "✅ Metadata generation completed")
        except Exception as e:
            # PR-F: logger.error も併用して PR-C の processing_log.txt 収集に乗せる。
            # cb.log は rich console 経由で「⚠ ...」が出るが、stack trace は消える。
            # logger.error(..., exc_info=True) で stack trace も processing_log.txt に残す。
            logger.error("MetadataGenerator failed; using defaults: %s", e, exc_info=True)
            cb.log(f"⚠ Metadata generation failed (using defaults): {e}")
            cb.progress(0.90, "⚠️ Using default metadata")
    
    await asyncio.sleep(0)  # Yield to event loop for Gradio progress flush

    # Step 3.5: Fact Check (フェイルオープン)
    # MetadataGenerator 後、artifact build の前に台本のハルシネーション検出を行う。
    # config.fact_checker.enabled=True なら実行、エラーは WARNING のみ。
    # 出力: <session>/factcheck_report.json（UI 側で読み込んで表示）
    #
    # Phase 3A: 続けて FactFixAgent を実行し、high/medium の issues を自動修正する。
    # config.fact_checker.auto_fix=True かつ FactCheckReport に high/medium issue が
    # 1 件以上ある場合のみ実行。修正結果は script_fixed.json として保存し、
    # 以降の音声合成は fixed 版を使う（artifact 内の script を差し替え）。
    fc_cfg = getattr(config.yaml.script_generator.orchestrator, "fact_checker", None)
    if fc_cfg is not None and getattr(fc_cfg, "enabled", False):
        cb.log("\n== Scripting Phase: Fact Check ==")
        cb.progress(0.92, "🔍 Fact-checking script vs research...")
        await asyncio.sleep(0)
        try:
            from services.script_generation.fact_checker import (
                FactChecker,
                FactFixAgent,
                apply_fixes_to_script,
            )
            from services.script_generation.adapters.factory import LLMAdapterFactory

            curator_model = config.yaml.script_generator.orchestrator.curator_model
            fc_llm_port = LLMAdapterFactory.create(
                config,
                context.provider,
                model_override=curator_model or None,
            )
            fact_checker = FactChecker(fc_llm_port, config)
            fc_report = await fact_checker.check(
                theme=research_brief.theme,
                script=script,
                research_data=research_data,
                progress_log=cb.log,
            )
            saved_fc_path = session_manager.save_fact_check_report(fc_report)
            cb.log(
                f"✓ Fact check completed: confidence={fc_report.overall_confidence}, "
                f"issues={len(fc_report.issues)} → {saved_fc_path.name}"
            )

            # Phase 3A: 自動修正
            auto_fix_enabled = getattr(fc_cfg, "auto_fix", True)
            high_med_issues = [i for i in fc_report.issues if i.severity in ("high", "medium")]
            if auto_fix_enabled and high_med_issues:
                cb.log("\n== Scripting Phase: Auto-Fix (FactFixAgent) ==")
                cb.progress(0.93, f"🛠 自動修正中（{len(high_med_issues)}件）...")
                await asyncio.sleep(0)
                try:
                    fixer = FactFixAgent(fc_llm_port, config)
                    await fixer.fix_report(fc_report, progress_log=cb.log)

                    # 修正済み issues を report に書き戻して再保存（fixed_text/auto_fixed が埋まる）
                    session_manager.save_fact_check_report(fc_report)

                    if fixer.last_fixed_count > 0:
                        fixed_script, applied = apply_fixes_to_script(script, fc_report)
                        session_manager.save_script_fixed(fixed_script)
                        cb.log(
                            f"✓ 自動修正適用: {applied}件 → "
                            f"{session_manager.get_script_fixed_path().name}"
                        )
                        # 以降の音声合成は fixed 版を使う
                        script = fixed_script
                    else:
                        cb.log("[INFO] 自動修正: 適用件数 0 件のため script_fixed.json は作成しません")

                    cb.progress(0.94, "✅ Fact check + auto-fix completed")
                except Exception as e:
                    # 自動修正の失敗もフェイルオープン（FactCheck の結果は保持）
                    logger.warning("FactFixAgent failed (non-fatal, skipping): %s", e, exc_info=True)
                    cb.log(f"⚠ 自動修正失敗（fact check は完了済み、original script を使用）: {e}")
                    cb.progress(0.94, "⚠️ Auto-fix skipped")
            else:
                if not auto_fix_enabled:
                    cb.log("[INFO] 自動修正は無効（config.fact_checker.auto_fix=false）")
                else:
                    cb.log("[INFO] 自動修正対象なし（high/medium issue が 0 件）")
                cb.progress(0.94, "✅ Fact check completed")
        except Exception as e:
            # フェイルオープン: パイプラインを止めない。
            # PR-F: logger.error は呼ばず logger.warning に留める（致命的でないため）。
            logger.warning("FactChecker failed (non-fatal, skipping): %s", e, exc_info=True)
            cb.log(f"⚠ Fact check failed (skipped, non-fatal): {e}")
            cb.progress(0.94, "⚠️ Fact check skipped")
    else:
        cb.log("[INFO] Fact check disabled (config.fact_checker.enabled=false)")
        cb.progress(0.94, "⏭️ Fact check skipped (disabled)")

    await asyncio.sleep(0)  # Yield to event loop for Gradio progress flush

    # Step 4: Build RadioScriptArtifact
    cb.progress(0.95, "📦 Building script artifact...")
    await asyncio.sleep(0)  # Yield to event loop for Gradio progress flush
    script_artifact = RadioScriptArtifact(
        session_id=session_manager.session_id,
        script=script,
        segments=[_to_json_safe(seg.model_dump()) for seg in segments] if segments else None,
        visual_identity=_to_json_safe(visual_identity.model_dump()) if visual_identity else None,
        research_brief_path="research_brief.json",
        llm_usage=_to_json_safe(asdict(llm_usage)) if llm_usage else None,
    )
    
    # Save RadioScriptArtifact
    saved_path = session_manager.save_script_artifact(script_artifact)
    cb.log(f"✓ RadioScriptArtifact saved: {saved_path}")
    
    cb.progress(1.0, "✅ Scripting phase completed")
    cb.log(f"✓ Scripting phase completed ({script_duration:.1f}s)")
    
    return script_artifact
