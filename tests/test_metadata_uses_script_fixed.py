"""metadata 生成で FactFix 修正済み script_fixed.json を優先利用することの回帰テスト

FactChecker / FactFixAgent が script_fixed.json を生成しても、
workflow._generate_youtube_metadata が常に原文 script を使ってしまい、
ハルシネーション内容が YouTube 概要欄に載る本運用バグへの修正検証。

担保する内容:
  1. workflow._resolve_script_for_metadata が script_fixed.json 存在時に
     FactFix 後の Script を返す
  2. script_fixed.json 不在時は fallback Script をそのまま返す
  3. script_fixed.json が壊れている場合はフェイルオープンで fallback を返す
  4. 構造的契約: workflow.py の両方の _generate_youtube_metadata 呼び出し前に
     _resolve_script_for_metadata 経由で effective_script を解決している
"""
import re
from pathlib import Path

import pytest

from core.models.script import Script, DialogueTurn, TurnType
from workflow import _resolve_script_for_metadata


WORKFLOW_SRC_PATH = Path(__file__).resolve().parent.parent / "workflow.py"


def _make_script(suffix: str) -> Script:
    """テスト用の最小 Script。サフィックスでテキストを差別化して fixed/orig を区別する。"""
    turns = [
        DialogueTurn(
            speaker="A",
            text=f"line{i}_{suffix}",
            turn_type=TurnType.DIALOGUE,
            section="intro" if i < 5 else "deep_dive",
        )
        for i in range(10)
    ]
    return Script(
        title=f"title_{suffix}",
        thumbnail_title=f"thumb_{suffix}",
        sections=turns,
    )


# ---------------------------------------------------------------------------
# (1) _resolve_script_for_metadata 単体: 動作レベル
# ---------------------------------------------------------------------------

def test_resolver_returns_fixed_script_when_present(tmp_path: Path):
    """script_fixed.json が存在すれば修正版 Script を返す"""
    fixed = _make_script("FIXED")
    (tmp_path / "script_fixed.json").write_text(
        fixed.model_dump_json(indent=2), encoding="utf-8"
    )

    fallback = _make_script("ORIGINAL")
    result = _resolve_script_for_metadata(tmp_path, fallback)

    # FIXED が返ってきていること（ORIGINAL ではない）
    assert result.title == "title_FIXED"
    assert any("FIXED" in (t.text or "") for t in result.sections)
    assert not any("ORIGINAL" in (t.text or "") for t in result.sections)


def test_resolver_returns_fallback_when_fixed_absent(tmp_path: Path):
    """script_fixed.json が無ければ fallback をそのまま返す（FactFix 未実行 / 修正対象なしのケース）"""
    fallback = _make_script("ORIGINAL")
    result = _resolve_script_for_metadata(tmp_path, fallback)
    assert result is fallback
    assert result.title == "title_ORIGINAL"


def test_resolver_failopens_on_corrupt_fixed_json(tmp_path: Path):
    """script_fixed.json が壊れていてもフォールバック側で続行する（フェイルオープン）"""
    (tmp_path / "script_fixed.json").write_text("not valid json", encoding="utf-8")

    fallback = _make_script("ORIGINAL")
    result = _resolve_script_for_metadata(tmp_path, fallback)
    assert result is fallback


def test_resolver_logs_choice_when_log_fn_provided(tmp_path: Path):
    """log_fn が渡されたとき、選択結果（fixed 採用 / 不在 / 失敗）に応じてログを出す"""
    fixed = _make_script("FIXED")
    (tmp_path / "script_fixed.json").write_text(
        fixed.model_dump_json(), encoding="utf-8"
    )

    captured: list[str] = []

    def _log(msg: str):
        captured.append(msg)

    _resolve_script_for_metadata(tmp_path, _make_script("ORIGINAL"), log_fn=_log)
    assert any("修正済み" in m or "script_fixed" in m for m in captured), captured

    # 不在ケース
    captured.clear()
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    _resolve_script_for_metadata(empty_dir, _make_script("ORIGINAL"), log_fn=_log)
    assert any("script_fixed.json なし" in m or "原文" in m for m in captured), captured


def test_resolver_works_without_log_fn(tmp_path: Path):
    """log_fn=None でも例外を出さずに動く（既存の log を意識しないコードパス）"""
    fallback = _make_script("ORIGINAL")
    # 例外が出ないことだけ確認
    result = _resolve_script_for_metadata(tmp_path, fallback)
    assert result is fallback


# ---------------------------------------------------------------------------
# (2) 構造的契約: workflow.py の両方の _generate_youtube_metadata 呼び出し前に
#     _resolve_script_for_metadata が使われている
# ---------------------------------------------------------------------------

def test_metadata_call_sites_route_through_resolver():
    """workflow.py 内の `_generate_youtube_metadata(...)` 呼び出しの直前で
    `_resolve_script_for_metadata` が呼ばれていること（両方の call site で）。

    これが無いと回帰: FactFix 修正版があっても原文 script から metadata.txt が
    生成されハルシネーション内容が YouTube 説明文に載る。
    """
    src = WORKFLOW_SRC_PATH.read_text(encoding="utf-8")

    # `_generate_youtube_metadata(` の登場回数（定義 1 + 呼び出し N）
    call_sites = list(re.finditer(r"_generate_youtube_metadata\s*\(", src))
    # 定義 1 件 + 呼び出し 2 件 = 3 件のはず
    assert len(call_sites) >= 3, (
        f"_generate_youtube_metadata の出現箇所が想定より少ない: {len(call_sites)} 件"
    )

    # 関数定義行（def _generate_youtube_metadata...）を除いた呼び出し位置を取得
    call_positions = [
        m.start() for m in call_sites
        if not src[max(0, m.start() - 40):m.start()].rstrip().endswith("def")
    ]
    assert len(call_positions) == 2, (
        f"_generate_youtube_metadata の呼び出し回数が想定 2 件と異なる: {len(call_positions)}"
    )

    # 各呼び出しの直前 ~600 文字以内に _resolve_script_for_metadata が出現すること
    for pos in call_positions:
        window = src[max(0, pos - 600):pos]
        assert "_resolve_script_for_metadata" in window, (
            f"_generate_youtube_metadata 呼び出し（位置 {pos}）の直前 600 文字以内に "
            f"_resolve_script_for_metadata が無い。FactFix 後の script を使う処理が"
            f"抜けている可能性。\n直前の窓:\n{window[-300:]}"
        )


def test_resolver_helper_exists_in_workflow():
    """workflow.py に _resolve_script_for_metadata 関数が定義されている"""
    src = WORKFLOW_SRC_PATH.read_text(encoding="utf-8")
    assert re.search(r"def\s+_resolve_script_for_metadata\s*\(", src), (
        "workflow.py に _resolve_script_for_metadata 関数定義がない"
    )
