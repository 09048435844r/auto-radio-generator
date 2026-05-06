"""VoicevoxClient._get_chapter_title / _build_chapters の視聴者向けタイトル変換テスト

2026-05-06: チャプター名が segment_type の内部名（"オープニング" / "deep_dive" /
"deep_dive 解説"）として漏れていた問題への回帰テスト。

期待する変換ルール:
- intro / オープニング系 → 「はじめに」
- deep_dive / deep_dive_N → そのセグメントの ScriptSegment.topic_title
  （= CuratedTopic.title）。topic_title が無い場合は legacy の固定マッピングへ
- conclusion / ending / まとめ系 → 「まとめ」
- DialogueTurn.chapter_title が AI 生成で付いていれば最優先
"""
from unittest.mock import MagicMock

import pytest

from core.models.script import Script, DialogueTurn, TurnType
from core.models.curation import ScriptSegment


def _seg(segment_id: str, segment_type: str, topic_title=None, turns_count: int = 2) -> ScriptSegment:
    return ScriptSegment(
        segment_id=segment_id,
        segment_type=segment_type,  # type: ignore[arg-type]
        topic_title=topic_title,
        turns=[{"speaker": "A", "text": f"x{i}"} for i in range(turns_count)],
        context_summary="",
    )


def _make_client():
    """VoicevoxClient を実 init を回避して構築（音声合成 API には触れない）"""
    from services.audio_synthesis.voicevox_client import VoicevoxClient
    # __init__ は AppConfig 必須なので、未初期化インスタンスを作成して
    # チャプター生成ヘルパーだけテストする（_get_chapter_title / _build_*chapters は state を使わない）
    client = VoicevoxClient.__new__(VoicevoxClient)
    return client


# ---------------------------------------------------------------------------
# _get_chapter_title: 優先度1 (DialogueTurn.chapter_title) は最優先
# ---------------------------------------------------------------------------

def test_get_chapter_title_dialogue_chapter_title_takes_priority():
    client = _make_client()
    title = client._get_chapter_title(
        section_id="deep_dive",
        text="...",
        chapter_title="AI生成タイトル",
        topic_title="無視されるべきトピック",
    )
    assert title == "AI生成タイトル"


# ---------------------------------------------------------------------------
# _get_chapter_title: intro / オープニング系 → 「はじめに」
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("section_id", ["intro", "INTRO", "intro_main", "opening", "オープニング"])
def test_get_chapter_title_intro_family_maps_to_hajime(section_id):
    client = _make_client()
    assert client._get_chapter_title(section_id=section_id, text="hello") == "はじめに"


# ---------------------------------------------------------------------------
# _get_chapter_title: conclusion / ending / まとめ系 → 「まとめ」
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("section_id", ["conclusion", "ending", "closing", "conclusion_part2", "まとめ"])
def test_get_chapter_title_conclusion_family_maps_to_matome(section_id):
    client = _make_client()
    assert client._get_chapter_title(section_id=section_id, text="bye") == "まとめ"


# ---------------------------------------------------------------------------
# _get_chapter_title: deep_dive 系 + topic_title → トピックタイトル
# ---------------------------------------------------------------------------

def test_get_chapter_title_deep_dive_with_topic_title_uses_topic():
    client = _make_client()
    title = client._get_chapter_title(
        section_id="deep_dive",
        text="本題",
        topic_title="AI界の45億ドル巨人",
    )
    assert title == "AI界の45億ドル巨人"


def test_get_chapter_title_deep_dive_n_with_topic_title_uses_topic():
    client = _make_client()
    title = client._get_chapter_title(
        section_id="deep_dive_2",
        text="第2部",
        topic_title="CGM精度問題と血糖値測定誤差",
    )
    assert title == "CGM精度問題と血糖値測定誤差"


def test_get_chapter_title_deep_dive_falls_back_when_no_topic_title():
    """topic_title が空 / None の場合は legacy 固定マッピングへフォールバック"""
    client = _make_client()
    # deep_dive (segment_type) → そのまま section_id 文字列が返る（マッピング無し）
    assert client._get_chapter_title(section_id="deep_dive", text="x", topic_title=None) == "deep_dive"
    # deep_dive_1 → "深掘り1"（legacy 固定マッピング）
    assert client._get_chapter_title(section_id="deep_dive_1", text="x", topic_title=None) == "深掘り1"
    assert client._get_chapter_title(section_id="deep_dive_1", text="x", topic_title="") == "深掘り1"


# ---------------------------------------------------------------------------
# _get_chapter_title: その他の section は legacy 固定マッピング維持
# ---------------------------------------------------------------------------

def test_get_chapter_title_legacy_news_mapping_unchanged():
    client = _make_client()
    title = client._get_chapter_title(section_id="news_1", text="速報: 何かが起きた")
    assert "ニュース1" in title
    assert "速報: 何かが起きた" in title


def test_get_chapter_title_unknown_section_returns_section_id():
    client = _make_client()
    assert client._get_chapter_title(section_id="random_xyz", text="x") == "random_xyz"


# ---------------------------------------------------------------------------
# _build_segment_index_map
# ---------------------------------------------------------------------------

def _make_script(section_pattern: list[str]) -> Script:
    """指定の section リストで Script を作成（dialogue 数 = section_pattern 長）"""
    turns = [
        DialogueTurn(speaker="A", text=f"line{i}", turn_type=TurnType.DIALOGUE, section=sec)
        for i, sec in enumerate(section_pattern)
    ]
    while len(turns) < 10:
        turns.append(
            DialogueTurn(speaker="A", text="pad", turn_type=TurnType.DIALOGUE)
        )
    return Script(
        title="t",
        thumbnail_title="th",
        sections=turns,
    )


def test_build_segment_index_map_returns_empty_when_segments_none():
    from services.audio_synthesis.voicevox_client import VoicevoxClient

    script = _make_script(["intro"] * 10)
    assert VoicevoxClient._build_segment_index_map(script, None) == []


def test_build_segment_index_map_returns_empty_on_count_mismatch():
    from services.audio_synthesis.voicevox_client import VoicevoxClient

    script = _make_script(["intro"] * 10)  # 10 dialogue lines
    segments = [_seg("intro", "intro", turns_count=5)]  # only 5 turns
    assert VoicevoxClient._build_segment_index_map(script, segments) == []


def test_build_segment_index_map_maps_each_index_to_owner_segment():
    from services.audio_synthesis.voicevox_client import VoicevoxClient

    # 10 dialogue lines split: 3 intro + 4 deep_dive_1 + 3 conclusion
    script = _make_script(
        ["intro"] * 3 + ["deep_dive"] * 4 + ["conclusion"] * 3
    )
    segments = [
        _seg("intro", "intro", turns_count=3),
        _seg("deep_dive_1", "deep_dive", topic_title="トピックA", turns_count=4),
        _seg("conclusion", "conclusion", turns_count=3),
    ]
    seg_for_idx = VoicevoxClient._build_segment_index_map(script, segments)
    assert len(seg_for_idx) == 10
    assert all(s.segment_id == "intro" for s in seg_for_idx[:3])
    assert all(s.segment_id == "deep_dive_1" for s in seg_for_idx[3:7])
    assert all(s.segment_id == "conclusion" for s in seg_for_idx[7:])


# ---------------------------------------------------------------------------
# _build_chapters: end-to-end with segments
# ---------------------------------------------------------------------------

def _phrase_data_for(script: Script, ms_per_line: int = 1000) -> list:
    """各 dialogue line に等間隔タイミングを与えた phrase_data を生成"""
    phrase_data = []
    cursor = 0
    for line in script.get_dialogue_only():
        start = cursor
        end = cursor + ms_per_line
        phrase_data.append((MagicMock(), start, end, line.text or "", line.speaker or "A"))
        cursor = end
    return phrase_data


def test_build_chapters_uses_topic_title_for_deep_dive_segments():
    """3 つの deep_dive セグメント each with own topic_title → 3 個の独立チャプター"""
    client = _make_client()
    script = _make_script(
        # 各 deep_dive 区間は同じ section="deep_dive" を共有（実運用パターン）
        ["intro"] * 2
        + ["deep_dive"] * 3
        + ["deep_dive"] * 3
        + ["deep_dive"] * 3
        + ["conclusion"] * 2
    )
    segments = [
        _seg("intro", "intro", turns_count=2),
        _seg("deep_dive_1", "deep_dive", topic_title="AI界の45億ドル巨人", turns_count=3),
        _seg("deep_dive_2", "deep_dive", topic_title="CGM精度問題", turns_count=3),
        _seg("deep_dive_3", "deep_dive", topic_title="量子計算の現在", turns_count=3),
        _seg("conclusion", "conclusion", turns_count=2),
    ]
    phrase_data = _phrase_data_for(script)
    chapters = client._build_chapters(phrase_data, script, segments=segments)

    titles = [c.title for c in chapters]
    assert titles == [
        "はじめに",
        "AI界の45億ドル巨人",
        "CGM精度問題",
        "量子計算の現在",
        "まとめ",
    ]


def test_build_chapters_falls_back_to_legacy_when_segments_none():
    """segments=None なら従来の line.section ベースの動作にフォールバック"""
    client = _make_client()
    script = _make_script(["intro"] * 2 + ["deep_dive_1"] * 2 + ["conclusion"] * 2 + ["pad"] * 4)
    phrase_data = _phrase_data_for(script)
    chapters = client._build_chapters(phrase_data, script, segments=None)

    titles = [c.title for c in chapters]
    # 新変換ルール（intro→はじめに、conclusion→まとめ）は適用される
    # deep_dive_1 は topic_title が無いので legacy "深掘り1"
    assert "はじめに" in titles
    assert "深掘り1" in titles
    assert "まとめ" in titles


def test_build_chapters_dedup_by_segment_id_not_section():
    """同じ section="deep_dive" でも segment_id が違えば別チャプターとして出る"""
    client = _make_client()
    # 10 dialogue (5 + 5)、セクションは全て同じ "deep_dive" を共有
    script = _make_script(["deep_dive"] * 5 + ["deep_dive"] * 5)
    segments = [
        _seg("deep_dive_1", "deep_dive", topic_title="topicA", turns_count=5),
        _seg("deep_dive_2", "deep_dive", topic_title="topicB", turns_count=5),
    ]
    phrase_data = _phrase_data_for(script)
    chapters = client._build_chapters(phrase_data, script, segments=segments)
    titles = [c.title for c in chapters]
    assert titles == ["topicA", "topicB"]


def test_build_chapters_returns_empty_for_empty_inputs():
    client = _make_client()
    script = _make_script(["intro"] * 10)
    assert client._build_chapters([], script) == []
    assert client._build_chapters([(MagicMock(), 0, 1, "", "A")], None) == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _build_mock_chapters
# ---------------------------------------------------------------------------

def test_build_mock_chapters_uses_topic_title_when_segments_provided():
    client = _make_client()
    # 全 10 dialogue を segments で全カバー（index_map が成立する条件）
    script = _make_script(["intro"] * 3 + ["deep_dive"] * 4 + ["conclusion"] * 3)
    segments = [
        _seg("intro", "intro", turns_count=3),
        _seg("deep_dive_1", "deep_dive", topic_title="モックでも適用", turns_count=4),
        _seg("conclusion", "conclusion", turns_count=3),
    ]
    chapters = client._build_mock_chapters(script, total_duration_sec=60.0, segments=segments)

    # _build_mock_chapters は dedup なしなので全 line に対して chapter を作る挙動を維持
    titles = [c.title for c in chapters]
    assert "はじめに" in titles
    assert "モックでも適用" in titles
    assert "まとめ" in titles
    # 旧内部名がリークしていないこと
    assert "deep_dive" not in titles
    assert "オープニング" not in titles
