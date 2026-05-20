"""
VisualPaletteGenerator の Mac Studio Proxy 経路への移行回帰テスト (Step 6)

Step 5 まで Gemini Structured Output 直叩きだった
`services.script_generation.visual_palette_generator` を、
Step 6 で `LLMAdapterFactory("ollama")` 経由 (= Mac Studio Proxy / vLLM) に置換した。

本テストは:
  1. generate_identity 正常系 (mock port → JSON → VisualIdentity)
  2. JSON パース失敗時に static fallback (_get_fallback_identity) が返ること
  3. API エラー時にも static fallback が返ること
  4. (構造的回帰防止) genai / types module 未 import であること
を保護する。

非同期テストは本プロジェクト既存パターン (test_image_prompt_generator.py 等) に
合わせ、sync 関数 + asyncio.run(...) で記述する (pytest-asyncio 非依存)。
"""

import asyncio

import pytest
from unittest.mock import Mock, patch, AsyncMock

from core.interfaces.llm_port import LLMRequest, LLMResponse
from core.models.usage import LLMUsage
from core.models.visual import (
    VisualIdentity,
    DEFAULT_PRIMARY_COLOR,
    DEFAULT_SECONDARY_COLOR,
    DEFAULT_AESTHETIC,
)


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
                input_tokens=80,
                output_tokens=120,
                request_count=1,
            ),
            finish_reason="stop",
        )
    )
    return port


def _make_mock_config() -> Mock:
    """VisualPaletteGenerator が __init__ で参照する設定だけ整えた Mock を返す。"""
    config = Mock()
    config.yaml.script_generator.orchestrator.curator_model = CURATOR_MODEL_FOR_TEST
    return config


# Few-shot 例 (Theme: "持続血糖測定器CGMについて") と同形の有効 JSON
_VALID_VISUAL_IDENTITY_JSON = """{
  "primary_color": "electric cyan",
  "secondary_color": "hot magenta",
  "color_mood": "futuristic medical",
  "aesthetic": "Clean Minimalist Modern",
  "visual_keywords": ["clinical", "sterile", "high-tech"],
  "reasoning": "Medical theme requires clean, professional aesthetic"
}"""


class TestGenerateIdentity:
    """generate_identity のテスト"""

    @patch("services.script_generation.visual_palette_generator.LLMAdapterFactory.create")
    def test_uses_ollama_port_with_curator_model(self, mock_factory_create):
        """
        provider=ollama / model_override=curator_model で LLMAdapterFactory が呼ばれ、
        LLMRequest の中身 (model / max_tokens / temperature / response_format) が
        プラン通りであり、返却 JSON が VisualIdentity にパースされること。
        """
        from services.script_generation.visual_palette_generator import (
            VisualPaletteGenerator,
        )

        mock_port = _make_port_mock(_VALID_VISUAL_IDENTITY_JSON)
        mock_factory_create.return_value = mock_port

        gen = VisualPaletteGenerator(_make_mock_config())
        identity = asyncio.run(
            gen.generate_identity(
                theme="持続血糖測定器CGMについて",
                script_summary="CGMの精度と臨床現場での活用について議論する",
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

        # LLMRequest の中身検証
        mock_port.generate.assert_called_once()
        request = mock_port.generate.call_args.args[0]
        assert isinstance(request, LLMRequest)
        assert request.model == CURATOR_MODEL_FOR_TEST
        assert request.max_tokens == 1024
        assert request.temperature == pytest.approx(0.9)
        assert request.response_format == "json"
        # SYSTEM_PROMPT がそのまま system 側に詰まっていること
        assert "professional art director" in request.system_prompt
        # 受け取った JSON が VisualIdentity にパースされていること
        assert isinstance(identity, VisualIdentity)
        assert identity.primary_color == "electric cyan"
        assert identity.secondary_color == "hot magenta"
        assert identity.aesthetic == "Clean Minimalist Modern"
        assert "clinical" in identity.visual_keywords

    @patch("services.script_generation.visual_palette_generator.LLMAdapterFactory.create")
    def test_falls_back_on_invalid_json(self, mock_factory_create):
        """LLM が壊れた / スキーマ違反の JSON を返した場合、
        _get_fallback_identity の DEFAULT identity が返ること (例外伝播なし)。"""
        from services.script_generation.visual_palette_generator import (
            VisualPaletteGenerator,
        )

        # primary_color 等の必須フィールドが欠落した不正 JSON
        broken_json = '{"foo": "bar"}'
        mock_port = _make_port_mock(broken_json)
        mock_factory_create.return_value = mock_port

        gen = VisualPaletteGenerator(_make_mock_config())
        identity = asyncio.run(
            gen.generate_identity(theme="壊れたJSON再現", script_summary="summary")
        )

        # フォールバック値が返ること
        assert isinstance(identity, VisualIdentity)
        assert identity.primary_color == DEFAULT_PRIMARY_COLOR
        assert identity.secondary_color == DEFAULT_SECONDARY_COLOR
        assert identity.aesthetic == DEFAULT_AESTHETIC

    @patch("services.script_generation.visual_palette_generator.LLMAdapterFactory.create")
    def test_falls_back_on_api_error(self, mock_factory_create):
        """API 呼び出しが例外を投げた場合も _get_fallback_identity が返ること。"""
        from services.script_generation.visual_palette_generator import (
            VisualPaletteGenerator,
        )

        mock_port = Mock()
        mock_port.generate = AsyncMock(
            side_effect=RuntimeError("Mac Studio Proxy down")
        )
        mock_factory_create.return_value = mock_port

        gen = VisualPaletteGenerator(_make_mock_config())
        identity = asyncio.run(
            gen.generate_identity(theme="API停止再現", script_summary="summary")
        )

        assert isinstance(identity, VisualIdentity)
        assert identity.primary_color == DEFAULT_PRIMARY_COLOR
        assert identity.secondary_color == DEFAULT_SECONDARY_COLOR


class TestStructuralRegression:
    """構造的回帰防止: Gemini SDK 依存が消えていることを検証"""

    def test_module_does_not_import_gemini_sdk(self):
        """visual_palette_generator モジュールに google.genai 由来のシンボルが
        残っていないこと (Step 5 で Gemini adapter 物理削除済みの整合)。"""
        import services.script_generation.visual_palette_generator as m

        assert not hasattr(m, "genai"), (
            "google.genai は Step 6 で削除済みの import。再混入していないか確認"
        )
        assert not hasattr(m, "types"), (
            "google.genai.types は Step 6 で削除済みの import。再混入していないか確認"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
