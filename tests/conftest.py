"""テスト共通フィクスチャ"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from core.models.config import (
    AppConfig,
    EnvSettings,
    YamlConfig,
    VideoRendererConfig,
)


@pytest.fixture
def mock_app_config(tmp_path: Path) -> AppConfig:
    """テスト用のダミー AppConfig を返すフィクスチャ

    実際の .env / config.yaml を読み込まず、
    最小限のデフォルト値だけで AppConfig を構築する。
    """
    env = EnvSettings(
        PERPLEXITY_API_KEY="test-key",
        GEMINI_API_KEY="test-key",
        VOICEVOX_BASE_URL="http://localhost:50021",
    )
    yaml_config = YamlConfig(
        video_renderer=VideoRendererConfig(
            output_resolution="1920x1080",
            output_fps=30,
            bgm_volume=0.15,
            bgm_fade_in_sec=3.0,
            bgm_fade_out_sec=3.0,
            enable_spectrum=False,
            use_gpu=False,
        ),
    )
    return AppConfig(
        env=env,
        yaml=yaml_config,
        project_root=tmp_path,
    )
