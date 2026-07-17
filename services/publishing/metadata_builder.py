"""YouTube動画メタデータ構築ユーティリティ"""
from __future__ import annotations

import logging
from typing import List

from services.publishing.text_sanitizer import sanitize_for_youtube, validate_chapter_format
from core.models.research import ResearchSource

logger = logging.getLogger(__name__)

ReferenceEntry = str | ResearchSource

# 免責文 (全動画一律)。説明欄末尾 (使用音声クレジット = footer の直前) に挿入する。
MEDICAL_DISCLAIMER = "※本動画は一般的な情報提供を目的としており、医学的助言ではありません。"


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


def _append_section_heading(lines: List[str], heading: str, below_blank_lines: int = 0) -> None:
    """見出し前は2行、見出し後は0〜1行の空行で見出しを追加する。"""
    while lines and lines[-1] == "":
        lines.pop()
    lines.extend(["", "", heading])

    if below_blank_lines not in (0, 1):
        raise ValueError("below_blank_lines must be 0 or 1")

    lines.extend([""] * below_blank_lines)


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


def normalize_hashtags(
    dynamic_tags: List[str],
    fixed_tags: List[str],
    max_total: int = 60,
) -> List[str]:
    """テーマ由来タグ先頭 + 固定タグ末尾の # 付きハッシュタグ列を構築する。

    - # 未付与のタグには # を付与する (既に付いていれば二重付与しない)
    - 順序: dynamic (テーマ由来) → fixed (固定)。YouTube はタイトル上に
      先頭 3 つを表示するため、動画ごとに変わるテーマ由来タグを先頭に置く
    - YouTube 仕様 (ハッシュタグ 60 個超で全タグ無効) に合わせ、
      合計が max_total を超える分は末尾から落とす
    """
    def _hashify(tag: str) -> str:
        value = (tag or "").strip()
        if not value:
            return ""
        return value if value.startswith("#") else f"#{value}"

    merged = _normalize_non_empty([_hashify(t) for t in [*dynamic_tags, *fixed_tags]])
    return merged[:max_total]


def format_reference_text_lines(references: List[ReferenceEntry]) -> List[str]:
    """metadata.txt 向けの「タイトル + 日付 + URL」参考文献行を構築する。

    1 文献 2 行 (見出し行 + URL 行) + 区切り空行:
        参考文献1: 環状オリゴ糖の脂質吸収抑制効果(2026-06-28)
        https://...
    published_date が無いソースは日付を省略 (空カッコを出さない)。
    title が無いソースは現行どおり「参考文献N + URL」のみ。
    """
    lines: List[str] = []
    for idx, ref in enumerate(_normalize_references(references), start=1):
        if isinstance(ref, ResearchSource):
            title = (ref.title or "").strip()
            heading = f"参考文献{idx}: {title}" if title else f"参考文献{idx}"
            published = (getattr(ref, "published_date", None) or "").strip()
            if published:
                heading = f"{heading}({published})"
            url = (ref.url or "").strip()
        else:
            heading = f"参考文献{idx}"
            url = (ref or "").strip()
        lines.append(heading)
        lines.append(url)
        lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def build_video_description(
    script_description: str,
    chapters: List[str],
    references: List[ReferenceEntry],
    dynamic_tags: List[str],
    fixed_tags: List[str],
    footer_text: str,
    llm_model_info: str = "",
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
    9. llm_model_info (使用モデル情報)
    10. <空行>
    11. footer_text
    """
    description_text = (script_description or "").strip() or "（概要未設定）"
    chapter_lines = _normalize_non_empty(chapters)
    reference_lines = _normalize_references(references)

    # 2026-07-17: # 付与 + テーマ由来先頭/固定末尾 + 60 個上限の正規化に変更
    merged_tags = normalize_hashtags(dynamic_tags, fixed_tags)
    footer = (footer_text or "").strip() or "（フッター未設定）"

    lines: List[str] = ["【動画の概要】", description_text]

    _append_section_heading(lines, "【目次】", below_blank_lines=0)
    if chapter_lines:
        lines.extend(chapter_lines)
    else:
        lines.append("- チャプター情報なし")
    _append_section_heading(lines, "【参考文献】", below_blank_lines=0)
    if reference_lines:
        for idx, ref in enumerate(reference_lines, start=1):
            if isinstance(ref, ResearchSource):
                title = (ref.title or "").strip() or f"参考文献{idx}"
                # published_date があればタイトル行に付与 (無ければ日付を省略し
                # 空カッコを出さない)。1 文献 2 行 (タイトル + URL) を維持する
                published = (getattr(ref, "published_date", None) or "").strip()
                if published:
                    title = f"{title}({published})"
                url = (ref.url or "").strip()
                lines.append(f"📄 {title}")
                lines.append(f"🔗 {url}")
                lines.append("")  # 3行構造の3行目（空行）
            else:
                # 文字列（URL）の場合
                lines.append(f"📄 参考文献{idx}")
                lines.append(f"🔗 {ref}")
                lines.append("")  # 3行構造の3行目（空行）
    else:
        lines.append("- 参考文献なし")
    _append_section_heading(lines, "【タグ】", below_blank_lines=0)
    if merged_tags:
        lines.append(" ".join(merged_tags))
    else:
        lines.append("#ラジオ")

    # 使用モデル情報を追加（存在する場合）
    if llm_model_info:
        lines.append("")
        lines.append("")
        lines.append(llm_model_info)

    # 免責文 (全動画一律)。footer = 使用音声クレジットの直前に置く
    lines.append("")
    lines.append(MEDICAL_DISCLAIMER)
    lines.append("")
    lines.append(footer)

    # 最終的なサニタイズと検証
    final_text = "\n".join(lines).strip()
    final_text = sanitize_for_youtube(final_text, max_length=5000)
    final_text = final_text.strip()
    
    # チャプター形式の検証
    if chapter_lines and not validate_chapter_format(chapter_lines):
        logger.warning("チャプター形式がYouTubeに認識されない可能性があります")

    return final_text
