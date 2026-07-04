"""workflow._run_metadata_phase の単体テスト（Phase 4 分解 E1 / 案1）。

_run_phases から抽出したメタデータ生成フェーズ。mock スキップ挙動、外部台本モード
での dict 生成（LLM 非呼び出し）、および mock スキップ時に external_phase_result が
None でも安全であること（.pre_built_metadata へ非アクセス）を検証する。
"""
from pathlib import Path
from types import SimpleNamespace

from core.models.script import DialogueTurn, Script, TurnType
from workflow import _run_metadata_phase


def _make_script() -> Script:
    turns = [
        DialogueTurn(speaker="A", text=f"line{i}", turn_type=TurnType.DIALOGUE)
        for i in range(10)
    ]
    return Script(title="台本題", thumbnail_title="th", sections=turns)


def _make_config(mock_mode=False, mock_skip_metadata=False) -> SimpleNamespace:
    return SimpleNamespace(
        yaml=SimpleNamespace(
            dev=SimpleNamespace(
                mock_mode=mock_mode, mock_skip_metadata=mock_skip_metadata
            )
        )
    )


def _ext_result(pre_built_metadata) -> SimpleNamespace:
    """external_phase_result スタブ（.pre_built_metadata のみ持つ）。"""
    return SimpleNamespace(pre_built_metadata=pre_built_metadata)


def test_mock_skip_writes_empty_metadata_without_touching_external_result(tmp_path: Path):
    logs = []
    # 案1 の要: mock スキップ経路では external_phase_result へアクセスしないため
    # None を渡しても AttributeError にならない（原コードと厳密一致）。
    path, meta = _run_metadata_phase(
        config=_make_config(mock_mode=True, mock_skip_metadata=True),
        output_base=tmp_path,
        script=_make_script(),
        chapters=[],
        external_phase_result=None,
        theme="テーマ",
        log_fn=logs.append,
    )
    assert path == tmp_path / "metadata.txt"
    assert path.read_text(encoding="utf-8") == ""
    assert meta == {}
    assert any("スキップ" in m for m in logs)


def test_normal_path_builds_metadata_from_external_dict(tmp_path: Path):
    ext = {
        "title": "外部タイトル",
        "thumbnail_title": "外部短縮",
        "description": "外部説明文",
        "hashtags": ["#a", "#b"],
    }
    path, meta = _run_metadata_phase(
        config=_make_config(mock_mode=False),
        output_base=tmp_path,
        script=_make_script(),
        chapters=[],
        external_phase_result=_ext_result(ext),
        theme="テーマ",
        log_fn=lambda _m: None,
    )
    assert path.exists()
    assert meta["title"] == "外部タイトル"
    assert meta["thumbnail_title"] == "外部短縮"
    assert meta["description"] == "外部説明文"
