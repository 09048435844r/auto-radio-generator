"""ワークフローのロギング/進捗ユーティリティ。

workflow.py から責務 #10（ロギング/進捗）を抽出したモジュール。
挙動は変更せず、以下のシンボルを提供する:

- ProgressCallback: ログ/進捗コールバックをまとめるクラス
- _SessionLogFileHandler: LogFileWriter 専用の FileHandler マーカークラス
- LogFileWriter: ログを processing_log.txt に書き込むクラス

後方互換のため workflow.py から再エクスポートされる。
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional


@dataclass
class ProgressCallback:
    """進捗コールバックをまとめるクラス"""

    def __init__(self,
                 log_callback: Optional[Callable[[str], None]] = None,
                 progress_callback: Optional[Callable[[float, str], None]] = None,
                 log_writer: Optional['LogFileWriter'] = None):
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.log_writer = log_writer

    def log(self, msg: str):
        """ログメッセージを送信"""
        if self.log_callback:
            self.log_callback(msg)
        # ログファイルにも書き込み
        if self.log_writer:
            self.log_writer.write(msg)

    def progress(self, ratio: float, description: str):
        """進捗を送信 (0.0〜1.0)"""
        if self.progress_callback:
            self.progress_callback(ratio, description)


class _SessionLogFileHandler(logging.FileHandler):
    """PR-C: LogFileWriter 専用の FileHandler マーカークラス。

    root logger から「自クラス由来のハンドラのみ」を `isinstance` で確実に
    識別・除去するために存在する。Gradio のような長命プロセスで前回 session の
    `LogFileWriter.finalize()` が呼ばれずにプロセスが継続した場合、新しい
    LogFileWriter が初期化される際に、このマーカークラス経由で前回の残留
    ハンドラを安全に掃除できる（他用途で追加された FileHandler は touch されない）。

    将来 `processing_log.txt` 以外のファイルに書く FileHandler が追加されても
    `isinstance(h, _SessionLogFileHandler)` で区別されるため誤検知ゼロ。
    """
    pass


class LogFileWriter:
    """ログをファイルに書き込むクラス

    PR-C（Issue A）: Python logger 出力も同じ processing_log.txt に統合。
    従来 stderr にしか出ていなかった `logger.warning/error` 系（FactExtractor の
    Unknown category 警告・TopicCurator の title 欠落警告・MetadataGenerator の
    truncation 警告等）が、セッションごとの `processing_log.txt` に自動記録される。
    """

    def __init__(self, output_dir: Path):
        """初期化

        Args:
            output_dir: ログファイルを保存するディレクトリ
        """
        self.output_dir = output_dir
        self.log_path = output_dir / "processing_log.txt"
        self.logs: list[str] = []

        # ログファイルを初期化
        self.log_path.write_text(
            f"=== 自動ラジオ生成ログ ===\n"
            f"開始時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n",
            encoding="utf-8"
        )

        # PR-C: 前回 session の残留 handler を掃除（Gradio 長命プロセスでの finalize 漏れ対策）。
        # `_SessionLogFileHandler` だけを狙って remove するため、他用途の FileHandler は安全。
        root_logger = logging.getLogger()
        for stale in [h for h in root_logger.handlers if isinstance(h, _SessionLogFileHandler)]:
            root_logger.removeHandler(stale)
            try:
                stale.close()
            except Exception:
                pass  # 既に close 済み等は無視

        # PR-C: このセッションの processing_log.txt に logger 出力を束ねる FileHandler を attach。
        # Level=WARNING で運用監視に必要な最小セット（WARNING/ERROR/CRITICAL）を捕捉。
        # DEBUG/INFO はノイズ抑止のため意図的に除外（config 駆動化は別 PR）。
        self._logger_handler: _SessionLogFileHandler = _SessionLogFileHandler(
            self.log_path, mode="a", encoding="utf-8"
        )
        self._logger_handler.setLevel(logging.WARNING)
        self._logger_handler.setFormatter(logging.Formatter(
            ">>> [%(levelname)s] [%(name)s] %(message)s"
        ))
        root_logger.addHandler(self._logger_handler)
        # root logger 自体の level が未設定（= WARNING default）でも WARNING は流れる。
        # ただし basicConfig が呼ばれていない場合でも handler レベルで制御されるので問題ない。

    def write(self, msg: str):
        """ログメッセージを追記

        Args:
            msg: ログメッセージ
        """
        self.logs.append(msg)

        # ファイルに追記
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(msg + "\n")

    def finalize(self):
        """ログファイルを完了"""
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(f"\n終了時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        # PR-C: 自 session の handler を detach + close して次 session へのリークを防ぐ。
        # 二重 finalize された場合も例外を握りつぶして冪等化。
        try:
            logging.getLogger().removeHandler(self._logger_handler)
        except Exception:
            pass
        try:
            self._logger_handler.close()
        except Exception:
            pass
