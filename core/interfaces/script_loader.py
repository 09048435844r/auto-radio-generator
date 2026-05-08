"""IScriptLoader - 外部台本ローダーの抽象基底クラス

Step 3 (2026-05-09) 外部台本モード化で導入。Mac 側 radio_director 等の外部
パイプラインが生成した台本データを `core.models.script.Script` に変換する
責務を持つ ABC。既存 ABC 群 (IResearcher / IScriptGenerator / IAudioSynthesizer /
IVideoRenderer) と同列の薄いインターフェース。

実装: services/script_loading/ 配下のクラス。
最初の実装は `RadioDirectorScriptLoader` (Mac 側 VerifiedScript JSON 専用)。
"""
from abc import ABC, abstractmethod
from pathlib import Path

from core.models.script import Script


class IScriptLoader(ABC):
    """外部台本ローダーの抽象基底クラス

    外部パイプライン (Mac 側 radio_director 等) が生成した台本データファイルを
    1 ファイル受け取り、Windows 側 auto-radio-generator の `Script` モデルに
    変換する。Phase 1 (planning) / Phase 2 (scripting) を完全 bypass する経路で
    使用される。

    実装は同期メソッドで足りる (ファイル I/O + Pydantic 検証のみ、ネットワーク不要)。
    """

    @abstractmethod
    def load(self, verified_script_path: Path) -> Script:
        """外部台本ファイルを読み込み Script に変換する。

        Args:
            verified_script_path: 外部台本 JSON のパス (Mac 側 VerifiedScript 等)

        Returns:
            Script: Windows 側パイプライン (VOICEVOX / FFmpeg) で使用可能な台本

        Raises:
            FileNotFoundError: 指定パスが存在しない
            pydantic.ValidationError: ファイル内容が想定スキーマに整合しない
            (silent fallback 禁止 — 不正データは即エラー)
        """
        ...
