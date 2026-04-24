"""PR-C (Issue A): LogFileWriter による Python logger 出力の processing_log.txt への統合テスト.

Scope:
  1. Basic capture: logger.warning → processing_log.txt に `>>> [WARNING] ...` 行が入る
  2. finalize 後の隔離: finalize 後の warning はファイルに書き込まれない
  3. 複数インスタンスの隔離: 前回 finalize 後の新インスタンスは前ファイルに書かない
  4. .write() 後方互換: 既存の rich markup 行のフォーマットは変化なし
  5. 残留ハンドラ掃除: finalize 忘れのまま新インスタンスを作ると、前ハンドラが root logger から掃除される
  6. 誤検知ゼロ: 非 _SessionLogFileHandler の FileHandler は掃除対象にならない
"""
import logging
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_root_handlers():
    """各テスト終了時に root logger のハンドラを復元する（テスト間汚染防止）。

    _SessionLogFileHandler のインスタンスのみを掃除し、pytest / 他テストが
    付与した他種類のハンドラは温存する。
    """
    from workflow import _SessionLogFileHandler

    root = logging.getLogger()
    before = list(root.handlers)
    try:
        yield
    finally:
        for h in list(root.handlers):
            if isinstance(h, _SessionLogFileHandler) and h not in before:
                root.removeHandler(h)
                try:
                    h.close()
                except Exception:
                    pass


def _make_log_writer(dir_path: Path):
    from workflow import LogFileWriter

    return LogFileWriter(dir_path)


def _read_log(dir_path: Path) -> str:
    return (dir_path / "processing_log.txt").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Basic capture
# ---------------------------------------------------------------------------

def test_logger_warning_is_captured_to_processing_log(tmp_path: Path):
    """logger.warning(...) が processing_log.txt に `>>> [WARNING] ...` 行として現れる。"""
    writer = _make_log_writer(tmp_path)

    test_logger = logging.getLogger("tests.test_logger_capture.basic")
    test_logger.warning("captured warning message")

    writer.finalize()

    content = _read_log(tmp_path)
    assert ">>> [WARNING]" in content
    assert "tests.test_logger_capture.basic" in content
    assert "captured warning message" in content


def test_logger_error_is_captured(tmp_path: Path):
    """logger.error(...) も captured される (WARNING 以上対象)。"""
    writer = _make_log_writer(tmp_path)
    logging.getLogger("tests.err").error("error details here")
    writer.finalize()

    content = _read_log(tmp_path)
    assert ">>> [ERROR]" in content
    assert "error details here" in content


def test_logger_info_is_not_captured(tmp_path: Path):
    """logger.info(...) は WARNING 未満なので captured されない（ノイズ抑止）。"""
    writer = _make_log_writer(tmp_path)
    logging.getLogger("tests.info").info("info should not appear")
    writer.finalize()

    content = _read_log(tmp_path)
    assert "info should not appear" not in content


# ---------------------------------------------------------------------------
# 2. finalize 後の隔離
# ---------------------------------------------------------------------------

def test_logger_warning_after_finalize_is_not_captured(tmp_path: Path):
    """finalize() 後に発行した warning はファイルに追加されない（handler detach 確認）。"""
    writer = _make_log_writer(tmp_path)
    writer.finalize()

    before_size = (tmp_path / "processing_log.txt").stat().st_size

    logging.getLogger("tests.after").warning("should not reach file")

    after_size = (tmp_path / "processing_log.txt").stat().st_size
    assert before_size == after_size, \
        "finalize 後の warning がファイルサイズを変えてはいけない（handler 残留）"

    content = _read_log(tmp_path)
    assert "should not reach file" not in content


# ---------------------------------------------------------------------------
# 3. 複数インスタンスの隔離
# ---------------------------------------------------------------------------

def test_multiple_writers_do_not_cross_contaminate(tmp_path: Path):
    """session A finalize → session B 開始 → session B の warning は session A のファイルに書かない。"""
    dir_a = tmp_path / "session_a"
    dir_b = tmp_path / "session_b"
    dir_a.mkdir()
    dir_b.mkdir()

    writer_a = _make_log_writer(dir_a)
    logging.getLogger("tests.sep").warning("for session A")
    writer_a.finalize()

    writer_b = _make_log_writer(dir_b)
    logging.getLogger("tests.sep").warning("for session B")
    writer_b.finalize()

    content_a = _read_log(dir_a)
    content_b = _read_log(dir_b)

    assert "for session A" in content_a
    assert "for session A" not in content_b, "session A の warning が session B に漏れている"
    assert "for session B" in content_b
    assert "for session B" not in content_a, "session B の warning が session A に遡って書かれている"


# ---------------------------------------------------------------------------
# 4. .write() 後方互換
# ---------------------------------------------------------------------------

def test_write_method_preserves_legacy_format(tmp_path: Path):
    """既存の .write(msg) 呼び出しは、msg + '\\n' のそのままの形式でファイルに記録される。"""
    writer = _make_log_writer(tmp_path)
    writer.write("[cyan]📋 existing rich markup line[/cyan]")
    writer.write("  プレーンテキスト行")
    writer.finalize()

    content = _read_log(tmp_path)
    # rich markup そのまま（カラーコードが解釈されることはない）
    assert "[cyan]📋 existing rich markup line[/cyan]\n" in content
    assert "  プレーンテキスト行\n" in content
    # logger 用のプレフィックス `>>> [...]` は .write() が付与しないこと
    for line in ["[cyan]📋 existing rich markup line[/cyan]", "  プレーンテキスト行"]:
        assert f">>> [WARNING] {line}" not in content
        assert f">>> [ERROR] {line}" not in content


def test_write_and_logger_coexist_in_same_file(tmp_path: Path):
    """.write() と logger.warning が同じファイルに混在でき、片方が他方を壊さない。"""
    writer = _make_log_writer(tmp_path)
    writer.write("[green]✓ step finished[/green]")
    logging.getLogger("tests.mix").warning("fallback used")
    writer.write("  続行")
    writer.finalize()

    content = _read_log(tmp_path)
    assert "[green]✓ step finished[/green]" in content
    assert ">>> [WARNING]" in content
    assert "fallback used" in content
    assert "  続行" in content


# ---------------------------------------------------------------------------
# 5. 残留ハンドラ掃除（finalize 忘れシミュレーション）
# ---------------------------------------------------------------------------

def test_residual_handler_is_cleaned_when_new_writer_created(tmp_path: Path):
    """writer_a を finalize せずに writer_b を作ると、writer_a のハンドラが root logger から掃除される。

    これは Gradio 長命プロセスで例外等により finalize() が呼ばれなかった場合の汚染防止策。
    """
    from workflow import _SessionLogFileHandler

    dir_a = tmp_path / "leaked"
    dir_b = tmp_path / "fresh"
    dir_a.mkdir()
    dir_b.mkdir()

    writer_a = _make_log_writer(dir_a)
    # writer_a.finalize() は**意図的に呼ばない**（漏れシミュレーション）

    # この時点で root logger に writer_a の handler がアタッチされている
    root = logging.getLogger()
    session_handlers_before = [h for h in root.handlers if isinstance(h, _SessionLogFileHandler)]
    assert len(session_handlers_before) == 1

    # writer_b を作成 → writer_a のハンドラが掃除されるはず
    writer_b = _make_log_writer(dir_b)

    session_handlers_after = [h for h in root.handlers if isinstance(h, _SessionLogFileHandler)]
    # 残るのは writer_b の 1 つのみ（writer_a のは掃除された）
    assert len(session_handlers_after) == 1
    assert session_handlers_after[0] is writer_b._logger_handler

    # さらに、writer_b の warning は writer_b のファイルにのみ書かれる
    logging.getLogger("tests.residual").warning("post-cleanup warning")
    writer_b.finalize()

    content_b = _read_log(dir_b)
    content_a = _read_log(dir_a)
    assert "post-cleanup warning" in content_b
    assert "post-cleanup warning" not in content_a, \
        "writer_a の残留ハンドラが掃除されていれば writer_a のファイルには書かれないはず"


# ---------------------------------------------------------------------------
# 6. 誤検知ゼロ（非 _SessionLogFileHandler は掃除対象外）
# ---------------------------------------------------------------------------

def test_non_session_filehandler_is_not_cleaned_up(tmp_path: Path):
    """他目的で root logger に付与された FileHandler は、LogFileWriter 初期化時に掃除されない。

    これは _SessionLogFileHandler の専用サブクラス化が誤検知ゼロで動作する証拠。
    """
    # 他目的の FileHandler（通常の logging.FileHandler）を root logger に付与
    other_path = tmp_path / "other.log"
    other_handler = logging.FileHandler(other_path, mode="w", encoding="utf-8")
    other_handler.setLevel(logging.WARNING)
    root = logging.getLogger()
    root.addHandler(other_handler)

    try:
        # LogFileWriter を作成
        session_dir = tmp_path / "session"
        session_dir.mkdir()
        writer = _make_log_writer(session_dir)

        # 他目的ハンドラがまだ root logger に残っていることを確認
        assert other_handler in root.handlers, \
            "_SessionLogFileHandler でない FileHandler を誤って掃除してはいけない"

        writer.finalize()

        # finalize 後も他目的ハンドラは残存
        assert other_handler in root.handlers
    finally:
        root.removeHandler(other_handler)
        other_handler.close()
