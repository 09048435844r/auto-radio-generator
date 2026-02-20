"""Utilities for building rich YouTube metadata text blocks."""

from __future__ import annotations

from typing import List

from core.models.research import ResearchSource


ReferenceEntry = str | ResearchSource


def _normalize_non_empty(items: List[str]) -> List[str]:
    """Trim values, drop empties, and preserve order while deduplicating."""
    seen = set()
    normalized: List[str] = []
    for item in items:
        value = (item or "").strip()
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _normalize_references(items: List[ReferenceEntry]) -> List[ReferenceEntry]:
    """Trim values, drop empties, and preserve order while deduplicating by URL/string."""
    seen = set()
    normalized: List[ReferenceEntry] = []
    for item in items:
        if isinstance(item, ResearchSource):
            url = (item.url or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            normalized.append(item)
            continue

        value = (item or "").strip()
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def build_video_description(
    script_description: str,
    chapters: List[str],
    references: List[ReferenceEntry],
    dynamic_tags: List[str],
    fixed_tags: List[str],
    footer_text: str,
) -> str:
    """Build a rich YouTube description with a fixed, maintainable structure.

    構成順序:
    1. 【動画の概要】(script_description)
    2. <空行>
    3. 【目次】(chapters - 00:00 形式)
    4. <空行>
    5. 【参考文献】(references - 箇条書き)
    6. <空行>
    7. 【タグ】(dynamic_tags + fixed_tags)
    8. <空行>
    9. footer_text
    """
    description_text = (script_description or "").strip() or "（概要未設定）"
    chapter_lines = _normalize_non_empty(chapters)
    reference_lines = _normalize_references(references)

    merged_tags = _normalize_non_empty([*dynamic_tags, *fixed_tags])
    footer = (footer_text or "").strip() or "（フッター未設定）"

    lines: List[str] = ["【動画の概要】", description_text, ""]

    lines.append("【目次】")
    if chapter_lines:
        lines.extend(chapter_lines)
    else:
        lines.append("- チャプター情報なし")
    lines.append("")

    lines.append("【参考文献】")
    if reference_lines:
        for idx, ref in enumerate(reference_lines, start=1):
            if isinstance(ref, ResearchSource):
                title = (ref.title or "").strip() or f"参考文献{idx}"
                url = (ref.url or "").strip()
                lines.append(f"📄 {title}")
                lines.append(f"🔗 {url}")
                lines.append("")  # 空行で区切り
            else:
                # 文字列（URL）の場合
                lines.append(f"📄 参考文献{idx}")
                lines.append(f"🔗 {ref}")
                lines.append("")  # 空行で区切り
    else:
        lines.append("- 参考文献なし")
    lines.append("")

    lines.append("【タグ】")
    if merged_tags:
        lines.append(" ".join(merged_tags))
    else:
        lines.append("#ラジオ")
    lines.append("")

    lines.append(footer)

    return "\n".join(lines)
