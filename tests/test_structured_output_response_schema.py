"""vLLM Structured Output 基盤テスト (Phase 1)

担保する内容:
1. LLMRequest に response_schema / response_schema_name / response_schema_strict
   フィールドが追加されており、デフォルト値で完全な後方互換を保つ
2. OllamaAdapter は response_schema=None なら従来の json_object を使い続ける
3. OllamaAdapter は response_schema が dict なら OpenAI 標準形式
   `response_format={"type":"json_schema","json_schema":{"name":...,"strict":...,"schema":...}}`
   に変換して chat.completions.create に渡す
4. TopicCurator は CurationResult のスキーマを LLMRequest に乗せて呼び出す
"""
import asyncio
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.interfaces.llm_port import LLMRequest, LLMResponse
from core.models import LLMUsage
from core.models.curation import CurationResult
from services.script_generation.adapters.ollama_adapter import OllamaAdapter


# ---------------------------------------------------------------------------
# (1) LLMRequest: 新フィールドのデフォルト値と後方互換
# ---------------------------------------------------------------------------

def test_llm_request_response_schema_defaults():
    req = LLMRequest(
        system_prompt="s",
        user_prompt="u",
        model="m",
        max_tokens=128,
        temperature=0.5,
    )
    assert req.response_schema is None
    assert req.response_schema_name == "response"
    assert req.response_schema_strict is False


def test_llm_request_response_schema_can_be_set():
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
    req = LLMRequest(
        system_prompt="s",
        user_prompt="u",
        model="m",
        max_tokens=128,
        temperature=0.5,
        response_schema=schema,
        response_schema_name="my_schema",
        response_schema_strict=True,
    )
    assert req.response_schema == schema
    assert req.response_schema_name == "my_schema"
    assert req.response_schema_strict is True


# ---------------------------------------------------------------------------
# (2) OllamaAdapter: response_schema=None なら従来挙動
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


def _make_adapter():
    adapter = OllamaAdapter(
        base_url="http://test.invalid:11435/v1",
        default_model="qwen3.5-122b-a10b",
    )
    create_mock = AsyncMock(return_value=_make_openai_response())
    adapter._client.chat.completions.create = create_mock
    return adapter, create_mock


def test_ollama_adapter_no_schema_falls_back_to_json_object():
    """response_schema=None かつ response_format='json' なら従来の json_object を使う"""
    adapter, create_mock = _make_adapter()
    req = LLMRequest(
        system_prompt="s", user_prompt="u", model="m",
        max_tokens=128, temperature=0.3,
        response_format="json",
    )
    asyncio.run(adapter.generate(req))

    kwargs = create_mock.call_args.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}
    # frequency_penalty は JSON モード値
    assert kwargs["frequency_penalty"] == 0.5


def test_ollama_adapter_no_schema_text_mode_unchanged():
    """response_schema=None かつ response_format='text' は dialog 用の penalty"""
    adapter, create_mock = _make_adapter()
    req = LLMRequest(
        system_prompt="s", user_prompt="u", model="m",
        max_tokens=128, temperature=0.3,
        response_format="text",
    )
    asyncio.run(adapter.generate(req))

    kwargs = create_mock.call_args.kwargs
    # text モードでは response_format を渡さない
    assert "response_format" not in kwargs
    assert kwargs["frequency_penalty"] == 0.9


# ---------------------------------------------------------------------------
# (3) OllamaAdapter: response_schema 付きで OpenAI 標準形式に変換
# ---------------------------------------------------------------------------

def test_ollama_adapter_passes_json_schema_when_response_schema_provided():
    adapter, create_mock = _make_adapter()
    schema = {
        "type": "object",
        "properties": {"animal": {"type": "string", "enum": ["cat", "dog"]}},
        "required": ["animal"],
    }
    req = LLMRequest(
        system_prompt="s", user_prompt="u", model="m",
        max_tokens=128, temperature=0.3,
        response_format="json",
        response_schema=schema,
        response_schema_name="animal_pick",
        response_schema_strict=False,
    )
    asyncio.run(adapter.generate(req))

    kwargs = create_mock.call_args.kwargs
    # OpenAI 標準形式に変換されている
    assert kwargs["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "animal_pick",
            "strict": False,
            "schema": schema,
        },
    }
    # JSON モード相当の frequency_penalty
    assert kwargs["frequency_penalty"] == 0.5


def test_ollama_adapter_response_schema_strict_true_propagates():
    adapter, create_mock = _make_adapter()
    schema = {"type": "object", "properties": {}}
    req = LLMRequest(
        system_prompt="s", user_prompt="u", model="m",
        max_tokens=128, temperature=0.3,
        response_format="json",
        response_schema=schema,
        response_schema_name="strict_thing",
        response_schema_strict=True,
    )
    asyncio.run(adapter.generate(req))

    js = create_mock.call_args.kwargs["response_format"]["json_schema"]
    assert js["strict"] is True
    assert js["name"] == "strict_thing"


def test_ollama_adapter_response_schema_overrides_json_object():
    """response_schema が指定されている場合、response_format='json' と併存しても json_schema が勝つ"""
    adapter, create_mock = _make_adapter()
    schema = {"type": "object"}
    req = LLMRequest(
        system_prompt="s", user_prompt="u", model="m",
        max_tokens=128, temperature=0.3,
        response_format="json",  # 普通の JSON モードも要求
        response_schema=schema,  # しかし schema が優先
    )
    asyncio.run(adapter.generate(req))

    rf = create_mock.call_args.kwargs["response_format"]
    # json_schema 形式（json_object ではない）
    assert rf["type"] == "json_schema"


def test_ollama_adapter_extra_body_still_attached_with_schema():
    """response_schema があっても enable_thinking / chat_template_kwargs は維持される"""
    adapter, create_mock = _make_adapter()
    schema = {"type": "object"}
    req = LLMRequest(
        system_prompt="s", user_prompt="u", model="m",
        max_tokens=128, temperature=0.3,
        response_format="json",
        response_schema=schema,
        enable_thinking=False,
    )
    asyncio.run(adapter.generate(req))

    kwargs = create_mock.call_args.kwargs
    assert kwargs["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }
    assert kwargs["response_format"]["type"] == "json_schema"


# ---------------------------------------------------------------------------
# (4) TopicCurator: CurationResult スキーマを LLMRequest に乗せる
# ---------------------------------------------------------------------------

def _make_curator(mock_app_config):
    from services.script_generation.topic_curator import TopicCurator
    mock_port = MagicMock()
    mock_port.provider_name = "ollama"

    mock_app_config.yaml.script_generator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.curator_model = "qwen3.5-122b-a10b"
    mock_app_config.yaml.script_generator.orchestrator.topic_curator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.topic_curator.max_tokens = 12288

    return TopicCurator(mock_port, mock_app_config)


def test_topic_curator_passes_curation_result_schema(mock_app_config):
    """TopicCurator._call_api が CurationResult.model_json_schema() を載せた LLMRequest を投げる"""
    curator = _make_curator(mock_app_config)

    captured = {}

    async def _fake_generate(request: LLMRequest):
        captured["request"] = request
        return LLMResponse(
            content='{"topics": [{"title": "T", "content": "c", "priority": 1, "tone": "解説", "key_facts": []}]}',
            usage=LLMUsage(provider="ollama", model_name="x", input_tokens=1, output_tokens=1),
            finish_reason="stop",
        )

    curator._llm.generate = _fake_generate

    asyncio.run(curator._call_api("sys", "usr"))

    req = captured["request"]
    assert req.response_schema is not None, "TopicCurator は CurationResult schema を渡すべき"
    assert isinstance(req.response_schema, dict)
    assert req.response_schema_name == "curation_result"
    assert req.response_schema_strict is False  # default 値の柔軟性のため
    # スキーマが CurationResult 由来であることを確認（topics プロパティが存在）
    assert req.response_schema == CurationResult.model_json_schema()
    assert "properties" in req.response_schema
    assert "topics" in req.response_schema["properties"]


def test_topic_curator_schema_includes_curated_topic_definition(mock_app_config):
    """CurationResult スキーマは $defs.CuratedTopic を含む（vLLM が型情報を必要とする）"""
    curator = _make_curator(mock_app_config)
    schema = CurationResult.model_json_schema()
    # Pydantic の model_json_schema は ネストモデルを $defs に格納する
    assert "$defs" in schema
    assert "CuratedTopic" in schema["$defs"]
    ct = schema["$defs"]["CuratedTopic"]
    # 主要フィールドが存在
    for field in ["title", "content", "priority", "tone", "key_facts"]:
        assert field in ct["properties"], f"CuratedTopic に {field} プロパティが無い"


# ---------------------------------------------------------------------------
# (5) 構造的契約: 他プロバイダーアダプタは response_schema を「読まない」
#     （Phase 1 では Ollama 専用、他は無視で後方互換）
# ---------------------------------------------------------------------------

ADAPTER_SRC_DIR = Path(__file__).resolve().parent.parent / "services" / "script_generation" / "adapters"


def test_other_adapters_do_not_consume_response_schema_in_phase1():
    """Phase 1: gemini/openai/anthropic アダプタは response_schema を参照しない（参照が無い → 自然に無視）"""
    for fname in ["gemini_adapter.py", "openai_adapter.py", "anthropic_adapter.py"]:
        src = (ADAPTER_SRC_DIR / fname).read_text(encoding="utf-8")
        assert "response_schema" not in src, (
            f"{fname} に response_schema 参照がある。Phase 1 では他プロバイダーは "
            f"非対応 (LLMRequest フィールドを完全に無視) で固める方針"
        )


def test_ollama_adapter_consumes_response_schema():
    """OllamaAdapter は response_schema を読み出して使うこと（Phase 1 の唯一の対応プロバイダー）"""
    src = (ADAPTER_SRC_DIR / "ollama_adapter.py").read_text(encoding="utf-8")
    # 参照されている
    assert re.search(r"request\.response_schema", src), (
        "ollama_adapter.py は request.response_schema を読まないと schema 投与ができない"
    )
    # OpenAI 標準形式の type=json_schema に変換している
    assert re.search(r'"type"\s*:\s*"json_schema"', src) or re.search(
        r"'type'\s*:\s*'json_schema'", src
    ), "ollama_adapter.py は response_format type=json_schema 形式を組み立てるべき"
