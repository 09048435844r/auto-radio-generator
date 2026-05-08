"""RadioDirectorScriptLoader のテスト

Step 3 外部台本モード化の commit 3。Mac 側 radio_director (Step 1 完了) が生成する
VerifiedScript JSON を Windows 側 Script に変換する loader の挙動を担保する。

Acceptance Criteria 対応:
- 仕様 §5.1.3 references=[] 正常系
- 仕様 §5.2.4 Mac 側 fixture が Windows 側 loader で読める
"""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.models.script import Script
from services.script_loading import RadioDirectorScriptLoader
from services.script_loading.radio_director_loader import build_script_segments


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "verified_script_sample.json"


# ---------------------------------------------------------------------------
# (1) Mac 側 fixture が読み込める (§5.2.4)
# ---------------------------------------------------------------------------

def test_loader_reads_mac_side_fixture():
    """添付 fixture (Mac 側 radio_director から取得) が ValidationError を起こさず Script に変換される"""
    loader = RadioDirectorScriptLoader()
    script = loader.load(FIXTURE_PATH)

    assert isinstance(script, Script)
    assert script.title  # 非空
    assert script.thumbnail_title  # 非空
    assert script.description  # 非空


# ---------------------------------------------------------------------------
# (2) Script.sections は全 segments × all turns を平坦化したもの
# ---------------------------------------------------------------------------

def test_loader_flattens_all_turns():
    """fixture の 5 segments すべての turns が Script.sections に含まれる"""
    loader = RadioDirectorScriptLoader()
    script = loader.load(FIXTURE_PATH)

    # 元 JSON の turn 総数を確認
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    expected_turns = sum(len(seg["turns"]) for seg in raw["script"]["segments"])

    # Script.sections は DIALOGUE turn のみで構成される
    dialogue_turns = [s for s in script.sections if s.is_dialogue()]
    assert len(dialogue_turns) == expected_turns


# ---------------------------------------------------------------------------
# (3) 各 segment の先頭 turn に section + chapter_title が付与される
# ---------------------------------------------------------------------------

def test_loader_marks_segment_boundaries_on_first_turn():
    """各 segment の最初の turn に section + chapter_title が付き、
    後続 turn には付いていない"""
    loader = RadioDirectorScriptLoader()
    script = loader.load(FIXTURE_PATH)

    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    expected_marks = []  # (cumulative_index, segment_type, segment_title)
    cumulative = 0
    for seg in raw["script"]["segments"]:
        expected_marks.append((cumulative, seg["segment_type"], seg["title"]))
        cumulative += len(seg["turns"])

    for first_idx, seg_type, seg_title in expected_marks:
        dt = script.sections[first_idx]
        assert dt.section == seg_type, f"index {first_idx}: section 不一致"
        assert dt.chapter_title == seg_title, f"index {first_idx}: chapter_title 不一致"

    # 各 segment の 2 つ目以降の turn は section/chapter_title が None
    for first_idx, seg_type, _ in expected_marks:
        # 同じ segment 内の 2 番目（存在すれば）を確認
        next_idx = first_idx + 1
        if next_idx >= len(script.sections):
            continue
        # 次 segment の境界でないことを確認するため、対応する元 turns 数を見る
        # （ここでは「次 turn がまだ同じ segment 内」のケースでのみ assert）
        seg = next(s for s in raw["script"]["segments"] if s["segment_type"] == seg_type)
        if len(seg["turns"]) > 1:
            dt2 = script.sections[next_idx]
            assert dt2.section is None
            assert dt2.chapter_title is None
            break  # 1 件確認で十分


# ---------------------------------------------------------------------------
# (4) metadata の各フィールドが Script に転写される
# ---------------------------------------------------------------------------

def test_loader_copies_metadata_fields():
    loader = RadioDirectorScriptLoader()
    script = loader.load(FIXTURE_PATH)

    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    md = raw["metadata"]
    assert script.title == md["title"]
    assert script.thumbnail_title == md["thumbnail_title"]
    assert script.description == md["description"]
    assert list(script.hashtags) == list(md["hashtags"])


# ---------------------------------------------------------------------------
# (5) references=[] 正常系 (§4.4 既知制約 / §5.1.3)
# ---------------------------------------------------------------------------

def test_loader_handles_empty_references():
    """fixture は references=[] 状態。loader は空配列を Script.references=[] として通す"""
    loader = RadioDirectorScriptLoader()
    script = loader.load(FIXTURE_PATH)
    assert script.references == []


# ---------------------------------------------------------------------------
# (6) references が非空のとき HttpUrl が str 化される
# ---------------------------------------------------------------------------

def test_loader_converts_references_to_url_strings(tmp_path: Path):
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    raw["metadata"]["references"] = [
        {"url": "https://example.com/a", "title": "A", "tier": "AAA"},
        {"url": "https://example.org/b", "title": None, "tier": "B"},
    ]
    p = tmp_path / "vs_with_refs.json"
    p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    loader = RadioDirectorScriptLoader()
    script = loader.load(p)
    assert all(isinstance(r, str) for r in script.references)
    # HttpUrl が str に変換されると末尾 '/' が付く可能性があるが、ホスト・パスの主要部分は保持される
    assert any("example.com/a" in r for r in script.references)
    assert any("example.org/b" in r for r in script.references)


# ---------------------------------------------------------------------------
# (7) ファイル不存在で FileNotFoundError
# ---------------------------------------------------------------------------

def test_loader_raises_filenotfound_for_missing_path(tmp_path: Path):
    loader = RadioDirectorScriptLoader()
    with pytest.raises(FileNotFoundError):
        loader.load(tmp_path / "does_not_exist.json")


# ---------------------------------------------------------------------------
# (8) 不正 JSON で ValidationError (silent fallback 禁止 §3.4)
# ---------------------------------------------------------------------------

def test_loader_raises_validation_error_for_corrupt_json(tmp_path: Path):
    p = tmp_path / "broken.json"
    p.write_text('{"script": "not an object"}', encoding="utf-8")
    loader = RadioDirectorScriptLoader()
    with pytest.raises(ValidationError):
        loader.load(p)


# ---------------------------------------------------------------------------
# (9) スキーマ違反 (segment_type 未定義値) で ValidationError
# ---------------------------------------------------------------------------

def test_loader_raises_for_invalid_segment_type(tmp_path: Path):
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    raw["script"]["segments"][0]["segment_type"] = "bonus_round"  # NG: Literal 範囲外
    p = tmp_path / "vs_bad_segment_type.json"
    p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    loader = RadioDirectorScriptLoader()
    with pytest.raises(ValidationError, match="segment_type"):
        loader.load(p)


# ---------------------------------------------------------------------------
# (10) Script の min_length=10 制約: fixture は十分大きい (5 segments、合計 >50 turns)
# ---------------------------------------------------------------------------

def test_loader_satisfies_script_min_sections():
    loader = RadioDirectorScriptLoader()
    script = loader.load(FIXTURE_PATH)
    # Script.sections は min_length=10
    assert len(script.sections) >= 10


# ---------------------------------------------------------------------------
# (11) build_script_segments helper: segment_id を deep_dive_N 形式で連番
# ---------------------------------------------------------------------------

def test_build_script_segments_assigns_deep_dive_indices():
    from core.models.verified_script import VerifiedScript
    raw_text = FIXTURE_PATH.read_text(encoding="utf-8")
    vs = VerifiedScript.model_validate_json(raw_text)
    segments = build_script_segments(vs)

    # 5 segments 想定: intro / deep_dive_1 / deep_dive_2 / deep_dive_3 / conclusion
    ids = [s.segment_id for s in segments]
    assert ids[0] == "intro"
    deep_dive_ids = [i for i in ids if i.startswith("deep_dive_")]
    # deep_dive_N が連番
    assert deep_dive_ids == [f"deep_dive_{i}" for i in range(1, len(deep_dive_ids) + 1)]
    assert ids[-1] == "conclusion"


# ---------------------------------------------------------------------------
# (12) build_script_segments: topic_title が segment.title と一致 (chapter rendering 用)
# ---------------------------------------------------------------------------

def test_build_script_segments_topic_title_matches_segment_title():
    from core.models.verified_script import VerifiedScript
    raw_text = FIXTURE_PATH.read_text(encoding="utf-8")
    vs = VerifiedScript.model_validate_json(raw_text)
    segments = build_script_segments(vs)

    for ss, vs_seg in zip(segments, vs.script.segments):
        assert ss.topic_title == vs_seg.title


# ---------------------------------------------------------------------------
# (13) build_script_segments: turns は List[dict] で speaker/text を保持
# ---------------------------------------------------------------------------

def test_build_script_segments_turns_are_dict_format():
    from core.models.verified_script import VerifiedScript
    raw_text = FIXTURE_PATH.read_text(encoding="utf-8")
    vs = VerifiedScript.model_validate_json(raw_text)
    segments = build_script_segments(vs)

    for ss in segments:
        assert isinstance(ss.turns, list)
        for t in ss.turns:
            assert isinstance(t, dict)
            assert "speaker" in t
            assert "text" in t
        # 先頭 turn には section/chapter_title が付く
        assert ss.turns[0].get("section") in ("intro", "deep_dive", "conclusion")
        assert ss.turns[0].get("chapter_title")
