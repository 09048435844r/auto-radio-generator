"""
VisualPaletteGenerator の観測性ログ回帰テスト (2026-07-15)

Visual Identity が LLM 生成かフォールバック発動かを実行ログから後追いで
切り分けられるよう追加したログの保護:
  1. フォールバック発動時に WARNING ログ (フォールバック配色を使用) が出ること
     (WARNING は LogFileWriter (PR-C) 経由で processing_log.txt に自動記録される)
  2. LLM 生成成功時に採用配色 (primary/secondary/color_mood/aesthetic) が
     INFO ログに出ること

非同期テストは既存パターン (test_visual_palette_generator.py) に合わせ、
sync 関数 + asyncio.run(...) で記述する (pytest-asyncio 非依存)。
"""

import asyncio
import logging

import pytest
from unittest.mock import Mock, patch, AsyncMock

from core.interfaces.llm_port import LLMResponse
from core.models.usage import LLMUsage
from core.models.visual import DEFAULT_PRIMARY_COLOR, DEFAULT_SECONDARY_COLOR


CURATOR_MODEL_FOR_TEST = "qwen3.5-122b-a10b"
LOGGER_NAME = "services.script_generation.visual_palette_generator"


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


_VALID_VISUAL_IDENTITY_JSON = """{
  "primary_color": "warm amber",
  "secondary_color": "soft violet",
  "color_mood": "cozy nostalgic",
  "aesthetic": "Cozy Lo-fi Studio",
  "visual_keywords": ["warm", "analog", "intimate"],
  "reasoning": "Lo-fi music requires warm, intimate aesthetic"
}"""


class TestVisualIdentityLogging:
    """LLM 生成/フォールバックのログ切り分けテスト"""

    @patch("services.script_generation.visual_palette_generator.LLMAdapterFactory.create")
    def test_fallback_emits_warning_log(self, mock_factory_create, caplog):
        """API エラーでフォールバック発動時、WARNING レベルで
        「フォールバック配色を使用」+ theme + 採用配色がログに出ること。"""
        from services.script_generation.visual_palette_generator import (
            VisualPaletteGenerator,
        )

        mock_port = Mock()
        mock_port.generate = AsyncMock(
            side_effect=RuntimeError("Mac Studio Proxy down")
        )
        mock_factory_create.return_value = mock_port

        gen = VisualPaletteGenerator(_make_mock_config())
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            asyncio.run(
                gen.generate_identity(theme="API停止再現", script_summary="summary")
            )

        warn_records = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "フォールバック配色を使用" in r.getMessage()
        ]
        assert warn_records, "フォールバック発動の WARNING ログが出ていない"
        msg = warn_records[0].getMessage()
        assert "API停止再現" in msg, "theme が WARNING ログに含まれていない"
        assert DEFAULT_PRIMARY_COLOR in msg
        assert DEFAULT_SECONDARY_COLOR in msg

    @patch("services.script_generation.visual_palette_generator.LLMAdapterFactory.create")
    def test_success_emits_adopted_identity_log(self, mock_factory_create, caplog):
        """LLM 生成成功時、採用した配色 (primary/secondary/color_mood/aesthetic)
        が「LLM生成」の明示付きで INFO ログに出ること。WARNING は出ないこと。"""
        from services.script_generation.visual_palette_generator import (
            VisualPaletteGenerator,
        )

        mock_factory_create.return_value = _make_port_mock(
            _VALID_VISUAL_IDENTITY_JSON
        )

        gen = VisualPaletteGenerator(_make_mock_config())
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            asyncio.run(
                gen.generate_identity(
                    theme="Lo-fiヒップホップの魅力", script_summary="summary"
                )
            )

        adopted_records = [
            r for r in caplog.records
            if r.levelno == logging.INFO and "LLM生成" in r.getMessage()
        ]
        assert adopted_records, "採用 identity の INFO ログが出ていない"
        msg = adopted_records[0].getMessage()
        assert "warm amber" in msg
        assert "soft violet" in msg
        assert "cozy nostalgic" in msg
        assert "Cozy Lo-fi Studio" in msg

        # 成功経路でフォールバック WARNING が出ていないこと
        assert not [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "フォールバック配色を使用" in r.getMessage()
        ]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
