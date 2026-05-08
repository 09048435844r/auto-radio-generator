"""VerifiedScript Pydantic v2 モデルのテスト

Mac 側 SSOT (指示書 §4.3 / Step 1 完了仕様) に整合する Windows 側 view モデルを
担保する。不正な構造は ValidationError で拒否、`references=[]` は正常系として扱う。
"""
import json

import pytest
from pydantic import ValidationError

from core.models.verified_script import (
    Chapter,
    ScriptBody,
    Segment,
    ShowSpec,
    SourceRef,
    Turn,
    VerifiedScript,
    VideoMetadata,
)


# ---------------------------------------------------------------------------
# Helper: 最小限の有効な VerifiedScript 構築
# ---------------------------------------------------------------------------

def _minimal_segment(segment_type: str = "intro", topic_index: int = 0, title: str = "T") -> dict:
    return {
        "segment_type": segment_type,
        "topic_index": topic_index,
        "title": title,
        "turns": [{"speaker": "A", "text": "セリフ"}],
    }


def _minimal_metadata(*, references=None, hashtags=None) -> dict:
    return {
        "title": "テスト動画タイトル",
        "thumbnail_title": "短い見出し",
        "description": "x" * 60,  # 50〜2000 字
        "hashtags": hashtags if hashtags is not None else ["#tag1", "#tag2", "#tag3"],
        "chapters": [
            {"timestamp": "0:00", "title": "イントロ"},
            {"timestamp": "1:00", "title": "本編"},
        ],
        "references": [] if references is None else references,
    }


def _minimal_payload(*, references=None, hashtags=None) -> dict:
    return {
        "script": {
            "show_spec": {"topics": []},
            "segments": [
                _minimal_segment("intro"),
                _minimal_segment("conclusion", topic_index=1, title="まとめ"),
            ],
            "metrics": {},
        },
        "metrics": {},
        "warnings": [],
        "metadata": _minimal_metadata(references=references, hashtags=hashtags),
    }


# ---------------------------------------------------------------------------
# (1) 必須フィールドが揃っていれば valid
# ---------------------------------------------------------------------------

def test_minimal_valid_payload_parses():
    vs = VerifiedScript.model_validate(_minimal_payload())
    assert vs.metadata.title == "テスト動画タイトル"
    assert vs.metadata.thumbnail_title == "短い見出し"
    assert len(vs.script.segments) == 2
    assert vs.script.segments[0].segment_type == "intro"


# ---------------------------------------------------------------------------
# (2) references=[] 正常系 (§4.4 既知制約)
# ---------------------------------------------------------------------------

def test_references_empty_list_is_valid():
    vs = VerifiedScript.model_validate(_minimal_payload(references=[]))
    assert vs.metadata.references == []


def test_references_with_valid_entries_parses():
    refs = [
        {"url": "https://example.com/", "title": "Example", "tier": "AAA"},
        {"url": "https://example.org/path", "title": None, "tier": None},
    ]
    vs = VerifiedScript.model_validate(_minimal_payload(references=refs))
    assert len(vs.metadata.references) == 2
    assert str(vs.metadata.references[0].url) == "https://example.com/"
    assert vs.metadata.references[0].tier == "AAA"


# ---------------------------------------------------------------------------
# (3) thumbnail_title の 15 字制約 (Step 1 確定仕様)
# ---------------------------------------------------------------------------

def test_thumbnail_title_max_15_chars():
    payload = _minimal_payload()
    payload["metadata"]["thumbnail_title"] = "x" * 16  # 16 字 → NG
    with pytest.raises(ValidationError, match="thumbnail_title"):
        VerifiedScript.model_validate(payload)


def test_thumbnail_title_exactly_15_chars_is_valid():
    payload = _minimal_payload()
    payload["metadata"]["thumbnail_title"] = "x" * 15  # 15 字 → OK
    vs = VerifiedScript.model_validate(payload)
    assert len(vs.metadata.thumbnail_title) == 15


# ---------------------------------------------------------------------------
# (4) description の 50〜2000 字制約
# ---------------------------------------------------------------------------

def test_description_too_short_rejected():
    payload = _minimal_payload()
    payload["metadata"]["description"] = "x" * 49  # 49 字 → NG
    with pytest.raises(ValidationError, match="description"):
        VerifiedScript.model_validate(payload)


def test_description_too_long_rejected():
    payload = _minimal_payload()
    payload["metadata"]["description"] = "x" * 2001  # 2001 字 → NG
    with pytest.raises(ValidationError, match="description"):
        VerifiedScript.model_validate(payload)


# ---------------------------------------------------------------------------
# (5) hashtags の 3〜15 件制約
# ---------------------------------------------------------------------------

def test_hashtags_too_few_rejected():
    payload = _minimal_payload(hashtags=["#a", "#b"])  # 2 件 → NG
    with pytest.raises(ValidationError, match="hashtags"):
        VerifiedScript.model_validate(payload)


def test_hashtags_too_many_rejected():
    payload = _minimal_payload(hashtags=[f"#h{i}" for i in range(16)])  # 16 件 → NG
    with pytest.raises(ValidationError, match="hashtags"):
        VerifiedScript.model_validate(payload)


# ---------------------------------------------------------------------------
# (6) segment_type の Literal 制約
# ---------------------------------------------------------------------------

def test_unknown_segment_type_rejected():
    payload = _minimal_payload()
    payload["script"]["segments"][0]["segment_type"] = "bonus"  # NG: 未定義
    with pytest.raises(ValidationError, match="segment_type"):
        VerifiedScript.model_validate(payload)


# ---------------------------------------------------------------------------
# (7) 破損 JSON / model_validate_json 経路
# ---------------------------------------------------------------------------

def test_model_validate_json_with_valid_text():
    text = json.dumps(_minimal_payload(), ensure_ascii=False)
    vs = VerifiedScript.model_validate_json(text)
    assert isinstance(vs, VerifiedScript)


def test_model_validate_json_rejects_corrupt_text():
    with pytest.raises(ValidationError):
        VerifiedScript.model_validate_json('{"script": "not an object"}')


# ---------------------------------------------------------------------------
# (8) chapters は 2 件以上必須
# ---------------------------------------------------------------------------

def test_chapters_minimum_two_required():
    payload = _minimal_payload()
    payload["metadata"]["chapters"] = [{"timestamp": "0:00", "title": "唯一"}]
    with pytest.raises(ValidationError, match="chapters"):
        VerifiedScript.model_validate(payload)


# ---------------------------------------------------------------------------
# (9) Turn / Segment の最小制約
# ---------------------------------------------------------------------------

def test_segment_with_zero_turns_rejected():
    payload = _minimal_payload()
    payload["script"]["segments"][0]["turns"] = []
    with pytest.raises(ValidationError, match="turns"):
        VerifiedScript.model_validate(payload)


def test_turn_speaker_must_be_a_or_b():
    payload = _minimal_payload()
    payload["script"]["segments"][0]["turns"][0]["speaker"] = "C"
    with pytest.raises(ValidationError, match="speaker"):
        VerifiedScript.model_validate(payload)
