"""PR-D (Issue C): max_tokens config 駆動化の横展開テスト。

各エージェント（TopicCurator / ShowRunner / SegmentGenerator 3 phases /
MetadataGenerator）について:
  1. config の max_tokens 値が LLMRequest.max_tokens に正しく伝播する
  2. finish_reason == "length" 時に RuntimeError を送出する（PR-A の
     FactExtractor と同一パターンに統一）

FactExtractor 自体は PR-A で既に同パターンが導入済みのため、本ファイルでは
横展開された他 5 モジュールをカバーする（SegmentGenerator は 3 メソッド別に検証）。
"""
import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.models.usage import LLMUsage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeLLMResponse:
    """Minimal stand-in for LLMResponse with controllable finish_reason."""

    def __init__(self, content: str, usage: LLMUsage, finish_reason: str = "stop"):
        self.content = content
        self.usage = usage
        self.finish_reason = finish_reason


def _fake_usage() -> LLMUsage:
    return LLMUsage(
        provider="gemini",
        model_name="test",
        input_tokens=10,
        output_tokens=10,
        request_count=1,
    )


def _valid_topics_json() -> str:
    """TopicCurator / 下流 validator を通す最小限の JSON 応答。"""
    return json.dumps({
        "topics": [
            {
                "title": "ダミートピック",
                "content": "テスト用",
                "priority": 1,
                "estimated_turns": 30,
                "tone": "解説",
                "key_facts": ["fact1"],
                "selection_reason": "テスト",
            }
        ],
        "curator_reasoning": "テスト",
    })


def _valid_show_plan_json() -> str:
    return json.dumps({
        "overall_arc": "A",
        "intro_hook_strategy": "B",
        "topic_bridges": [
            {"from_topic_index": -1, "to_topic_index": 0, "transition_hint": "h"},
        ],
        "conclusion_strategy": "C",
        "overall_tone": "D",
        "planner_reasoning": "E",
    })


def _valid_metadata_json() -> str:
    return json.dumps({
        "title": "テストタイトル",
        "thumbnail_title": "短縮",
        "description": "概要欄テキスト",
        "hashtags": ["A", "B", "C", "D", "E"],
    })


def _valid_segment_json() -> str:
    return json.dumps({
        "segment_id": "intro",
        "segment_type": "intro",
        "topic_title": None,
        "turns": [
            {"speaker": "A", "text": "セリフ1", "section": "intro"},
            {"speaker": "B", "text": "セリフ2"},
        ],
        "context_summary": "テスト要約",
    })


# ---------------------------------------------------------------------------
# Fixture: shared orchestrator config mock
# ---------------------------------------------------------------------------

def _inject_orchestrator_cfg(mock_app_config, **overrides: Any) -> None:
    """Build a MagicMock orchestrator config that supports the expected fields."""
    mock_app_config.yaml.script_generator = MagicMock()
    orch = mock_app_config.yaml.script_generator.orchestrator = MagicMock()

    # Common defaults
    orch.curator_model = "gemini-2.5-flash"
    orch.max_topics = 3
    orch.segment_model = ""
    orch.json_model = ""
    orch.two_phase_generation = False
    orch.intro = MagicMock(min_turns=10, max_turns=20)
    orch.deep_dive = MagicMock(min_turns=25, max_turns=45)
    orch.conclusion = MagicMock(min_turns=10, max_turns=20)

    # Sub-configs
    orch.topic_curator = MagicMock(max_tokens=overrides.get("tc_max_tokens", 8192))
    orch.show_runner = MagicMock(
        enabled=True,
        model="",
        max_tokens=overrides.get("sr_max_tokens", 4096),
    )
    orch.fact_extractor = MagicMock(
        enabled=True, model="", max_facts=30, max_tokens=8192,
    )
    orch.segment_generator = MagicMock(
        max_tokens_single=overrides.get("sg_single", 8192),
        max_tokens_phase1=overrides.get("sg_phase1", 4096),
        max_tokens_phase2=overrides.get("sg_phase2", 2048),
    )
    orch.metadata_generator = MagicMock(max_tokens=overrides.get("mg_max_tokens", 2048))


# ---------------------------------------------------------------------------
# TopicCurator
# ---------------------------------------------------------------------------

def test_topic_curator_max_tokens_from_config(mock_app_config):
    _inject_orchestrator_cfg(mock_app_config, tc_max_tokens=12345)
    from services.script_generation.topic_curator import TopicCurator

    port = MagicMock()
    port.provider_name = "gemini"
    curator = TopicCurator(port, mock_app_config)
    assert curator.max_tokens == 12345

    captured: dict = {}

    async def mock_generate(req):
        captured["max_tokens"] = req.max_tokens
        return _FakeLLMResponse(_valid_topics_json(), _fake_usage(), "stop")

    port.generate = mock_generate

    import asyncio
    rd = MagicMock(mode="trivia", content="リサーチ本文")
    asyncio.run(curator.curate_topics(rd))
    assert captured["max_tokens"] == 12345


def test_topic_curator_raises_on_length_truncation(mock_app_config):
    _inject_orchestrator_cfg(mock_app_config, tc_max_tokens=8192)
    from services.script_generation.topic_curator import TopicCurator

    port = MagicMock()
    port.provider_name = "gemini"
    curator = TopicCurator(port, mock_app_config)

    async def mock_generate(req):
        return _FakeLLMResponse('{"topics":[', _fake_usage(), "length")

    port.generate = mock_generate

    import asyncio
    rd = MagicMock(mode="trivia", content="リサーチ")
    with pytest.raises(RuntimeError, match="finish_reason=length"):
        asyncio.run(curator.curate_topics(rd))


# ---------------------------------------------------------------------------
# ShowRunner
# ---------------------------------------------------------------------------

def _make_curation_result_for_sr():
    from core.models.curation import CuratedTopic, CurationResult
    return CurationResult(
        topics=[CuratedTopic(
            title="T",
            content="c" * 50,
            priority=1,
            estimated_turns=30,
            tone="解説",
            key_facts=["f"],
            selection_reason="r",
        )],
        curator_reasoning="ok",
    )


def test_show_runner_max_tokens_from_config(mock_app_config):
    _inject_orchestrator_cfg(mock_app_config, sr_max_tokens=9999)
    from services.script_generation.show_runner import ShowRunner

    port = MagicMock()
    port.provider_name = "gemini"
    runner = ShowRunner(port, mock_app_config)
    assert runner.max_tokens == 9999

    captured: dict = {}

    async def mock_generate(req):
        captured["max_tokens"] = req.max_tokens
        return _FakeLLMResponse(_valid_show_plan_json(), _fake_usage(), "stop")

    port.generate = mock_generate

    import asyncio
    asyncio.run(runner.plan_show(theme="t", curation_result=_make_curation_result_for_sr()))
    assert captured["max_tokens"] == 9999


def test_show_runner_raises_on_length_truncation(mock_app_config):
    _inject_orchestrator_cfg(mock_app_config, sr_max_tokens=4096)
    from services.script_generation.show_runner import ShowRunner

    port = MagicMock()
    port.provider_name = "gemini"
    runner = ShowRunner(port, mock_app_config)

    async def mock_generate(req):
        return _FakeLLMResponse('{"overall_arc":', _fake_usage(), "length")

    port.generate = mock_generate

    import asyncio
    with pytest.raises(RuntimeError, match="finish_reason=length"):
        asyncio.run(runner.plan_show(theme="t", curation_result=_make_curation_result_for_sr()))


# ---------------------------------------------------------------------------
# SegmentGenerator - 1-phase JSON
# ---------------------------------------------------------------------------

def _make_segment_generator(mock_app_config, *, two_phase: bool = False):
    _inject_orchestrator_cfg(mock_app_config)
    mock_app_config.yaml.script_generator.orchestrator.two_phase_generation = two_phase

    from services.script_generation.segment_generator import SegmentGenerator

    port = MagicMock()
    port.provider_name = "gemini"
    port.model_name = "test-model"
    gen = SegmentGenerator(port, mock_app_config)
    return gen, port


def test_segment_generator_single_phase_max_tokens_from_config(mock_app_config):
    _inject_orchestrator_cfg(mock_app_config, sg_single=7777)
    mock_app_config.yaml.script_generator.orchestrator.two_phase_generation = False
    from services.script_generation.segment_generator import SegmentGenerator

    port = MagicMock()
    port.provider_name = "gemini"
    port.model_name = "m"
    gen = SegmentGenerator(port, mock_app_config)
    assert gen.max_tokens_single == 7777

    captured: dict = {}

    async def mock_generate(req):
        captured["max_tokens"] = req.max_tokens
        return _FakeLLMResponse(_valid_segment_json(), _fake_usage(), "stop")

    port.generate = mock_generate

    import asyncio
    asyncio.run(gen._call_api("sys", "user"))
    assert captured["max_tokens"] == 7777


def test_segment_generator_single_phase_raises_on_length(mock_app_config):
    _inject_orchestrator_cfg(mock_app_config)
    mock_app_config.yaml.script_generator.orchestrator.two_phase_generation = False
    from services.script_generation.segment_generator import SegmentGenerator

    port = MagicMock()
    port.provider_name = "gemini"
    port.model_name = "m"
    gen = SegmentGenerator(port, mock_app_config)

    async def mock_generate(req):
        return _FakeLLMResponse("{partial", _fake_usage(), "length")

    port.generate = mock_generate

    import asyncio
    with pytest.raises(RuntimeError, match="finish_reason=length"):
        asyncio.run(gen._call_api("sys", "user"))


# ---------------------------------------------------------------------------
# SegmentGenerator - Phase 1 (creative markdown)
# ---------------------------------------------------------------------------

def test_segment_generator_phase1_max_tokens_from_config(mock_app_config):
    _inject_orchestrator_cfg(mock_app_config, sg_phase1=3333)
    from services.script_generation.segment_generator import SegmentGenerator

    port = MagicMock()
    port.provider_name = "gemini"
    port.model_name = "m"
    gen = SegmentGenerator(port, mock_app_config)
    assert gen.max_tokens_phase1 == 3333

    captured: dict = {}

    async def mock_generate(req):
        captured["max_tokens"] = req.max_tokens
        return _FakeLLMResponse("## セグメント\nA: セリフ\nB: セリフ\n", _fake_usage(), "stop")

    port.generate = mock_generate

    import asyncio
    asyncio.run(gen._generate_creative_markdown(
        segment_type="intro", user_prompt="user",
        min_turns=10, max_turns=20,
    ))
    assert captured["max_tokens"] == 3333


def test_segment_generator_phase1_raises_on_length(mock_app_config):
    _inject_orchestrator_cfg(mock_app_config)
    from services.script_generation.segment_generator import SegmentGenerator

    port = MagicMock()
    port.provider_name = "gemini"
    port.model_name = "m"
    gen = SegmentGenerator(port, mock_app_config)

    async def mock_generate(req):
        return _FakeLLMResponse("## 途切れた", _fake_usage(), "length")

    port.generate = mock_generate

    import asyncio
    with pytest.raises(RuntimeError, match="finish_reason=length"):
        asyncio.run(gen._generate_creative_markdown(
            segment_type="intro", user_prompt="user",
            min_turns=10, max_turns=20,
        ))


# ---------------------------------------------------------------------------
# SegmentGenerator - Phase 2 (JSON conversion)
# ---------------------------------------------------------------------------

def test_segment_generator_phase2_max_tokens_from_config(mock_app_config):
    _inject_orchestrator_cfg(mock_app_config, sg_phase2=1111)
    from services.script_generation.segment_generator import SegmentGenerator

    port = MagicMock()
    port.provider_name = "gemini"
    port.model_name = "m"
    gen = SegmentGenerator(port, mock_app_config)
    assert gen.max_tokens_phase2 == 1111

    captured: dict = {}

    async def mock_generate(req):
        captured["max_tokens"] = req.max_tokens
        return _FakeLLMResponse(_valid_segment_json(), _fake_usage(), "stop")

    port.generate = mock_generate

    import asyncio
    asyncio.run(gen._convert_markdown_to_json("dummy markdown", "intro"))
    assert captured["max_tokens"] == 1111


def test_segment_generator_phase2_raises_on_length(mock_app_config):
    _inject_orchestrator_cfg(mock_app_config)
    from services.script_generation.segment_generator import SegmentGenerator

    port = MagicMock()
    port.provider_name = "gemini"
    port.model_name = "m"
    gen = SegmentGenerator(port, mock_app_config)

    async def mock_generate(req):
        return _FakeLLMResponse('{"partial":', _fake_usage(), "length")

    port.generate = mock_generate

    import asyncio
    with pytest.raises(RuntimeError, match="finish_reason=length"):
        asyncio.run(gen._convert_markdown_to_json("dummy", "intro"))


# ---------------------------------------------------------------------------
# MetadataGenerator
# ---------------------------------------------------------------------------

def test_metadata_generator_max_tokens_from_config(mock_app_config):
    _inject_orchestrator_cfg(mock_app_config, mg_max_tokens=5555)
    from services.script_generation.metadata_generator import MetadataGenerator

    port = MagicMock()
    port.provider_name = "gemini"
    port.model_name = "m"
    gen = MetadataGenerator(port, mock_app_config)
    assert gen.max_tokens == 5555

    captured: dict = {}

    async def mock_generate(req):
        captured["max_tokens"] = req.max_tokens
        return _FakeLLMResponse(_valid_metadata_json(), _fake_usage(), "stop")

    port.generate = mock_generate

    import asyncio
    asyncio.run(gen._call_api("test prompt"))
    assert captured["max_tokens"] == 5555


def test_metadata_generator_raises_on_length_truncation(mock_app_config):
    _inject_orchestrator_cfg(mock_app_config)
    from services.script_generation.metadata_generator import MetadataGenerator

    port = MagicMock()
    port.provider_name = "gemini"
    port.model_name = "m"
    gen = MetadataGenerator(port, mock_app_config)

    async def mock_generate(req):
        return _FakeLLMResponse('{"title":"切れ', _fake_usage(), "length")

    port.generate = mock_generate

    import asyncio
    with pytest.raises(RuntimeError, match="finish_reason=length"):
        asyncio.run(gen._call_api("test prompt"))
