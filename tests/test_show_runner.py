"""ShowRunner / ShowPlan regression tests (Phase 3 施策④)

Scope (unit-level, no real LLM calls):
  1. ShowPlan accessor methods work correctly
  2. ShowRunner._parse_show_plan_response correctly parses valid/sanitizable JSON
  3. SegmentGenerator prompt builders inject show_plan_hint defensively
  4. Orchestrator._build_*_hint helpers produce None for None ShowPlan (backward compat)
  5. SessionManager save/load/has methods round-trip correctly
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.models.show_plan import ShowPlan, TopicBridge


# ---------------------------------------------------------------------------
# ShowPlan data model tests
# ---------------------------------------------------------------------------

def _make_sample_show_plan() -> ShowPlan:
    return ShowPlan(
        overall_arc="謎提示→驚愕の事実→反転→余韻",
        intro_hook_strategy="冒頭3ターンで最大の数字を提示",
        topic_bridges=[
            TopicBridge(from_topic_index=-1, to_topic_index=0, transition_hint="謎かけから最初の深掘りへ"),
            TopicBridge(from_topic_index=0, to_topic_index=1, transition_hint="対比を強調"),
            TopicBridge(from_topic_index=1, to_topic_index=-1, transition_hint="余韻を残す問いで締めへ"),
        ],
        conclusion_strategy="一言に絞って余韻を残す",
        overall_tone="驚き多め、ユーモア控えめ",
        planner_reasoning="テスト用",
    )


def test_show_plan_get_bridge_into():
    plan = _make_sample_show_plan()
    b = plan.get_bridge_into(0)
    assert b is not None
    assert b.from_topic_index == -1
    assert plan.get_bridge_into(-1).to_topic_index == -1
    assert plan.get_bridge_into(99) is None


def test_show_plan_get_bridge_out_of():
    plan = _make_sample_show_plan()
    b = plan.get_bridge_out_of(-1)
    assert b is not None
    assert b.to_topic_index == 0
    assert plan.get_bridge_out_of(1).to_topic_index == -1
    assert plan.get_bridge_out_of(99) is None


def test_show_plan_roundtrip_json():
    """ShowPlan must serialize and deserialize without loss."""
    plan = _make_sample_show_plan()
    blob = plan.model_dump_json()
    restored = ShowPlan.model_validate_json(blob)
    assert restored.overall_arc == plan.overall_arc
    assert len(restored.topic_bridges) == 3
    assert restored.topic_bridges[1].transition_hint == "対比を強調"


# ---------------------------------------------------------------------------
# ShowRunner._parse_show_plan_response
# ---------------------------------------------------------------------------

def _make_show_runner_for_parse(mock_app_config):
    """Build a ShowRunner instance without touching the LLM port."""
    from services.script_generation.show_runner import ShowRunner

    # Minimal stub LLM port (not used by _parse_show_plan_response)
    mock_port = MagicMock()
    mock_port.provider_name = "gemini"

    # Inject minimal orchestrator config so constructor doesn't crash
    mock_app_config.yaml.script_generator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.curator_model = "gemini-2.5-flash"
    mock_app_config.yaml.script_generator.orchestrator.show_runner = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.show_runner.model = ""

    return ShowRunner(mock_port, mock_app_config)


def test_parse_valid_json(mock_app_config):
    runner = _make_show_runner_for_parse(mock_app_config)
    raw = json.dumps({
        "overall_arc": "起伏のあるアーク",
        "intro_hook_strategy": "数字で掴む",
        "topic_bridges": [
            {"from_topic_index": -1, "to_topic_index": 0, "transition_hint": "入り"},
            {"from_topic_index": 0, "to_topic_index": -1, "transition_hint": "締め"},
        ],
        "conclusion_strategy": "問いで終わる",
        "overall_tone": "驚き多め",
        "planner_reasoning": "テスト",
    })
    plan = runner._parse_show_plan_response(raw, topic_count=1)
    assert plan.overall_arc == "起伏のあるアーク"
    assert len(plan.topic_bridges) == 2
    assert plan.topic_bridges[0].from_topic_index == -1


def test_parse_skips_malformed_bridges(mock_app_config):
    """Bridges with non-integer indices should be skipped, not crash."""
    runner = _make_show_runner_for_parse(mock_app_config)
    raw = json.dumps({
        "overall_arc": "X",
        "intro_hook_strategy": "Y",
        "topic_bridges": [
            {"from_topic_index": -1, "to_topic_index": 0, "transition_hint": "valid"},
            {"from_topic_index": "not-an-int", "to_topic_index": 1, "transition_hint": "invalid"},
        ],
        "conclusion_strategy": "Z",
        "overall_tone": "T",
    })
    plan = runner._parse_show_plan_response(raw, topic_count=1)
    assert len(plan.topic_bridges) == 1
    assert plan.topic_bridges[0].transition_hint == "valid"


# ---------------------------------------------------------------------------
# SegmentGenerator: show_plan_hint injection (defensive)
# ---------------------------------------------------------------------------

def test_intro_prompt_without_hint_is_backward_compatible(mock_app_config):
    """show_plan_hint=None must produce exactly the legacy prompt (no extra section)."""
    from services.script_generation.segment_generator import SegmentGenerator

    mock_port = MagicMock()
    mock_app_config.yaml.script_generator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.two_phase_generation = False
    mock_app_config.yaml.script_generator.orchestrator.intro = MagicMock(min_turns=10, max_turns=20)
    mock_app_config.yaml.script_generator.orchestrator.deep_dive = MagicMock(min_turns=25, max_turns=45)
    mock_app_config.yaml.script_generator.orchestrator.conclusion = MagicMock(min_turns=10, max_turns=20)
    mock_app_config.yaml.script_generator.orchestrator.json_model = ""
    mock_app_config.yaml.script_generator.orchestrator.segment_model = ""

    gen = SegmentGenerator(mock_port, mock_app_config)
    legacy = gen._build_intro_user_prompt("theme", ["A", "B"], "", hook_fact=None, show_plan_hint=None)
    assert "番組構成ヒント" not in legacy

    with_hint = gen._build_intro_user_prompt(
        "theme", ["A", "B"], "", hook_fact=None, show_plan_hint="【ヒント】テスト"
    )
    assert "番組構成ヒント" in with_hint
    assert "テスト" in with_hint


# ---------------------------------------------------------------------------
# Orchestrator hint builders - backward compat with None ShowPlan
# ---------------------------------------------------------------------------

def test_orchestrator_hint_builders_return_none_for_none_plan():
    """When ShowPlan is None, all _build_*_hint must return None so SegmentGenerator
    falls back to legacy behavior without any extra prompt section."""
    from services.script_generation.orchestrator import ScriptOrchestrator

    # We bypass __init__ to avoid wiring the full context; only unbound methods needed.
    assert ScriptOrchestrator._build_intro_hint(None, None) is None
    assert ScriptOrchestrator._build_deep_dive_hint(None, None, topic_index=0) is None
    assert ScriptOrchestrator._build_conclusion_hint(None, None, topic_count=3) is None


def test_orchestrator_hint_builders_produce_content_for_real_plan():
    from services.script_generation.orchestrator import ScriptOrchestrator

    plan = _make_sample_show_plan()
    intro_hint = ScriptOrchestrator._build_intro_hint(None, plan)
    assert intro_hint is not None
    assert "番組全体アーク" in intro_hint
    assert "導入フック戦略" in intro_hint

    dd_hint = ScriptOrchestrator._build_deep_dive_hint(None, plan, topic_index=0)
    assert dd_hint is not None
    assert "導入からの接続意図" in dd_hint

    conc_hint = ScriptOrchestrator._build_conclusion_hint(None, plan, topic_count=2)
    assert conc_hint is not None
    assert "締め戦略" in conc_hint


# ---------------------------------------------------------------------------
# SessionManager save/load/has ShowPlan
# ---------------------------------------------------------------------------

def test_session_manager_show_plan_roundtrip(tmp_path: Path):
    from core.session_manager import SessionManager

    sm = SessionManager(project_root=tmp_path, session_id="testsess")
    # Ensure session_dir exists
    sm.session_dir.mkdir(parents=True, exist_ok=True)

    assert sm.has_show_plan() is False

    plan = _make_sample_show_plan()
    saved = sm.save_show_plan(plan)
    assert saved.exists()
    assert sm.has_show_plan() is True

    loaded = sm.load_show_plan()
    assert loaded.overall_arc == plan.overall_arc
    assert len(loaded.topic_bridges) == 3

    status = sm.get_session_status()
    assert status["show_plan_completed"] is True


def test_session_manager_load_show_plan_missing_raises(tmp_path: Path):
    from core.session_manager import SessionManager

    sm = SessionManager(project_root=tmp_path, session_id="empty")
    sm.session_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(FileNotFoundError):
        sm.load_show_plan()
