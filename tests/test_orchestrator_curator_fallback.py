"""PR-H: ScriptOrchestrator の TopicCurator 失敗時フェイルオープンテスト。

PR-B で導入した CurationResult.topics 非空 validator が、Curator 実行失敗
（qwen3:8b 等の小型モデルが空 topics を返したケース）で raise した結果、
orchestrator が catch できず、パイプライン全体がクラッシュしていた本運用バグへの
修正を検証する。

PR-H では try/except でラップし、`_build_fallback_curation_for_failure` という
helper メソッドにフォールバック CurationResult 構築ロジックを切り出した。
本ファイルは helper の単体テスト + 統合的な契約検証を行う。
"""
import logging
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from core.models.curation import CuratedTopic, CurationResult


# ---------------------------------------------------------------------------
# Helper: 軽量な ScriptOrchestrator インスタンス作成
# ---------------------------------------------------------------------------

def _make_test_orchestrator():
    """`__new__` で `__init__` をバイパスし、helper メソッド直接テストに必要な属性のみ設定。

    `_build_fallback_curation_for_failure` は self の属性を一切参照せず純粋関数的なので、
    ScriptOrchestrator の重い依存（ExecutionContext / 各エージェント）は一切不要。
    """
    from services.script_generation.orchestrator import ScriptOrchestrator
    return ScriptOrchestrator.__new__(ScriptOrchestrator)


# ---------------------------------------------------------------------------
# (1) PR-B の validator が空 topics で raise することを再確認（前提）
# ---------------------------------------------------------------------------

def test_curation_result_validator_raises_on_empty_topics():
    """PR-B 由来: 空 topics で CurationResult を構築すると ValidationError。

    PR-H が解決する元の問題の再現。これは fix されてはいけない validator の挙動。
    """
    with pytest.raises(ValidationError):
        CurationResult(topics=[])


# ---------------------------------------------------------------------------
# (2) _build_fallback_curation_for_failure: 例外種別ごとの動作
# ---------------------------------------------------------------------------

def test_fallback_handles_pydantic_validation_error(caplog):
    """ValidationError (PR-B 契約違反) を catch して valid な CurationResult を返す。"""
    orch = _make_test_orchestrator()

    # 実物の ValidationError を取得（CurationResult(topics=[]) の構築失敗から）
    try:
        CurationResult(topics=[])
    except ValidationError as ve:
        validation_error = ve

    log_messages = []
    def log_fn(msg):
        log_messages.append(msg)

    with caplog.at_level(logging.ERROR, logger="services.script_generation.orchestrator"):
        result = orch._build_fallback_curation_for_failure(validation_error, log_fn)

    # 返り値が PR-B の validator を通る valid な CurationResult
    assert isinstance(result, CurationResult)
    assert len(result.topics) == 1, "PR-B 非空契約を満たすべき"
    assert result.topics[0].title.startswith("（自動生成失敗")

    # logger.error が呼ばれた（PR-C/F 経由で processing_log.txt に残る）
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("TopicCurator failed" in r.getMessage() for r in error_records), \
        "logger.error が呼ばれて PR-C 経由で processing_log.txt に残るべき"
    assert any("ValidationError" in r.getMessage() for r in error_records), \
        "error_type が ValidationError として記録されるべき"

    # rich console 経由（cb.log）にもメッセージが届く
    assert any("TopicCurator 失敗" in m for m in log_messages)
    assert any("ValidationError" in m for m in log_messages)


def test_fallback_handles_runtime_error(caplog):
    """RuntimeError (PR-D fail-fast 系) でも同様にフォールバックする。"""
    orch = _make_test_orchestrator()
    runtime_error = RuntimeError(
        "TopicCurator output was truncated (finish_reason=length). Current max_tokens=8192."
    )

    with caplog.at_level(logging.ERROR, logger="services.script_generation.orchestrator"):
        result = orch._build_fallback_curation_for_failure(runtime_error, lambda msg: None)

    assert isinstance(result, CurationResult)
    assert len(result.topics) == 1

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("RuntimeError" in r.getMessage() for r in error_records)
    assert any("finish_reason=length" in r.getMessage() for r in error_records)


def test_fallback_handles_arbitrary_exception(caplog):
    """予期せぬ例外（ValueError など）でも安全にフォールバックする。"""
    orch = _make_test_orchestrator()
    unknown_error = ValueError("some unexpected error from LLM port")

    with caplog.at_level(logging.ERROR, logger="services.script_generation.orchestrator"):
        result = orch._build_fallback_curation_for_failure(unknown_error, lambda msg: None)

    assert isinstance(result, CurationResult)
    assert len(result.topics) == 1


# ---------------------------------------------------------------------------
# (3) Fallback topic の構造的妥当性: SegmentGenerator が期待する最小限を満たすか
# ---------------------------------------------------------------------------

def test_fallback_topic_has_minimum_viable_fields():
    """fallback topic が SegmentGenerator の generate_deep_dive が読む必須フィールドを持つ。"""
    orch = _make_test_orchestrator()
    result = orch._build_fallback_curation_for_failure(
        RuntimeError("test"), lambda msg: None
    )

    topic = result.topics[0]
    assert topic.title  # 非空
    assert topic.content  # 非空
    assert topic.priority >= 1
    assert topic.estimated_turns >= 1
    assert topic.tone in ("驚き", "議論", "解説", "感動", "笑い"), \
        f"tone は CuratedTopic の許容値の 1 つであるべき (got: {topic.tone!r})"
    assert isinstance(topic.key_facts, list)
    assert topic.selection_reason  # 非空（下流 SegmentGenerator が読む）


def test_fallback_topic_title_signals_failure_to_viewer():
    """fallback topic のタイトルは「失敗だったとわかる文言」であるべき（透明性）。"""
    orch = _make_test_orchestrator()
    result = orch._build_fallback_curation_for_failure(
        RuntimeError("test"), lambda msg: None
    )

    topic = result.topics[0]
    # 視聴者から見ても「自動生成失敗のフォールバック」と分かる
    assert "失敗" in topic.title or "フォールバック" in topic.title


def test_fallback_curator_reasoning_includes_error_info():
    """curator_reasoning に元の例外情報が記録される（後追い debug 用）。"""
    orch = _make_test_orchestrator()
    test_error = RuntimeError("specific test error message 12345")
    result = orch._build_fallback_curation_for_failure(test_error, lambda msg: None)

    assert "TopicCurator failed" in result.curator_reasoning
    assert "RuntimeError" in result.curator_reasoning
    assert "specific test error message 12345" in result.curator_reasoning


# ---------------------------------------------------------------------------
# (4) 結果の CurationResult が round-trip しても valid（永続化での問題なし）
# ---------------------------------------------------------------------------

def test_fallback_curation_result_roundtrips_through_json():
    """fallback CurationResult が JSON シリアライズ→デシリアライズしても valid。

    SessionManager.save_curation_result / load_curation_result 経路で問題ないことを担保。
    """
    orch = _make_test_orchestrator()
    result = orch._build_fallback_curation_for_failure(
        ValueError("test"), lambda msg: None
    )

    blob = result.model_dump_json()
    restored = CurationResult.model_validate_json(blob)
    assert len(restored.topics) == 1
    assert restored.topics[0].title == result.topics[0].title


# ---------------------------------------------------------------------------
# (5) 構造的回帰: orchestrator.generate_script の Step 1 が try/except を持つこと
# ---------------------------------------------------------------------------

def test_orchestrator_generate_script_wraps_curator_in_try_except():
    """orchestrator.py の generate_script に Curator の try/except + フォールバック呼び出しが
    存在することを静的に確認（将来のリファクタで PR-H の修正が消えるリグレッション防止）。
    """
    from pathlib import Path
    src = Path(
        "E:/windsurf/auto_radio_generator/services/script_generation/orchestrator.py"
    ).read_text(encoding="utf-8")

    # try/except で curate_topics を囲んでいる
    assert "await self.curate_topics(" in src
    assert "_build_fallback_curation_for_failure" in src
    # except Exception で広く catch している（ValidationError も RuntimeError もカバー）
    assert "except Exception as e:" in src
