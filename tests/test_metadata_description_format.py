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
    """セクション間(2行) > セクション内(0〜1行) と参考文献3行構造を検証"""
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

    # セクション間は2行空行、見出し直後は0行
    assert "概要テキスト\n\n\n【目次】\n00:00 オープニング" in description

    # 参考文献は厳密に3行構造
    assert "📄 Example Title\n🔗 https://example.com\n\n" in description
    assert "📄 参考文献2\n🔗 https://example.org\n\n" in description

    # 参考文献セクションも見出し直後は0行
    assert "【参考文献】\n📄 Example Title" in description

    # 末尾に不要な空行を残さない
    assert description.endswith("footer")
