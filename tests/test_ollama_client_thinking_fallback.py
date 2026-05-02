"""OllamaClient（旧 IScriptGenerator 経路）の thinking-mode フォールバック回帰テスト

OllamaAdapter 側は commit 02af3ae で content=None フォールバックが入ったが、
OllamaClient 側（_generate_youtube_metadata から呼ばれる generate_packaging_prompt
など、Phase 4 後処理経路で消費される旧 client）は対策が漏れていた。
本テストは helper `_extract_content_with_thinking_fallback` の挙動を検証し、
ollama_client.py のフォールバックが OllamaAdapter と挙動一致することを担保する。
"""
import logging
from unittest.mock import MagicMock

import pytest

from services.script_generation.ollama_client import (
    _extract_content_with_thinking_fallback,
)

_LOGGER_NAME = "services.script_generation.ollama_client"


def _make_message(*, content, reasoning_content=None, model_extra=None) -> MagicMock:
    """OpenAI SDK の ChatCompletionMessage 互換 MagicMock。"""
    msg = MagicMock()
    msg.content = content
    msg.reasoning_content = reasoning_content
    msg.model_extra = model_extra
    return msg


# ---------------------------------------------------------------------------
# (1) 既存挙動: content が文字列ならそのまま返る
# ---------------------------------------------------------------------------

def test_returns_content_unchanged_when_present(caplog):
    msg = _make_message(content='{"ok": true}', reasoning_content="not used")
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        result = _extract_content_with_thinking_fallback(
            msg, model="qwen3-next-80b", finish_reason="stop"
        )
    assert result == '{"ok": true}'
    assert not [r for r in caplog.records if "falling back" in r.getMessage()]


def test_returns_empty_string_unchanged_when_explicit():
    """空文字列 content は thinking-mode 症状ではないので、そのまま返す。
    呼び出し側で `text or ""` パターンが既に空文字列を許容している前提。"""
    msg = _make_message(content="", reasoning_content="should not be used")
    result = _extract_content_with_thinking_fallback(
        msg, model="qwen3-next-80b", finish_reason="stop"
    )
    assert result == ""


# ---------------------------------------------------------------------------
# (2) thinking-mode フォールバック: reasoning_content 優先
# ---------------------------------------------------------------------------

def test_falls_back_to_reasoning_content_when_content_is_none(caplog):
    main = '{"title": "テスト", "description": "本文"}'
    msg = _make_message(content=None, reasoning_content=main)
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        result = _extract_content_with_thinking_fallback(
            msg, model="qwen3-next-80b", finish_reason="stop"
        )
    assert result == main
    msgs = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("message.reasoning_content" in m for m in msgs), msgs


def test_falls_back_to_model_extra_thinking_when_no_reasoning_content(caplog):
    main = '{"a": 1}'
    msg = _make_message(content=None, reasoning_content=None,
                        model_extra={"thinking": main})
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        result = _extract_content_with_thinking_fallback(
            msg, model="qwen3-next-80b", finish_reason="stop"
        )
    assert result == main
    msgs = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("model_extra['thinking']" in m for m in msgs), msgs


def test_model_extra_reasoning_content_key_is_searched():
    main = '{"a": 1}'
    msg = _make_message(content=None, reasoning_content=None,
                        model_extra={"reasoning_content": main})
    result = _extract_content_with_thinking_fallback(
        msg, model="qwen3-next-80b", finish_reason="stop"
    )
    assert result == main


# ---------------------------------------------------------------------------
# (3) 優先順位: 公式フィールド > model_extra
# ---------------------------------------------------------------------------

def test_reasoning_content_takes_priority_over_model_extra():
    msg = _make_message(
        content=None,
        reasoning_content="from reasoning_content",
        model_extra={"reasoning_content": "from model_extra", "thinking": "from thinking"},
    )
    result = _extract_content_with_thinking_fallback(
        msg, model="qwen3-next-80b", finish_reason="stop"
    )
    assert result == "from reasoning_content"


# ---------------------------------------------------------------------------
# (4) 全フォールバック空 → None を返す
# ---------------------------------------------------------------------------

def test_returns_none_when_no_fallback_available():
    msg = _make_message(content=None, reasoning_content=None, model_extra=None)
    result = _extract_content_with_thinking_fallback(
        msg, model="qwen3-next-80b", finish_reason="stop"
    )
    assert result is None


def test_whitespace_only_fallback_does_not_count_as_valid():
    msg = _make_message(
        content=None,
        reasoning_content="   \n\t  ",
        model_extra={"thinking": ""},
    )
    result = _extract_content_with_thinking_fallback(
        msg, model="qwen3-next-80b", finish_reason="stop"
    )
    assert result is None


# ---------------------------------------------------------------------------
# (5) OllamaAdapter と挙動一致: 同じ探索順序キー
# ---------------------------------------------------------------------------

def test_fallback_key_set_matches_ollama_adapter():
    """OllamaClient と OllamaAdapter で _THINKING_FALLBACK_KEYS が一致すること。"""
    from services.script_generation.adapters.ollama_adapter import (
        _THINKING_FALLBACK_KEYS as adapter_keys,
    )
    from services.script_generation.ollama_client import (
        _THINKING_FALLBACK_KEYS as client_keys,
    )
    assert adapter_keys == client_keys, (
        "adapter と client で thinking-mode フォールバックキーがズレている"
    )
