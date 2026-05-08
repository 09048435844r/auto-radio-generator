"""IScriptLoader ABC のコントラクトテスト

Step 3 (2026-05-09) 外部台本モード化で導入された ABC の最低限の契約担保。
"""
import inspect
from pathlib import Path

import pytest

from core.interfaces import IScriptLoader
from core.models.script import Script


# ---------------------------------------------------------------------------
# (1) abstractmethod として load が定義されている
# ---------------------------------------------------------------------------

def test_iscript_loader_load_is_abstractmethod():
    """`load` メソッドが abstractmethod として宣言されている → 直接インスタンス化は NG"""
    assert getattr(IScriptLoader.load, "__isabstractmethod__", False) is True

    with pytest.raises(TypeError, match="abstract"):
        IScriptLoader()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# (2) 型ヒント契約: load(path: Path) -> Script
# ---------------------------------------------------------------------------

def test_iscript_loader_load_signature_contract():
    """load の引数は Path、戻り値は Script の型ヒントで宣言されている"""
    sig = inspect.signature(IScriptLoader.load)
    params = list(sig.parameters.values())
    # self を除いた最初の引数が Path
    assert len(params) >= 2, "load(self, verified_script_path) を期待"
    arg = params[1]
    assert arg.annotation is Path, f"load の引数は Path 型を期待 (実際: {arg.annotation})"
    assert sig.return_annotation is Script, (
        f"load の戻り値は Script を期待 (実際: {sig.return_annotation})"
    )


# ---------------------------------------------------------------------------
# (3) サブクラス実装の最小契約: load を実装すれば具象クラス化できる
# ---------------------------------------------------------------------------

def test_iscript_loader_concrete_subclass_can_be_instantiated(tmp_path):
    """`load` を実装したサブクラスは普通にインスタンス化できる
    （RadioDirectorScriptLoader が成立する基盤の確認）。
    """
    from core.models.script import DialogueTurn, TurnType

    class _DummyLoader(IScriptLoader):
        def load(self, verified_script_path: Path) -> Script:  # noqa: ARG002
            # 最低 10 turn の Script を返す（Script の min_length=10 制約に整合）
            turns = [
                DialogueTurn(speaker="A", text=f"line{i}", turn_type=TurnType.DIALOGUE)
                for i in range(10)
            ]
            return Script(
                title="dummy", thumbnail_title="t", sections=turns,
            )

    loader = _DummyLoader()
    result = loader.load(tmp_path / "any.json")
    assert isinstance(result, Script)
    assert result.title == "dummy"
