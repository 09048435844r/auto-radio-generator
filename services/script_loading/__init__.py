"""script_loading パッケージ - 外部台本ファイル読み込み層

Step 3 (2026-05-09) 外部台本モード化で導入。Mac 側 radio_director 等の外部
パイプラインが生成した台本ファイルを Windows 側 Script モデルに変換する
ローダー実装の置き場。
"""
from services.script_loading.radio_director_loader import RadioDirectorScriptLoader

__all__ = ["RadioDirectorScriptLoader"]
