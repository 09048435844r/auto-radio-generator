"""workflow._generate_thumbnail_assets の単体テスト（Phase 4 分解 E2）。

- static モードで background_image が paths 由来（project_root / paths.background_image）
- dynamic 生成失敗時に static へフォールバックし例外を伝播しない
ThumbnailGenerator / ThumbnailBackgroundGenerator をモックし、実時間値は非検証。
"""
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import workflow
from workflow import _generate_thumbnail_assets


class _FakeCallbacks:
    def __init__(self):
        self.logs = []

    def log(self, msg):
        self.logs.append(msg)


class _FakeThumbnailGenerator:
    """thumbnail_generator.generate の呼び出し(特に background_path)を記録。"""

    calls = []

    def generate(self, **kwargs):
        _FakeThumbnailGenerator.calls.append(kwargs)


class _NeverBgGen:
    """static 経路で構築されないことを担保するためのセンチネル。"""

    constructed = 0

    def __init__(self, *a, **k):
        _NeverBgGen.constructed += 1

    async def generate(self, **kwargs):  # pragma: no cover - 呼ばれない想定
        raise AssertionError("static モードで背景ジェネレータが呼ばれた")


class _RaisingBgGen:
    """dynamic 経路で generate が失敗するスタブ。"""

    def __init__(self, *a, **k):
        pass

    async def generate(self, **kwargs):
        raise RuntimeError("FLUX boom")


def _config(mode):
    return SimpleNamespace(
        yaml=SimpleNamespace(
            video_renderer=SimpleNamespace(thumbnail_background_mode=mode),
            paths=SimpleNamespace(background_image="assets/bg.png"),
        )
    )


def _script():
    return SimpleNamespace(title="台本題", description="概要文")


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    _FakeThumbnailGenerator.calls = []
    _NeverBgGen.constructed = 0
    monkeypatch.setattr(workflow, "ThumbnailGenerator", _FakeThumbnailGenerator)
    yield


def _run(**kwargs):
    return asyncio.run(_generate_thumbnail_assets(**kwargs))


def test_static_mode_uses_paths_background(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(workflow, "ThumbnailBackgroundGenerator", _NeverBgGen)
    cb = _FakeCallbacks()
    thumb, bg_time = _run(
        config=_config("static"),
        output_base=tmp_path,
        project_root=tmp_path,
        theme="テーマ",
        script=_script(),
        visual_identity=None,
        generated_metadata={"title": "MT", "thumbnail_title": "TT"},
        skip_thumbnail_in_mock=False,
        callbacks=cb,
    )
    assert _NeverBgGen.constructed == 0  # dynamic 背景生成は行われない
    assert thumb == tmp_path / "thumbnail.png"
    assert bg_time == 0.0
    assert _FakeThumbnailGenerator.calls[0]["background_path"] == tmp_path / "assets/bg.png"


def test_dynamic_failure_falls_back_to_static(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(workflow, "ThumbnailBackgroundGenerator", _RaisingBgGen)
    cb = _FakeCallbacks()
    # 例外が伝播しないこと
    thumb, bg_time = _run(
        config=_config("dynamic"),
        output_base=tmp_path,
        project_root=tmp_path,
        theme="テーマ",
        script=_script(),
        visual_identity=None,
        generated_metadata={"title": "MT", "thumbnail_title": "TT"},
        skip_thumbnail_in_mock=False,
        callbacks=cb,
    )
    assert thumb == tmp_path / "thumbnail.png"
    assert bg_time == 0.0  # 失敗時は計測値 0.0 のまま
    # 静的背景へフォールバック
    assert _FakeThumbnailGenerator.calls[0]["background_path"] == tmp_path / "assets/bg.png"
    assert any("静的背景を使用" in m for m in cb.logs)


def test_skip_thumbnail_in_mock_skips_generation(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(workflow, "ThumbnailBackgroundGenerator", _NeverBgGen)
    cb = _FakeCallbacks()
    thumb, _bg = _run(
        config=_config("static"),
        output_base=tmp_path,
        project_root=tmp_path,
        theme="テーマ",
        script=_script(),
        visual_identity=None,
        generated_metadata={"title": "MT", "thumbnail_title": "TT"},
        skip_thumbnail_in_mock=True,
        callbacks=cb,
    )
    assert thumb == tmp_path / "thumbnail.png"
    assert _FakeThumbnailGenerator.calls == []  # 生成スキップ
    assert any("サムネイル生成をスキップ" in m for m in cb.logs)
