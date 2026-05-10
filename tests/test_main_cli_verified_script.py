"""main.py の --verified-script CLI 引数テスト

Step 3 外部台本モード化の commit 7。CLI から `--phase external --verified-script <path>`
で外部台本モードを起動できることを担保する。
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest


MAIN_PY_PATH = Path(__file__).resolve().parent.parent / "main.py"
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "verified_script_sample.json"


# ---------------------------------------------------------------------------
# (1) main.py のソース構造: --phase external と --verified-script 引数が定義されている
# ---------------------------------------------------------------------------

def test_main_py_has_phase_external_choice():
    """Step 4 v2 (2026-05-10): --phase choices から 'all'/'script' を削除し
    'research'/'render'/'external' のみ残す"""
    src = MAIN_PY_PATH.read_text(encoding="utf-8")
    assert re.search(
        r'choices=\["research",\s*"render",\s*"external"\]',
        src,
    ), "main.py の --phase choices が Step 4 v2 仕様 (research/render/external) と一致しない"


def test_main_py_has_verified_script_argument():
    src = MAIN_PY_PATH.read_text(encoding="utf-8")
    assert '"--verified-script"' in src, "main.py に --verified-script 引数が定義されていない"


def test_main_py_external_phase_calls_execute_external_script_phase():
    src = MAIN_PY_PATH.read_text(encoding="utf-8")
    # --phase external 分岐内で execute_external_script_phase が呼ばれる
    assert 'elif args.phase == "external":' in src
    assert "execute_external_script_phase(" in src


# ---------------------------------------------------------------------------
# (2) CLI として `--help` が表示できる (argparse parsing が崩れていないことを確認)
# ---------------------------------------------------------------------------

def test_main_py_help_includes_external_phase():
    """`python main.py --help` 出力に external が含まれる (--phase choices 反映確認)"""
    result = subprocess.run(
        [sys.executable, str(MAIN_PY_PATH), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
        errors="replace",
    )
    # argparse は --help で exit 0
    assert result.returncode == 0, f"--help が異常終了: stderr={result.stderr[:300]}"
    out = result.stdout + result.stderr
    assert "external" in out, "--help 出力に external phase が含まれていない"
    assert "--verified-script" in out, "--help 出力に --verified-script が含まれていない"


# ---------------------------------------------------------------------------
# (3) Deprecated 警告: 旧 LLM 経路 (PerplexityResearcher / GeminiClient.generate) が
#     関数 level で warnings.warn(DeprecationWarning) を発火する
# ---------------------------------------------------------------------------

def test_perplexity_researcher_emits_deprecation_warning_on_init():
    """PerplexityResearcher の __init__ で DeprecationWarning が発火 (import 時には発火しない)"""
    import warnings as _w
    from unittest.mock import MagicMock

    # import 時には発火しない確認: 直前まで filterwarnings が active
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        from services.research.perplexity_client import PerplexityResearcher
        # ここまでで発火していてはいけない (module level でないため)
        deprecation_at_import = [
            w for w in caught
            if issubclass(w.category, DeprecationWarning)
            and "PerplexityResearcher" in str(w.message)
        ]
        assert deprecation_at_import == [], (
            "PerplexityResearcher の DeprecationWarning が import 時に発火している (関数 level であるべき)"
        )

    # __init__ で発火する確認 (mock config を渡す)
    cfg = MagicMock()
    cfg.env.perplexity_api_key = "dummy"
    cfg.yaml.researcher.model = "sonar-pro"
    cfg.yaml.researcher.max_tokens = 100
    cfg.yaml.researcher.modes = {}
    cfg.yaml.researcher.max_queries_per_plan = 3
    cfg.yaml.researcher.max_requests_per_workflow = 6
    cfg.yaml.researcher.enable_session_cache = True

    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        try:
            PerplexityResearcher(cfg)
        except Exception:
            # 内部で初期化失敗してもよい (警告自体は発火している)
            pass
        deprecation_at_init = [
            w for w in caught
            if issubclass(w.category, DeprecationWarning)
            and "PerplexityResearcher" in str(w.message)
        ]
        assert len(deprecation_at_init) >= 1, (
            "PerplexityResearcher.__init__ で DeprecationWarning が発火していない"
        )


def test_gemini_client_generate_has_deprecation_warning_in_source():
    """GeminiClient.generate の冒頭に warnings.warn(DeprecationWarning) が組み込まれている

    (実際に呼ぶには Gemini API キーや網羅的な依存が必要なので source 構造で担保する)
    """
    src = (Path(__file__).resolve().parent.parent
           / "services" / "script_generation" / "gemini_client.py").read_text(encoding="utf-8")
    # async def generate(...) の本体に warnings.warn が含まれる
    pattern = r"async def generate\([^)]+\) -> Script:.*?warnings\.warn\("
    assert re.search(pattern, src, re.DOTALL), (
        "GeminiClient.generate の本体に warnings.warn(DeprecationWarning) が見当たらない"
    )
    # DeprecationWarning がカテゴリで指定されている
    assert "DeprecationWarning" in src
