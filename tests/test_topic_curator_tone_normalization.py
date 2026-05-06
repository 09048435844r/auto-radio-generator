"""TopicCurator._normalize_tone / _parse_curation_response の tone 正規化テスト

Qwen3.5-122B 等が tone フィールドを文字列ではなくリスト
（例: ['驚き', ['議論'], ['解説']]）で返すと Pydantic ValidationError でパイプラインが
フォールバックトピックに落ちる本運用バグへの回帰テスト。

担保する内容:
  - 文字列 tone はそのまま採用
  - 単純リスト ["驚き"] は最初の要素を取り出す
  - ネストリスト [["議論"]] / ["驚き", ["議論"]] も再帰的にフラット化
  - None / 空 / 空白のみは "解説" デフォルトにフォールバック
  - 統合: _parse_curation_response がリスト tone の混在 JSON を ValidationError なく処理
"""
import json
from unittest.mock import MagicMock

import pytest

from services.script_generation.topic_curator import TopicCurator


# ---------------------------------------------------------------------------
# _normalize_tone: 純粋関数の単体テスト（インスタンスを介さず staticmethod として呼ぶ）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("驚き", "驚き"),
    ("  議論  ", "議論"),  # 前後空白は trim
    ("解説", "解説"),
])
def test_normalize_tone_plain_string(raw, expected):
    assert TopicCurator._normalize_tone(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    (["驚き"], "驚き"),
    (["議論", "解説"], "議論"),  # 先頭の文字列を採用
    (["驚き", "議論", "解説"], "驚き"),
])
def test_normalize_tone_flat_list(raw, expected):
    assert TopicCurator._normalize_tone(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ([["議論"]], "議論"),
    ([["驚き", "議論"]], "驚き"),
    ([[["解説"]]], "解説"),  # 三重ネスト
    (["驚き", ["議論"]], "驚き"),
    ([["驚き"], ["議論"]], "驚き"),
])
def test_normalize_tone_nested_list(raw, expected):
    assert TopicCurator._normalize_tone(raw) == expected


def test_normalize_tone_real_world_qwen_pattern():
    """実機観測パターン: Qwen3.5-122B が ['驚き', ['議論'], ['解説']] を返したケース"""
    raw = ["驚き", ["議論"], ["解説"]]
    assert TopicCurator._normalize_tone(raw) == "驚き"


@pytest.mark.parametrize("raw", [
    None,
    "",
    "   ",
    [],
    [None],
    [""],
    ["  "],
    [[]],
    [[""], [None]],  # 全部空のネスト
])
def test_normalize_tone_empty_returns_default(raw):
    assert TopicCurator._normalize_tone(raw) == "解説"


@pytest.mark.parametrize("raw, expected", [
    (123, "123"),       # int
    (1.5, "1.5"),       # float
    (True, "True"),     # bool
])
def test_normalize_tone_other_types_str_coerced(raw, expected):
    assert TopicCurator._normalize_tone(raw) == expected


def test_normalize_tone_dict_str_coerced():
    """dict は str() で文字列化される（多くのケースで意味のある文字列にはならないが落ちない）"""
    raw = {"key": "value"}
    result = TopicCurator._normalize_tone(raw)
    # dict は str() で "{'key': 'value'}" のような文字列になる → 非空なので採用される
    assert isinstance(result, str)
    assert len(result) > 0


def test_normalize_tone_list_with_first_empty_then_valid():
    """先頭が空リスト/空文字列でも、後続に有効な文字列があればそれを返す"""
    assert TopicCurator._normalize_tone([[], "驚き"]) == "驚き"
    assert TopicCurator._normalize_tone(["", "  ", "議論"]) == "議論"
    assert TopicCurator._normalize_tone([None, ["解説"]]) == "解説"


# ---------------------------------------------------------------------------
# _parse_curation_response 統合: リスト tone を含む JSON が ValidationError なく処理される
# ---------------------------------------------------------------------------

def _make_curator_for_parse(mock_app_config):
    """LLM port を使わず _parse_curation_response だけテストするための軽量 Curator"""
    mock_port = MagicMock()
    mock_port.provider_name = "ollama"

    mock_app_config.yaml.script_generator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.curator_model = "qwen3.5-122b-a10b"
    mock_app_config.yaml.script_generator.orchestrator.topic_curator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.topic_curator.max_tokens = 12288

    return TopicCurator(mock_port, mock_app_config)


def test_parse_curation_response_handles_list_tone(mock_app_config):
    """tone がリストで来てもValidationError を起こさず CuratedTopic を構築できる"""
    curator = _make_curator_for_parse(mock_app_config)

    payload = json.dumps({
        "topics": [
            {
                "title": "トピック1のタイトル",
                "content": "詳細内容" * 30,
                "priority": 1,
                "estimated_turns": 30,
                "tone": ["驚き"],  # ← LLM がリストで返したケース
                "key_facts": ["ファクト1", "ファクト2"],
                "selection_reason": "選定理由",
            },
        ],
        "curator_reasoning": "デバッグ用",
    })

    result = curator._parse_curation_response(payload)
    assert len(result.topics) == 1
    assert result.topics[0].tone == "驚き"  # 文字列に正規化されている


def test_parse_curation_response_handles_nested_list_tone(mock_app_config):
    """tone がネストリスト [['議論']] でも処理できる"""
    curator = _make_curator_for_parse(mock_app_config)

    payload = json.dumps({
        "topics": [
            {
                "title": "T1",
                "content": "c1",
                "priority": 1,
                "estimated_turns": 30,
                "tone": [["議論"]],
                "key_facts": [],
                "selection_reason": "",
            },
        ],
    })

    result = curator._parse_curation_response(payload)
    assert result.topics[0].tone == "議論"


def test_parse_curation_response_handles_real_world_qwen_pattern(mock_app_config):
    """実機観測: 複数トピックで tone がそれぞれ list / nested list / str の混在"""
    curator = _make_curator_for_parse(mock_app_config)

    payload = json.dumps({
        "topics": [
            {"title": "T1", "content": "c1", "priority": 1, "estimated_turns": 30,
             "tone": ["驚き", ["議論"], ["解説"]], "key_facts": [], "selection_reason": ""},
            {"title": "T2", "content": "c2", "priority": 2, "estimated_turns": 25,
             "tone": ["議論"], "key_facts": [], "selection_reason": ""},
            {"title": "T3", "content": "c3", "priority": 3, "estimated_turns": 20,
             "tone": "解説", "key_facts": [], "selection_reason": ""},  # 正常な文字列ケース
        ],
    })

    result = curator._parse_curation_response(payload)
    assert len(result.topics) == 3
    assert result.topics[0].tone == "驚き"
    assert result.topics[1].tone == "議論"
    assert result.topics[2].tone == "解説"


def test_parse_curation_response_handles_missing_tone_with_default(mock_app_config):
    """tone キー自体が無いトピックは "解説" デフォルトで処理される（既存挙動の維持）"""
    curator = _make_curator_for_parse(mock_app_config)

    payload = json.dumps({
        "topics": [
            {"title": "T1", "content": "c1", "priority": 1, "estimated_turns": 30,
             "key_facts": [], "selection_reason": ""},  # tone なし
        ],
    })

    result = curator._parse_curation_response(payload)
    assert result.topics[0].tone == "解説"


def test_parse_curation_response_handles_empty_list_tone_with_default(mock_app_config):
    """tone=[] は "解説" デフォルトに落ちる"""
    curator = _make_curator_for_parse(mock_app_config)

    payload = json.dumps({
        "topics": [
            {"title": "T1", "content": "c1", "priority": 1, "estimated_turns": 30,
             "tone": [], "key_facts": [], "selection_reason": ""},
        ],
    })

    result = curator._parse_curation_response(payload)
    assert result.topics[0].tone == "解説"
