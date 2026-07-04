"""workflow._upload_to_youtube の単体テスト（Phase 4 分解 E4）。

should_upload 判定（mock ガード / UI 優先 / config）、アップロード失敗時の非致命性、
再生リスト追加を、YouTubeClient をモックして検証する。
"""
from types import SimpleNamespace

import pytest

import workflow
from workflow import _upload_to_youtube


class _FakeCallbacks:
    def __init__(self):
        self.logs = []

    def log(self, msg):
        self.logs.append(msg)


class _FakeYouTubeClient:
    """呼び出しを記録するスタブ。"""

    instances = []

    def __init__(self, config):
        self.config = config
        self.upload_calls = []
        self.playlist_calls = []
        self.upload_result = "https://www.youtube.com/watch?v=ABC123"
        self.raise_on_upload = False
        _FakeYouTubeClient.instances.append(self)

    def upload_video(self, **kwargs):
        self.upload_calls.append(kwargs)
        if self.raise_on_upload:
            raise RuntimeError("upload boom")
        return self.upload_result

    def add_video_to_playlist(self, **kwargs):
        self.playlist_calls.append(kwargs)


@pytest.fixture(autouse=True)
def _reset_instances():
    _FakeYouTubeClient.instances = []
    yield


def _config():
    return SimpleNamespace(yaml=SimpleNamespace())


def test_mock_execution_never_uploads(monkeypatch):
    monkeypatch.setattr(workflow, "YouTubeClient", _FakeYouTubeClient)
    cb = _FakeCallbacks()
    url = _upload_to_youtube(
        config=_config(),
        use_mock=True,
        upload_override=True,  # UI で有効でも mock なら強制無効
        publishing_config=SimpleNamespace(enable_upload=True, playlist_id=None),
        video_path="v.mp4",
        formatted_title="t",
        formatted_description="d",
        thumbnail_path="th.png",
        callbacks=cb,
    )
    assert url is None
    assert _FakeYouTubeClient.instances == []  # クライアント生成すらされない
    assert any("強制的に無効化" in m for m in cb.logs)


def test_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(workflow, "YouTubeClient", _FakeYouTubeClient)
    cb = _FakeCallbacks()
    url = _upload_to_youtube(
        config=_config(),
        use_mock=False,
        upload_override=None,
        publishing_config=SimpleNamespace(enable_upload=False, playlist_id=None),
        video_path="v.mp4",
        formatted_title="t",
        formatted_description="d",
        thumbnail_path="th.png",
        callbacks=cb,
    )
    assert url is None
    assert _FakeYouTubeClient.instances == []


def test_upload_failure_is_non_fatal(monkeypatch):
    def _factory(config):
        client = _FakeYouTubeClient(config)
        client.raise_on_upload = True
        return client

    monkeypatch.setattr(workflow, "YouTubeClient", _factory)
    cb = _FakeCallbacks()
    url = _upload_to_youtube(
        config=_config(),
        use_mock=False,
        upload_override=True,
        publishing_config=SimpleNamespace(enable_upload=True, playlist_id=None),
        video_path="v.mp4",
        formatted_title="t",
        formatted_description="d",
        thumbnail_path="th.png",
        callbacks=cb,
    )
    assert url is None  # 例外を握り潰して None
    assert any("アップロードに失敗" in m for m in cb.logs)


def test_playlist_added_when_configured(monkeypatch):
    monkeypatch.setattr(workflow, "YouTubeClient", _FakeYouTubeClient)
    cb = _FakeCallbacks()
    url = _upload_to_youtube(
        config=_config(),
        use_mock=False,
        upload_override=True,
        publishing_config=SimpleNamespace(enable_upload=True, playlist_id="PL_123"),
        video_path="v.mp4",
        formatted_title="t",
        formatted_description="d",
        thumbnail_path="th.png",
        callbacks=cb,
    )
    assert url == "https://www.youtube.com/watch?v=ABC123"
    client = _FakeYouTubeClient.instances[0]
    assert client.playlist_calls == [{"video_id": "ABC123", "playlist_id": "PL_123"}]
