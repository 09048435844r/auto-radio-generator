"""CurationResult non-empty topics validator tests (Phase 4 review #4).

This is a BREAKING CHANGE: empty `topics` lists on `CurationResult` now raise
ValidationError at construction / JSON-load time. Previously the orchestrator
fell through silently to running Curator when `preset_curation.topics` was empty,
hiding broken state. The model-level validator makes the contract explicit.
"""
import pytest
from pydantic import ValidationError

from core.models.curation import CuratedTopic, CurationResult


def _make_one_topic() -> CuratedTopic:
    return CuratedTopic(
        title="テストトピック",
        content="これはテスト用のトピックです。最低限の妥当な内容を持つ。",
        priority=1,
        estimated_turns=30,
        tone="解説",
        key_facts=["ファクト1"],
        selection_reason="テスト選定理由",
    )


# ---------------------------------------------------------------------------
# Positive path: at least one topic accepted
# ---------------------------------------------------------------------------

def test_curation_result_accepts_single_topic():
    """Phase 4 review #4: topics が 1 件でもあれば構築成功。"""
    result = CurationResult(topics=[_make_one_topic()])
    assert len(result.topics) == 1


def test_curation_result_accepts_multiple_topics():
    result = CurationResult(
        topics=[_make_one_topic(), _make_one_topic(), _make_one_topic()],
        curator_reasoning="テスト用の複数トピック",
    )
    assert len(result.topics) == 3


def test_curation_result_roundtrip_json_with_topics():
    """Non-empty topics round-trips through model_dump_json / model_validate_json."""
    original = CurationResult(topics=[_make_one_topic()])
    blob = original.model_dump_json()
    restored = CurationResult.model_validate_json(blob)
    assert len(restored.topics) == 1
    assert restored.topics[0].title == "テストトピック"


# ---------------------------------------------------------------------------
# Negative path: empty topics rejected
# ---------------------------------------------------------------------------

def test_curation_result_rejects_empty_topics_on_construction():
    """Phase 4 review #4: 空の topics は ValidationError。"""
    with pytest.raises(ValidationError) as exc_info:
        CurationResult(topics=[])

    # Error message must clearly identify the offending field
    err_text = str(exc_info.value)
    assert "topics" in err_text
    # Our custom message mentions "at least one topic" to make the contract explicit
    assert "at least one" in err_text.lower() or "empty list" in err_text.lower()


def test_curation_result_rejects_empty_topics_on_json_load():
    """壊れた curation_result.json (topics=[]) をロード時に ValidationError で弾く。

    これは PR-B の破壊的変更の核: 既存セッションで topics=[] の壊れた JSON が
    あれば、load 時に早期検知される。sial fallthrough は起きない。
    """
    broken_json = '{"topics": [], "curator_reasoning": "broken preset"}'
    with pytest.raises(ValidationError) as exc_info:
        CurationResult.model_validate_json(broken_json)
    assert "topics" in str(exc_info.value)


def test_curation_result_rejects_missing_topics_field():
    """topics フィールド自体が欠けていても ValidationError（既存の ... 必須性）。"""
    with pytest.raises(ValidationError):
        CurationResult.model_validate({"curator_reasoning": "no topics key"})
