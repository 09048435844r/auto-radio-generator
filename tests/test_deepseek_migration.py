"""DeepSeekV4Flash 移行 (2026-07) の新規回帰テスト

GX10 の vLLM バックエンドが Qwen3.5-122B から 2 ノードクラスターの
DeepSeekV4Flash (served-model-name: "deepseek-v4-flash") に移行したことに伴う
追加テスト。Append-Only 原則により既存テストは一切変更せず、本ファイルで
新規挙動のみを検証する。

検証対象:
1. get_provider_from_model_name: "deepseek-v4-flash" 完全一致 → "ollama"
   （"deepseek-" の広いプレフィックスマッチは意図的に不採用。未対応の
   deepseek 系モデル名は従来どおり ValueError — 既存テスト
   test_llm_factory_provider_inference.py の仕様を維持）
2. OllamaAdapter.inject_no_think=False: system prompt へ /no_think を注入しない
   （/no_think は Qwen3 系 chat template 専用の制御トークンで、DeepSeek には
   ただのリテラルとして届きプロンプト汚染になるため。thinking 抑制は
   Mac Studio Proxy 側の reasoning_effort="none" で担保）
3. LLMAdapterFactory: OllamaConfig.inject_no_think を Adapter へ配線する
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.interfaces.llm_port import LLMRequest
from core.models.config import OllamaConfig
from services.script_generation.adapters.factory import LLMAdapterFactory
from services.script_generation.adapters.ollama_adapter import OllamaAdapter
from services.script_generation.llm_factory import get_provider_from_model_name


# ---------------------------------------------------------------------------
# (1) provider 推論: deepseek-v4-flash 完全一致 → ollama
# ---------------------------------------------------------------------------

def test_deepseek_v4_flash_maps_to_ollama():
    """served-model-name の完全一致のみ ollama にマッピングされる。"""
    assert get_provider_from_model_name("deepseek-v4-flash") == "ollama"


@pytest.mark.parametrize("non_exact_name", [
    "deepseek-v4-flash-2",   # 完全一致でない派生名
    "deepseek-v4",           # 部分文字列
    "DeepSeek-V4-Flash",     # 大文字（served-model-name は小文字固定）
])
def test_non_exact_deepseek_names_still_raise_value_error(non_exact_name):
    """完全一致以外の deepseek 系は従来どおり ValueError（防御的挙動の維持）。"""
    with pytest.raises(ValueError, match="Unknown model name"):
        get_provider_from_model_name(non_exact_name)


# ---------------------------------------------------------------------------
# (2) OllamaAdapter: inject_no_think オプトアウト
# ---------------------------------------------------------------------------

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


def _make_adapter_with_capture(**adapter_kwargs):
    adapter = OllamaAdapter(
        base_url="http://test.invalid:11435/v1",
        default_model="deepseek-v4-flash",
        **adapter_kwargs,
    )
    create_mock = AsyncMock(return_value=_make_openai_response())
    adapter._client.chat.completions.create = create_mock
    return adapter, create_mock


def _sent_messages(create_mock):
    return create_mock.call_args.kwargs["messages"]


def test_inject_no_think_false_does_not_prefix_system_prompt():
    """inject_no_think=False では enable_thinking=False でも /no_think を付与しない。"""
    adapter, create_mock = _make_adapter_with_capture(inject_no_think=False)
    req = LLMRequest(
        system_prompt="sys",
        user_prompt="hi",
        model="deepseek-v4-flash",
        max_tokens=256,
        temperature=0.6,
        response_format="text",
    )
    asyncio.run(adapter.generate(req))

    messages = _sent_messages(create_mock)
    assert messages[0] == {"role": "system", "content": "sys"}, (
        "inject_no_think=False では system prompt が無加工で送信されるべき"
    )
    assert all("/no_think" not in m["content"] for m in messages)


def test_inject_no_think_default_true_preserves_legacy_behavior():
    """デフォルト（引数省略）は従来挙動: /no_think を system prompt 先頭に付与。"""
    adapter, create_mock = _make_adapter_with_capture()
    req = LLMRequest(
        system_prompt="sys",
        user_prompt="hi",
        model="deepseek-v4-flash",
        max_tokens=256,
        temperature=0.6,
        response_format="text",
    )
    asyncio.run(adapter.generate(req))

    messages = _sent_messages(create_mock)
    assert messages[0] == {"role": "system", "content": "/no_think\nsys"}


def test_inject_no_think_false_with_empty_system_prompt_adds_no_message():
    """inject_no_think=False では防御的な /no_think 専用 system メッセージも追加しない。

    従来挙動（inject_no_think=True）は system メッセージが無い場合に
    {"role": "system", "content": "/no_think"} を先頭に insert していた。
    False 時はこの防御的挿入も含めて一切付与しないことを担保する。
    """
    adapter, create_mock = _make_adapter_with_capture(inject_no_think=False)
    req = LLMRequest(
        system_prompt="",
        user_prompt="hi",
        model="deepseek-v4-flash",
        max_tokens=256,
        temperature=0.6,
        response_format="text",
    )
    asyncio.run(adapter.generate(req))

    messages = _sent_messages(create_mock)
    assert all("/no_think" not in m["content"] for m in messages)


# ---------------------------------------------------------------------------
# (3) 配線: OllamaConfig.inject_no_think → LLMAdapterFactory → OllamaAdapter
# ---------------------------------------------------------------------------

def test_ollama_config_defaults():
    """OllamaConfig の新デフォルト: model=deepseek-v4-flash / inject_no_think=True。

    inject_no_think のデフォルト True は既存挙動（Qwen 系バックエンド）の維持。
    shipped config.yaml 側で false を明示する運用（SSOT は config.yaml）。
    """
    cfg = OllamaConfig()
    assert cfg.model == "deepseek-v4-flash"
    assert cfg.inject_no_think is True


@pytest.mark.parametrize("inject_flag", [True, False])
def test_factory_wires_inject_no_think_from_config(inject_flag):
    """LLMAdapterFactory が OllamaConfig.inject_no_think を Adapter へ渡す。"""
    mock_config = MagicMock()
    mock_config.yaml.script_generator.ollama = OllamaConfig(
        base_url="http://test.invalid:11435/v1",
        model="deepseek-v4-flash",
        inject_no_think=inject_flag,
    )

    adapter = LLMAdapterFactory.create(mock_config, "ollama")

    assert isinstance(adapter, OllamaAdapter)
    assert adapter._inject_no_think is inject_flag
    assert adapter._default_model == "deepseek-v4-flash"
