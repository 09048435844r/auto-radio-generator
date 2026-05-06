"""metadata.txt YouTube チャプターセクション生成テスト

2026-05-06: metadata.txt の YouTube チャプター部が空 or 内容薄になっていた問題への
回帰テスト。`_format_chapter_lines` の YouTube 互換出力（0:00 起点 / H:MM:SS） と
`_build_metadata_chapter_block` の section 構成を担保する。
"""
from core.interfaces import ChapterMarker

from workflow import (
    _build_metadata_chapter_block,
    _format_chapter_lines,
)


def _ch(start_sec: float, title: str, section_id: str = "section") -> ChapterMarker:
    return ChapterMarker(start_time_sec=start_sec, title=title, section_id=section_id)


# ---------------------------------------------------------------------------
# _format_chapter_lines: YouTube 互換出力
# ---------------------------------------------------------------------------

def test_format_chapter_lines_returns_empty_for_no_chapters():
    assert _format_chapter_lines([]) == []
    assert _format_chapter_lines(None) == []  # type: ignore[arg-type]


def test_format_chapter_lines_first_chapter_forced_to_zero():
    """先頭は実時間 (例 2.0s) でも 0:00 に正規化される（YouTube 必須仕様）"""
    chapters = [
        _ch(2.4, "はじめに", "intro"),
        _ch(60.0, "トピックA", "deep_dive_1"),
        _ch(180.0, "まとめ", "conclusion"),
    ]
    lines = _format_chapter_lines(chapters)
    assert lines[0] == "0:00 はじめに"
    assert lines[1] == "1:00 トピックA"
    assert lines[2] == "3:00 まとめ"


def test_format_chapter_lines_uses_mmss_for_short_videos():
    """1時間未満なら MM:SS 形式（H 部分なし）"""
    chapters = [
        _ch(0, "オープニング"),
        _ch(125, "本編"),
        _ch(3500, "終盤"),  # 58:20
    ]
    lines = _format_chapter_lines(chapters)
    assert lines == [
        "0:00 オープニング",
        "2:05 本編",
        "58:20 終盤",
    ]


def test_format_chapter_lines_uses_h_mm_ss_when_over_one_hour():
    """1時間以上の動画は全行 H:MM:SS にスイッチ"""
    chapters = [
        _ch(0, "はじめに"),
        _ch(1830, "本編1"),       # 30:30
        _ch(3661, "本編2"),       # 1:01:01
    ]
    lines = _format_chapter_lines(chapters)
    assert lines == [
        "0:00:00 はじめに",
        "0:30:30 本編1",
        "1:01:01 本編2",
    ]


def test_format_chapter_lines_dedup_consecutive_duplicate_titles():
    """同じタイトルが連続する場合は最初の1回だけ残す（重複防止）"""
    chapters = [
        _ch(0, "はじめに"),
        _ch(20, "はじめに"),  # 連続重複
        _ch(60, "本編"),
        _ch(120, "本編"),     # 連続重複
        _ch(180, "まとめ"),
    ]
    lines = _format_chapter_lines(chapters)
    assert lines == [
        "0:00 はじめに",
        "1:00 本編",
        "3:00 まとめ",
    ]


def test_format_chapter_lines_sorts_unsorted_input():
    """start_time_sec が昇順でなくても並べ替えて出力する"""
    chapters = [
        _ch(180, "まとめ"),
        _ch(0, "はじめに"),
        _ch(60, "本編"),
    ]
    lines = _format_chapter_lines(chapters)
    assert lines == [
        "0:00 はじめに",
        "1:00 本編",
        "3:00 まとめ",
    ]


def test_format_chapter_lines_handles_negative_start_time_safely():
    """異常値（負の秒数）が来ても 0 にクランプして落ちない"""
    chapters = [
        _ch(-5, "壊れたチャプター"),
        _ch(60, "正常"),
    ]
    lines = _format_chapter_lines(chapters)
    # 先頭は強制 0:00、2 件目は通常
    assert lines[0] == "0:00 壊れたチャプター"
    assert lines[1] == "1:00 正常"


# ---------------------------------------------------------------------------
# _build_metadata_chapter_block: metadata.txt 用 section 組み立て
# ---------------------------------------------------------------------------

def test_build_metadata_chapter_block_returns_empty_when_no_chapters():
    assert _build_metadata_chapter_block([]) == []
    assert _build_metadata_chapter_block(None) == []  # type: ignore[arg-type]


def test_build_metadata_chapter_block_emits_full_section():
    """ヘッダ + 案内 + 空行 + チャプター行 + 末尾空行 の構造を持つ"""
    chapters = [
        _ch(2.0, "はじめに", "intro"),
        _ch(63.5, "AI界の45億ドル巨人", "deep_dive_1"),
        _ch(245.0, "CGM精度問題", "deep_dive_2"),
        _ch(412.0, "量子計算", "deep_dive_3"),
        _ch(580.0, "まとめ", "conclusion"),
    ]
    block = _build_metadata_chapter_block(chapters)

    # ヘッダ
    assert block[0] == "【YouTubeチャプター】"
    assert "概要欄" in block[1] and "目次" in block[1]
    assert block[2] == ""

    # チャプター本体（先頭は 0:00 強制）
    assert block[3] == "0:00 はじめに"
    assert block[4] == "1:03 AI界の45億ドル巨人"
    assert block[5] == "4:05 CGM精度問題"
    assert block[6] == "6:52 量子計算"
    assert block[7] == "9:40 まとめ"

    # 末尾は空行で次セクションへ余白を残す
    assert block[-1] == ""


def test_build_metadata_chapter_block_does_not_leak_internal_segment_names():
    """内部 segment_id/segment_type が漏れていないこと（前タスク連動回帰防止）"""
    chapters = [
        _ch(0, "はじめに", "intro"),
        _ch(60, "AIの最前線", "deep_dive_1"),
        _ch(180, "まとめ", "conclusion"),
    ]
    block = _build_metadata_chapter_block(chapters)
    joined = "\n".join(block)

    # 視聴者向けタイトルは含まれる
    assert "はじめに" in joined
    assert "AIの最前線" in joined
    assert "まとめ" in joined
    # 内部名は出ない
    assert "deep_dive" not in joined
    assert "intro" not in joined.replace("はじめに", "")  # "はじめに" 由来は除外
    assert "conclusion" not in joined


def test_build_metadata_chapter_block_dedup_applied():
    """ブロック化前に dedup が走るので、同タイトル連続は1件に圧縮される"""
    chapters = [
        _ch(0, "はじめに"),
        _ch(30, "はじめに"),
        _ch(60, "本編"),
    ]
    block = _build_metadata_chapter_block(chapters)
    timestamp_lines = [l for l in block if l and l[0].isdigit()]
    assert timestamp_lines == ["0:00 はじめに", "1:00 本編"]
