"""OllamaAdapter thinking-mode fallback 回帰テスト

qwen3:32b など thinking mode を持つローカルモデルは、本文を
`message.content` ではなく `message.reasoning_content` または OpenAI SDK の
`model_extra` 経由で返してくるケースがある。content=None を素のまま
下流に流すと MetadataGenerator が `'NoneType' object is not subscriptable`
で落ちる本運用バグの実績があったため、Adapter 側でフォールバック取得する。

このテストは以下を担保する:
- content が文字列なら従来通りそのまま返る（回帰防止）
- content=None でも reasoning_content に値があれば本文として採用される
- content=None かつ reasoning_content が無く model_extra に thinking 系の
  キーがある場合もフォールバックされる
- 全フォールバックが無効な場合は従来通り LLMResponseError が出る
- フォールバック発動時には warning ログが残る
"""
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.interfaces.llm_port import LLMRequest, LLMResponseError
from services.script_generation.adapters.ollama_adapter import OllamaAdapter


_LOGGER_NAME = "services.script_generation.adapters.ollama_adapter"


def _make_request() -> LLMRequest:
    return LLMRequest(
        system_prompt="sys",
        user_prompt="hello",
        model="qwen3:32b",
        max_tokens=512,
        temperature=0.6,
        response_format=None,
    )


def _make_openai_response(
    *,
    content,
    reasoning_content=None,
    model_extra=None,
    finish_reason: str = "stop",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
) -> MagicMock:
    """OpenAI SDK の ChatCompletion レスポンス互換 MagicMock を組む"""
    message = MagicMock()
    message.content = content
    # MagicMock は未定義属性も MagicMock を返してしまうため、明示的に値を入れる。
    message.reasoning_content = reasoning_content
    message.model_extra = model_extra  # dict or None

    choice = MagicMock()
    choice.message = message
    choice.finish_reason = finish_reason

    response = MagicMock()
    response.choices = [choice]
    response.usage = MagicMock()
    response.usage.prompt_tokens = prompt_tokens
    response.usage.completion_tokens = completion_tokens
    return response


def _make_adapter(openai_response) -> OllamaAdapter:
    adapter = OllamaAdapter(
        base_url="http://test.invalid:11435/v1",
        default_model="qwen3:32b",
    )
    adapter._client.chat.completions.create = AsyncMock(return_value=openai_response)
    return adapter


# ---------------------------------------------------------------------------
# (1) 既存挙動: content が文字列ならそのまま返る（回帰防止）
# ---------------------------------------------------------------------------

def test_normal_content_passes_through_unchanged(caplog):
    response = _make_openai_response(content='{"ok": true}')
    adapter = _make_adapter(response)

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        result = asyncio.run(adapter.generate(_make_request()))

    assert result.content == '{"ok": true}'
    assert result.finish_reason == "stop"
    fallback_warnings = [r for r in caplog.records if "falling back" in r.getMessage()]
    assert fallback_warnings == []


# ---------------------------------------------------------------------------
# (2) thinking-mode フォールバック: reasoning_content
# ---------------------------------------------------------------------------

def test_falls_back_to_reasoning_content_when_content_is_none(caplog):
    """qwen3:32b の thinking mode で content=None / reasoning_content にメイン本文。"""
    main_text = '{"title": "テスト", "thumbnail_title": "t", "description": "d", "hashtags": []}'
    response = _make_openai_response(
        content=None,
        reasoning_content=main_text,
    )
    adapter = _make_adapter(response)

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        result = asyncio.run(adapter.generate(_make_request()))

    assert result.content == main_text, (
        "content=None の際は reasoning_content をフォールバック採用すべき"
    )
    msgs = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("falling back to message.reasoning_content" in m for m in msgs), msgs


# ---------------------------------------------------------------------------
# (3) model_extra 経由のフォールバック
# ---------------------------------------------------------------------------

def test_falls_back_to_model_extra_thinking_when_no_reasoning_content(caplog):
    """reasoning_content が無くても model_extra['thinking'] があれば採用。"""
    main_text = '{"title": "別経路"}'
    response = _make_openai_response(
        content=None,
        reasoning_content=None,
        model_extra={"thinking": main_text},
    )
    adapter = _make_adapter(response)

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        result = asyncio.run(adapter.generate(_make_request()))

    assert result.content == main_text
    msgs = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("model_extra['thinking']" in m for m in msgs), msgs


def test_model_extra_reasoning_content_key_is_searched():
    """model_extra に 'reasoning_content' キーが入っているケースもカバーする。"""
    main_text = '{"a": 1}'
    response = _make_openai_response(
        content=None,
        reasoning_content=None,
        model_extra={"reasoning_content": main_text},
    )
    adapter = _make_adapter(response)

    result = asyncio.run(adapter.generate(_make_request()))
    assert result.content == main_text


# ---------------------------------------------------------------------------
# (4) 優先順位: reasoning_content の方が model_extra より優先される
# ---------------------------------------------------------------------------

def test_reasoning_content_takes_priority_over_model_extra():
    response = _make_openai_response(
        content=None,
        reasoning_content="from reasoning_content",
        model_extra={"reasoning_content": "from model_extra", "thinking": "from thinking"},
    )
    adapter = _make_adapter(response)

    result = asyncio.run(adapter.generate(_make_request()))
    assert result.content == "from reasoning_content", (
        "公式フィールド reasoning_content が model_extra より優先されるべき"
    )


# ---------------------------------------------------------------------------
# (5) フォールバックが全部空: 従来通り LLMResponseError
# ---------------------------------------------------------------------------

def test_raises_when_content_and_all_fallbacks_are_empty():
    response = _make_openai_response(
        content=None,
        reasoning_content=None,
        model_extra=None,
    )
    adapter = _make_adapter(response)

    with pytest.raises(LLMResponseError):
        asyncio.run(adapter.generate(_make_request()))


def test_whitespace_only_fallback_does_not_count_as_valid():
    """空白のみの reasoning_content はフォールバック値として採用しない。"""
    response = _make_openai_response(
        content=None,
        reasoning_content="   \n\t  ",
        model_extra=None,
    )
    adapter = _make_adapter(response)

    with pytest.raises(LLMResponseError):
        asyncio.run(adapter.generate(_make_request()))


# ---------------------------------------------------------------------------
# (6) 既存の空文字列ガード（content="" もフォールバック対象外、エラー）
# ---------------------------------------------------------------------------

def test_empty_string_content_still_raises_without_fallback_attempt():
    """content が空文字列（None ではない）の場合は thinking-mode 症状ではないため
    既存の空応答エラーを維持する（フォールバックを試みない）。"""
    response = _make_openai_response(
        content="",
        reasoning_content="should not be used",
    )
    adapter = _make_adapter(response)

    with pytest.raises(LLMResponseError):
        asyncio.run(adapter.generate(_make_request()))
