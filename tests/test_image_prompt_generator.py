"""
ImagePromptGenerator の Mac Studio Proxy 経路への移行回帰テスト (Step 5)

Step 4 v2 まで Gemini API を直叩きしていた `services.script_generation.image_prompt_generator`
を、Step 5 で `LLMAdapterFactory("ollama")` 経由 (= Mac Studio Proxy / vLLM) に置換した。
本テストは:
  1. generate_thumbnail_prompt 正常系 (mock port → 英語プロンプト)
  2. generate_prompt 正常系 (segment ベース)
  3. API エラー時に static fallback が返ること
  4. (構造的回帰防止) genai / types module 未 import であること
を保護する。

非同期テストは本プロジェクト既存パターン (test_ollama_adapter_enable_thinking.py 等) に
合わせ、sync 関数 + asyncio.run(...) で記述する (pytest-asyncio 非依存)。
"""

import asyncio

import pytest
from unittest.mock import Mock, patch, AsyncMock

from core.interfaces.llm_port import LLMRequest, LLMResponse
from core.models.curation import ScriptSegment
from core.models.usage import LLMUsage


CURATOR_MODEL_FOR_TEST = "qwen3.5-122b-a10b"


def _make_port_mock(response_text: str) -> Mock:
    """LLMAdapterFactory.create が返す ILLMPort 互換のモックを構築する。"""
    port = Mock()
    port.generate = AsyncMock(
        return_value=LLMResponse(
            content=response_text,
            usage=LLMUsage(
                provider="ollama",
                model_name=CURATOR_MODEL_FOR_TEST,
                input_tokens=50,
                output_tokens=80,
                request_count=1,
            ),
            finish_reason="stop",
        )
    )
    return port


def _make_mock_config() -> Mock:
    """ImagePromptGenerator が __init__ で参照する設定だけ整えた Mock を返す。"""
    config = Mock()
    config.yaml.script_generator.orchestrator.curator_model = CURATOR_MODEL_FOR_TEST
    return config


class TestThumbnailPromptGeneration:
    """generate_thumbnail_prompt のテスト"""

    @patch("services.script_generation.image_prompt_generator.LLMAdapterFactory.create")
    def test_uses_ollama_port_with_curator_model(self, mock_factory_create):
        """
        provider=ollama / model_override=curator_model で LLMAdapterFactory が呼ばれ、
        LLMRequest の中身 (model / max_tokens / temperature / response_format) が
        プラン通りであること。
        """
        from services.script_generation.image_prompt_generator import ImagePromptGenerator

        dummy_response = (
            "An abstract futuristic cityscape with neon-lit skyscrapers, "
            "bathed in electric cyan and hot magenta neon lighting"
        )
        mock_port = _make_port_mock(dummy_response)
        mock_factory_create.return_value = mock_port

        config = _make_mock_config()
        gen = ImagePromptGenerator(config)
        prompt = asyncio.run(
            gen.generate_thumbnail_prompt(
                theme="AI technology",
                script_summary="discussion about AI advances",
            )
        )

        # provider="ollama" / model_override=curator_model で factory が呼ばれていること
        mock_factory_create.assert_called_once()
        factory_args = mock_factory_create.call_args
        provider_arg = (
            factory_args.args[1]
            if len(factory_args.args) >= 2
            else factory_args.kwargs.get("provider")
        )
        assert provider_arg == "ollama"
        assert factory_args.kwargs.get("model_override") == CURATOR_MODEL_FOR_TEST

        # LLMRequest の中身を検証
        mock_port.generate.assert_called_once()
        request = mock_port.generate.call_args.args[0]
        assert isinstance(request, LLMRequest)
        assert request.model == CURATOR_MODEL_FOR_TEST
        assert request.max_tokens == 512
        assert request.temperature == pytest.approx(0.9)
        assert request.response_format == "text"

        # 出力プロンプトに "no text" が含まれること (_enforce_quality_keywords の作用)
        assert "no text" in prompt.lower()

    @patch("services.script_generation.image_prompt_generator.LLMAdapterFactory.create")
    def test_falls_back_on_api_error(self, mock_factory_create):
        """API 呼び出しが例外を投げた場合、_get_fallback_thumbnail_prompt の
        英語フォールバックが返り、例外は伝播しないこと。"""
        from services.script_generation.image_prompt_generator import ImagePromptGenerator

        mock_port = Mock()
        mock_port.generate = AsyncMock(side_effect=RuntimeError("Mac Studio Proxy down"))
        mock_factory_create.return_value = mock_port

        gen = ImagePromptGenerator(_make_mock_config())
        prompt = asyncio.run(
            gen.generate_thumbnail_prompt(
                theme="AI",
                script_summary="summary",
            )
        )

        # フォールバックは "An abstract futuristic cityscape" で始まる固定文言
        assert prompt.startswith("An abstract futuristic cityscape")
        assert "no text" in prompt.lower()


class TestSegmentPromptGeneration:
    """generate_prompt (segment ベース) のテスト"""

    @patch("services.script_generation.image_prompt_generator.LLMAdapterFactory.create")
    def test_uses_ollama_port_with_segment_context(self, mock_factory_create):
        """generate_prompt が Mac Studio Proxy 経由で呼ばれ、
        LLMRequest が temperature=0.8 / max_tokens=512 / response_format=text であること。"""
        from services.script_generation.image_prompt_generator import ImagePromptGenerator

        dummy_response = (
            "A doctor examining a patient's continuous glucose monitor display, "
            "bathed in electric cyan and hot magenta neon glow"
        )
        mock_port = _make_port_mock(dummy_response)
        mock_factory_create.return_value = mock_port

        segment = ScriptSegment(
            segment_id="deep_dive_1",
            segment_type="deep_dive",
            topic_title="CGMの精度問題",
            turns=[
                {"speaker": "A", "text": "CGMは血糖値をリアルタイムで測定できる機器です"},
                {"speaker": "B", "text": "誤差は実測値の±15%程度ありますね"},
            ],
            context_summary="CGM の精度に関する議論",
        )

        gen = ImagePromptGenerator(_make_mock_config())
        prompt = asyncio.run(gen.generate_prompt(segment))

        # LLMRequest の中身検証
        mock_port.generate.assert_called_once()
        request = mock_port.generate.call_args.args[0]
        assert isinstance(request, LLMRequest)
        assert request.model == CURATOR_MODEL_FOR_TEST
        assert request.max_tokens == 512
        assert request.temperature == pytest.approx(0.8)
        assert request.response_format == "text"

        # 出力プロンプトに dummy_response の内容が含まれていること
        assert "doctor examining" in prompt
        assert "no text" in prompt.lower()


class TestStructuralRegression:
    """構造的回帰防止: Gemini SDK 依存が消えていることを検証"""

    def test_module_does_not_import_gemini_sdk(self):
        """image_prompt_generator モジュールに google.genai 由来のシンボルが
        残っていないこと (Step 4 v2 で Gemini adapter 物理削除済みの整合)。"""
        import services.script_generation.image_prompt_generator as m

        assert not hasattr(m, "genai"), (
            "google.genai は Step 5 で削除済みの import。再混入していないか確認"
        )
        assert not hasattr(m, "types"), (
            "google.genai.types は Step 5 で削除済みの import。再混入していないか確認"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
