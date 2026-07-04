"""workflow._build_publish_fields の単体テスト（Phase 4 分解 E3）。

_run_phases から抽出した純計算ヘルパー。datetime.now() を排した決定的関数として
タイトル整形・publishing_config パススルー・フッター優先順位を検証する。
"""
from types import SimpleNamespace

from core.models.script import DialogueTurn, Script, TurnType
from core.models.usage import LLMUsage, TotalUsage
from workflow import _build_publish_fields


def _make_script(title: str = "台本タイトル", description: str = "説明文") -> Script:
    turns = [
        DialogueTurn(speaker="A", text=f"line{i}", turn_type=TurnType.DIALOGUE)
        for i in range(10)
    ]
    return Script(title=title, thumbnail_title="th", sections=turns, description=description)


def _make_config(default_tags=None, footer_text="") -> SimpleNamespace:
    return SimpleNamespace(
        yaml=SimpleNamespace(
            publishing=SimpleNamespace(
                default_tags=default_tags if default_tags is not None else [],
                footer_text=footer_text,
            )
        )
    )


def test_title_uses_generated_metadata_and_creation_date():
    title, _desc, _pub = _build_publish_fields(
        config=_make_config(),
        theme="テーマ",
        script=_make_script(),
        research_sources=None,
        generated_metadata={"title": "AI生成タイトル"},
        chapters=[],
        total_usage=TotalUsage(),
        footer_text_override=None,
        creation_date="2026.07.04",
    )
    assert title == "AI生成タイトル (2026.07.04制作)"


def test_title_falls_back_to_script_title_when_metadata_missing():
    title, _desc, _pub = _build_publish_fields(
        config=_make_config(),
        theme="テーマ",
        script=_make_script(title="スクリプト題"),
        research_sources=None,
        generated_metadata={},  # title キー無し
        chapters=[],
        total_usage=TotalUsage(),
        footer_text_override=None,
        creation_date="2026.07.04",
    )
    assert title == "スクリプト題 (2026.07.04制作)"


def test_returns_publishing_config_object():
    config = _make_config(default_tags=["タグ"], footer_text="config footer")
    _title, _desc, pub = _build_publish_fields(
        config=config,
        theme="テーマ",
        script=_make_script(),
        research_sources=None,
        generated_metadata={"title": "T"},
        chapters=[],
        total_usage=TotalUsage(),
        footer_text_override=None,
        creation_date="2026.07.04",
    )
    assert pub is config.yaml.publishing


def test_footer_override_takes_precedence_over_config():
    config = _make_config(footer_text="config footer")
    _t, desc_override, _p = _build_publish_fields(
        config=config,
        theme="テーマ",
        script=_make_script(),
        research_sources=None,
        generated_metadata={"title": "T"},
        chapters=[],
        total_usage=TotalUsage(),
        footer_text_override="UIフッター",
        creation_date="2026.07.04",
    )
    # override が空のときは config フォールバック
    _t2, desc_config, _p2 = _build_publish_fields(
        config=config,
        theme="テーマ",
        script=_make_script(),
        research_sources=None,
        generated_metadata={"title": "T"},
        chapters=[],
        total_usage=TotalUsage(),
        footer_text_override="   ",  # 空白のみ → フォールバック
        creation_date="2026.07.04",
    )
    assert "UIフッター" in desc_override
    assert "config footer" in desc_config


def test_llm_model_info_included_when_usage_present():
    usage = TotalUsage()
    usage.llm_usage["ollama"] = LLMUsage(provider="ollama", model_name="gpt-oss")
    _t, desc, _p = _build_publish_fields(
        config=_make_config(),
        theme="テーマ",
        script=_make_script(),
        research_sources=None,
        generated_metadata={"title": "T"},
        chapters=[],
        total_usage=usage,
        footer_text_override=None,
        creation_date="2026.07.04",
    )
    assert "OLLAMA: gpt-oss" in desc
