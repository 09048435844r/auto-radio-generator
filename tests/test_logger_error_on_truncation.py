"""PR-F: PR-C と PR-D の連携漏れ修正の回帰テスト。

PR-D で 6 エージェント（topic_curator / show_runner / segment_generator×3 /
metadata_generator）の `finish_reason=length` 時に logger.warning を削除して
RuntimeError raise のみにした結果、PR-C の processing_log.txt 収集が捕捉対象を
失っていた問題に対処。

PR-F では各 fail-fast 路で `logger.error(msg)` を `raise RuntimeError(msg)` の
直前に呼び出すように改修。本ファイルは「全 6 箇所で truncation 時に
`logger.error` が確実に呼ばれること」を caplog で assert する。

加えて scripting_phase.py の MetadataGenerator catch / Visual identity catch にも
`logger.error(..., exc_info=True)` を追加した（PR-D の RuntimeError を rich console
経由で吸収していた cb.log 単独の構造を補強）。
"""
import json
import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.models.usage import LLMUsage


# ---------------------------------------------------------------------------
# Helpers (test_max_tokens_unification.py と同じパターン)
# ---------------------------------------------------------------------------

class _FakeLLMResponse:
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


def _inject_orchestrator_cfg(mock_app_config) -> None:
    mock_app_config.yaml.script_generator = MagicMock()
    orch = mock_app_config.yaml.script_generator.orchestrator = MagicMock()
    orch.curator_model = "gemini-2.5-flash"
    orch.max_topics = 3
    orch.segment_model = ""
    orch.json_model = ""
    orch.two_phase_generation = False
    orch.intro = MagicMock(min_turns=10, max_turns=20)
    orch.deep_dive = MagicMock(min_turns=25, max_turns=45)
    orch.conclusion = MagicMock(min_turns=10, max_turns=20)
    orch.topic_curator = MagicMock(max_tokens=8192)
    orch.show_runner = MagicMock(enabled=True, model="", max_tokens=4096)
    orch.fact_extractor = MagicMock(enabled=True, model="", max_facts=30, max_tokens=8192)
    orch.segment_generator = MagicMock(
        max_tokens_single=8192, max_tokens_phase1=4096, max_tokens_phase2=2048,
    )
    orch.metadata_generator = MagicMock(max_tokens=8192)


def _make_curation_result_for_sr():
    from core.models.curation import CuratedTopic, CurationResult
    return CurationResult(
        topics=[CuratedTopic(
            title="T", content="c" * 50, priority=1, estimated_turns=30,
            tone="解説", key_facts=["f"], selection_reason="r",
        )],
        curator_reasoning="ok",
    )


# ---------------------------------------------------------------------------
# Each agent: logger.error が finish_reason=length 時に呼ばれることを assert
# ---------------------------------------------------------------------------

def test_topic_curator_logs_error_on_length_truncation(mock_app_config, caplog):
    import asyncio
    _inject_orchestrator_cfg(mock_app_config)
    from services.script_generation.topic_curator import TopicCurator

    port = MagicMock()
    port.provider_name = "gemini"
    curator = TopicCurator(port, mock_app_config)

    async def mock_generate(req):
        return _FakeLLMResponse('{"topics":[', _fake_usage(), "length")

    port.generate = mock_generate

    rd = MagicMock(mode="trivia", content="dummy")
    with caplog.at_level(logging.ERROR, logger="services.script_generation.topic_curator"):
        with pytest.raises(RuntimeError, match="finish_reason=length"):
            asyncio.run(curator.curate_topics(rd))

    # PR-F: logger.error が呼ばれた証跡
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("finish_reason=length" in r.getMessage() for r in error_records), \
        "TopicCurator は truncation 時に logger.error を呼ぶべき"


def test_show_runner_logs_error_on_length_truncation(mock_app_config, caplog):
    import asyncio
    _inject_orchestrator_cfg(mock_app_config)
    from services.script_generation.show_runner import ShowRunner

    port = MagicMock()
    port.provider_name = "gemini"
    runner = ShowRunner(port, mock_app_config)

    async def mock_generate(req):
        return _FakeLLMResponse('{"overall_arc":', _fake_usage(), "length")

    port.generate = mock_generate

    with caplog.at_level(logging.ERROR, logger="services.script_generation.show_runner"):
        with pytest.raises(RuntimeError, match="finish_reason=length"):
            asyncio.run(runner.plan_show(theme="t", curation_result=_make_curation_result_for_sr()))

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("ShowRunner" in r.getMessage() and "finish_reason=length" in r.getMessage()
               for r in error_records), "ShowRunner は truncation 時に logger.error を呼ぶべき"


def test_segment_generator_single_phase_logs_error_on_length(mock_app_config, caplog):
    import asyncio
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

    with caplog.at_level(logging.ERROR, logger="services.script_generation.segment_generator"):
        with pytest.raises(RuntimeError, match="finish_reason=length"):
            asyncio.run(gen._call_api("sys", "user"))

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("1-phase JSON" in r.getMessage() for r in error_records), \
        "SegmentGenerator 1-phase は truncation 時に logger.error を呼ぶべき"


def test_segment_generator_phase1_logs_error_on_length(mock_app_config, caplog):
    import asyncio
    _inject_orchestrator_cfg(mock_app_config)
    from services.script_generation.segment_generator import SegmentGenerator

    port = MagicMock()
    port.provider_name = "gemini"
    port.model_name = "m"
    gen = SegmentGenerator(port, mock_app_config)

    async def mock_generate(req):
        return _FakeLLMResponse("## 途切れた", _fake_usage(), "length")

    port.generate = mock_generate

    with caplog.at_level(logging.ERROR, logger="services.script_generation.segment_generator"):
        with pytest.raises(RuntimeError, match="finish_reason=length"):
            asyncio.run(gen._generate_creative_markdown(
                segment_type="intro", user_prompt="user", min_turns=10, max_turns=20,
            ))

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("Phase 1" in r.getMessage() for r in error_records), \
        "SegmentGenerator Phase 1 は truncation 時に logger.error を呼ぶべき"


def test_segment_generator_phase2_logs_error_on_length(mock_app_config, caplog):
    import asyncio
    _inject_orchestrator_cfg(mock_app_config)
    from services.script_generation.segment_generator import SegmentGenerator

    port = MagicMock()
    port.provider_name = "gemini"
    port.model_name = "m"
    gen = SegmentGenerator(port, mock_app_config)

    async def mock_generate(req):
        return _FakeLLMResponse('{"partial":', _fake_usage(), "length")

    port.generate = mock_generate

    with caplog.at_level(logging.ERROR, logger="services.script_generation.segment_generator"):
        with pytest.raises(RuntimeError, match="finish_reason=length"):
            asyncio.run(gen._convert_markdown_to_json("dummy", "intro"))

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("Phase 2" in r.getMessage() for r in error_records), \
        "SegmentGenerator Phase 2 は truncation 時に logger.error を呼ぶべき"


def test_metadata_generator_logs_error_on_length_truncation(mock_app_config, caplog):
    import asyncio
    _inject_orchestrator_cfg(mock_app_config)
    from services.script_generation.metadata_generator import MetadataGenerator

    port = MagicMock()
    port.provider_name = "gemini"
    port.model_name = "m"
    gen = MetadataGenerator(port, mock_app_config)

    async def mock_generate(req):
        return _FakeLLMResponse('{"title":"切れ', _fake_usage(), "length")

    port.generate = mock_generate

    with caplog.at_level(logging.ERROR, logger="services.script_generation.metadata_generator"):
        with pytest.raises(RuntimeError, match="finish_reason=length"):
            asyncio.run(gen._call_api("test prompt"))

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("MetadataGenerator" in r.getMessage() and "finish_reason=length" in r.getMessage()
               for r in error_records), "MetadataGenerator は truncation 時に logger.error を呼ぶべき"


# ---------------------------------------------------------------------------
# logger.error の文言が RuntimeError の文言と完全一致することを担保
# （SSOT: 同じ msg 変数を logger.error と raise の両方に渡している）
# ---------------------------------------------------------------------------

def test_logger_error_message_matches_runtime_error_for_metadata_generator(mock_app_config, caplog):
    """logger.error の発火文言と RuntimeError 例外文言が完全一致することを確認。

    PR-F の実装は `msg = (...); logger.error(msg); raise RuntimeError(msg)` の形で、
    両者が同一文字列を参照する設計。リファクタ等で片方だけ変わるリグレッションを防ぐ。
    """
    import asyncio
    _inject_orchestrator_cfg(mock_app_config)
    from services.script_generation.metadata_generator import MetadataGenerator

    port = MagicMock()
    port.provider_name = "gemini"
    port.model_name = "m"
    gen = MetadataGenerator(port, mock_app_config)

    async def mock_generate(req):
        return _FakeLLMResponse('{"x":', _fake_usage(), "length")

    port.generate = mock_generate

    with caplog.at_level(logging.ERROR, logger="services.script_generation.metadata_generator"):
        try:
            asyncio.run(gen._call_api("test"))
        except RuntimeError as e:
            runtime_msg = str(e)
        else:
            pytest.fail("RuntimeError should have been raised")

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    logger_msgs = [r.getMessage() for r in error_records]
    assert runtime_msg in logger_msgs, \
        f"logger.error と RuntimeError の文言が乖離。logger={logger_msgs} runtime={runtime_msg!r}"
