"""metadata_builder のフォーマット検証テスト"""

from core.models.research import ResearchSource
from services.publishing.metadata_builder import build_video_description
from services.publishing.text_sanitizer import sanitize_for_youtube


def test_reference_title_url_newline_preserved_after_sanitize():
    """タイトル行とURL行の改行がサニタイザー後も保持されることを検証"""
    raw = "📄 タイトル\n🔗 https://example.com\n\n"
    sanitized = sanitize_for_youtube(raw)

    assert "📄 タイトル\n🔗 https://example.com" in sanitized
    assert "\n\n" in sanitized


def test_build_video_description_section_spacing_and_reference_block():
    """セクション間の2行空行と参考文献3行構造を検証"""
    description = build_video_description(
        script_description="概要テキスト",
        chapters=["00:00 オープニング", "01:00 本編"],
        references=[
            ResearchSource(title="Example Title", url="https://example.com"),
            "https://example.org",
        ],
        dynamic_tags=["#tag1"],
        fixed_tags=["#fixed"],
        footer_text="footer",
    )

    # セクション見出し前後の2行空行（目次見出し後の例）
    assert "【目次】\n\n\n00:00 オープニング" in description

    # 参考文献は厳密に3行構造
    assert "📄 Example Title\n🔗 https://example.com\n\n" in description
    assert "📄 参考文献2\n🔗 https://example.org\n\n" in description

    # 参考文献セクションの視認性（見出し後に2行空行）
    assert "【参考文献】\n\n\n📄 Example Title" in description
