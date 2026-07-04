"""workflow._record_execution_logs の単体テスト（Phase 4 分解 E5）。

ExecutionLogEntry / CostLogEntry を構築し ExecutionLogger へ 1 件ずつ append する
こと、およびログ書込例外が呼び出し元へ伝播しない（非致命）ことを検証する。
ExecutionLogger と _capture_config_snapshot のみモックし、エントリ構築は実モデルで行う。
"""
from types import SimpleNamespace

import pytest

import workflow
from core.models.execution_log import ConfigSnapshot
from core.models.usage import TotalUsage
from workflow import _record_execution_logs


class _FakeCallbacks:
    def __init__(self):
        self.logs = []

    def log(self, msg):
        self.logs.append(msg)


class _FakeLogger:
    instances = []

    def __init__(self, path):
        self.path = path
        self.exec_logs = []
        self.cost_logs = []
        self.raise_on_exec = False
        _FakeLogger.instances.append(self)

    def append_execution_log(self, entry):
        if self.raise_on_exec:
            raise RuntimeError("append boom")
        self.exec_logs.append(entry)

    def append_cost_log(self, entry):
        self.cost_logs.append(entry)


def _fake_cost():
    return SimpleNamespace(
        perplexity_usd=0.0,
        gemini_input_usd=0.0,
        gemini_output_usd=0.0,
        total_usd=0.0,
        total_jpy=0.0,
        is_free_tier=True,
    )


def _config():
    return SimpleNamespace(yaml=SimpleNamespace(researcher=SimpleNamespace(model="sonar-pro")))


def _production_result():
    return SimpleNamespace(video_path="v.mp4", audio_path="a.wav", subtitle_path="s.srt")


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    _FakeLogger.instances = []
    monkeypatch.setattr(
        workflow, "_capture_config_snapshot", lambda c, o: ConfigSnapshot(yaml_config={})
    )
    yield


def _call(callbacks, tmp_path):
    _record_execution_logs(
        config=_config(),
        overrides_obj=None,  # _capture_config_snapshot をモックしたため未使用
        output_base=tmp_path,
        project_root=tmp_path,
        theme="テーマ",
        production_result=_production_result(),
        thumbnail_path="th.png",
        metadata_path="metadata.txt",
        total_usage=TotalUsage(),
        cost=_fake_cost(),
        callbacks=callbacks,
    )


def test_appends_one_execution_and_one_cost_log(monkeypatch, tmp_path):
    monkeypatch.setattr(workflow, "ExecutionLogger", _FakeLogger)
    cb = _FakeCallbacks()
    _call(cb, tmp_path)
    assert len(_FakeLogger.instances) == 1
    logger = _FakeLogger.instances[0]
    assert len(logger.exec_logs) == 1
    assert len(logger.cost_logs) == 1
    assert any("記録完了" in m for m in cb.logs)


def test_logging_failure_is_non_fatal(monkeypatch, tmp_path):
    def _raising_factory(path):
        lg = _FakeLogger(path)
        lg.raise_on_exec = True
        return lg

    monkeypatch.setattr(workflow, "ExecutionLogger", _raising_factory)
    cb = _FakeCallbacks()
    # 例外が伝播しないこと
    _call(cb, tmp_path)
    assert any("記録エラー" in m for m in cb.logs)
