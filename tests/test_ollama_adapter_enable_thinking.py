"""OllamaAdapter enable_thinking (vLLM thinking mode 抑止) 回帰テスト

vLLM (Qwen3.5 thinking model) は chat_template_kwargs.enable_thinking=False を
受け取らないと thinking token を生成し続けて max_tokens を食い潰し、
finish_reason="length" + 空 content で落ちる本運用バグがある。
本テストは Adapter が常に extra_body 経由で chat_template_kwargs.enable_thinking
を送ること、LLMRequest の値が透過的に伝播することを担保する。

Ollama 本体（vLLM ではない）は OpenAI 互換 API の extra_body 未知フィールドを
無視するため、本フィールドは混在しても無害である。
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.interfaces.llm_port import LLMRequest
from services.script_generation.adapters.ollama_adapter import OllamaAdapter


def _make_openai_response(content: str = '{"ok": true}', finish_reason: str = "stop"):
    message = MagicMock()
    message.content = content
    message.reasoning_content = None
    message.model_extra = None

    choice = MagicMock()
    choice.message = message
    choice.finish_reason = finish_reason

    response = MagicMock()
    response.choices = [choice]
    response.usage = MagicMock()
    response.usage.prompt_tokens = 5
    response.usage.completion_tokens = 3
    return response


def _make_adapter_with_capture():
    """OllamaAdapter + chat.completions.create の AsyncMock を返す。
    呼び出し時の kwargs を `mock.call_args` で検査することで extra_body の中身を確認する。
    """
    adapter = OllamaAdapter(
        base_url="http://test.invalid:11435/v1",
        default_model="qwen3-next-80b",
    )
    create_mock = AsyncMock(return_value=_make_openai_response())
    adapter._client.chat.completions.create = create_mock
    return adapter, create_mock


# ---------------------------------------------------------------------------
# (1) LLMRequest defaults: enable_thinking is False by default
# ---------------------------------------------------------------------------

def test_llm_request_enable_thinking_default_is_false():
    req = LLMRequest(
        system_prompt="s",
        user_prompt="u",
        model="m",
        max_tokens=128,
        temperature=0.5,
    )
    assert req.enable_thinking is False


def test_llm_request_enable_thinking_can_be_overridden():
    req = LLMRequest(
        system_prompt="s",
        user_prompt="u",
        model="m",
        max_tokens=128,
        temperature=0.5,
        enable_thinking=True,
    )
    assert req.enable_thinking is True


# ---------------------------------------------------------------------------
# (2) OllamaAdapter passes extra_body with chat_template_kwargs
# ---------------------------------------------------------------------------

def test_ollama_adapter_sends_extra_body_with_enable_thinking_false_by_default():
    adapter, create_mock = _make_adapter_with_capture()
    req = LLMRequest(
        system_prompt="sys",
        user_prompt="hi",
        model="qwen3-next-80b",
        max_tokens=256,
        temperature=0.6,
        response_format="text",
    )
    asyncio.run(adapter.generate(req))

    assert create_mock.await_count == 1
    kwargs = create_mock.call_args.kwargs
    assert "extra_body" in kwargs, (
        "OllamaAdapter must always send extra_body with chat_template_kwargs"
    )
    extra_body = kwargs["extra_body"]
    assert extra_body == {"chat_template_kwargs": {"enable_thinking": False}}


def test_ollama_adapter_propagates_enable_thinking_true():
    adapter, create_mock = _make_adapter_with_capture()
    req = LLMRequest(
        system_prompt="sys",
        user_prompt="hi",
        model="qwen3-next-80b",
        max_tokens=256,
        temperature=0.6,
        response_format="text",
        enable_thinking=True,
    )
    asyncio.run(adapter.generate(req))

    extra_body = create_mock.call_args.kwargs["extra_body"]
    assert extra_body == {"chat_template_kwargs": {"enable_thinking": True}}


def test_ollama_adapter_extra_body_works_with_json_response_format():
    """JSON モードでも extra_body は付与され、既存の response_format と共存する"""
    adapter, create_mock = _make_adapter_with_capture()
    req = LLMRequest(
        system_prompt="sys",
        user_prompt="hi",
        model="qwen3-next-80b",
        max_tokens=256,
        temperature=0.6,
        response_format="json",
    )
    asyncio.run(adapter.generate(req))

    kwargs = create_mock.call_args.kwargs
    # 既存挙動: JSON モードで response_format / frequency_penalty が付く
    assert kwargs["response_format"] == {"type": "json_object"}
    assert "frequency_penalty" in kwargs
    # 新挙動: extra_body も並列して付く
    assert kwargs["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }


def test_ollama_adapter_extra_body_does_not_replace_other_kwargs():
    """extra_body 追加で既存の model/messages/max_tokens/temperature が崩れないこと"""
    adapter, create_mock = _make_adapter_with_capture()
    req = LLMRequest(
        system_prompt="SYS",
        user_prompt="USR",
        model="qwen3-next-80b",
        max_tokens=512,
        temperature=0.4,
        response_format="text",
    )
    asyncio.run(adapter.generate(req))

    kwargs = create_mock.call_args.kwargs
    assert kwargs["model"] == "qwen3-next-80b"
    assert kwargs["max_tokens"] == 512
    assert kwargs["temperature"] == 0.4
    # messages も system + user の 2 件で構築されている
    assert kwargs["messages"][0]["role"] == "system"
    assert kwargs["messages"][0]["content"] == "SYS"
    assert kwargs["messages"][1]["role"] == "user"
    assert kwargs["messages"][1]["content"] == "USR"


# ---------------------------------------------------------------------------
# (3) OllamaConfig has enable_thinking field with default False
# ---------------------------------------------------------------------------

def test_ollama_config_enable_thinking_default_is_false():
    from core.models.config import OllamaConfig

    cfg = OllamaConfig()
    assert cfg.enable_thinking is False


def test_ollama_config_enable_thinking_can_be_set_true():
    from core.models.config import OllamaConfig

    cfg = OllamaConfig(enable_thinking=True)
    assert cfg.enable_thinking is True
