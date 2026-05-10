"""llm_factory.get_provider_from_model_name の回帰テスト

2026-05-03: vLLM (Qwen3-Next-80B) 移行で qwen 系プレフィックスを ollama に
マッピングする変更を追加。app.py のマニュアル制作フローで qwen3-next-80b 等の
モデル名を入力した際に ValueError で即エラーになっていた問題を解消する。
"""
import pytest

from services.script_generation.llm_factory import get_provider_from_model_name


# ---------------------------------------------------------------------------
# (1) 既存マッピング（回帰防止）
# ---------------------------------------------------------------------------

# Step 4 v2 (2026-05-10): "gemini-" prefix は削除。
@pytest.mark.parametrize("model_name,expected", [
    ("gpt-5.4", "openai"),
    ("gpt-4o-2024-05-13", "openai"),
    ("o1-mini", "openai"),
    ("o3-mini", "openai"),
    ("claude-sonnet-4-6", "anthropic"),
    ("claude-opus-4-6", "anthropic"),
    ("llama3.2", "ollama"),
    ("phi3:mini", "ollama"),
    ("mistral:7b", "ollama"),
    ("mixtral:8x7b", "ollama"),
])
def test_existing_provider_mappings_unchanged(model_name, expected):
    """vLLM 移行前から認識されていたモデル名のマッピングが壊れていない（gemini を除く）。"""
    assert get_provider_from_model_name(model_name) == expected


def test_gemini_prefix_no_longer_recognized():
    """Step 4 v2: 'gemini-' prefix は削除されたため ValueError を発生させる"""
    with pytest.raises(ValueError, match="Unknown model name"):
        get_provider_from_model_name("gemini-3.1-pro-preview")


def test_gpt_oss_precedence_quirk_returns_openai():
    """既知の precedence 不整合: `gpt-oss:` は本来 ollama 想定だが `gpt-` が先に
    マッチして openai を返す。本タスクのスコープ外（pre-existing 挙動の固定）。
    将来 BACKLOG で precedence 並べ替えを行うときの回帰検出用にテスト化。"""
    assert get_provider_from_model_name("gpt-oss:20b-long") == "openai"


# ---------------------------------------------------------------------------
# (2) 新規追加: qwen 系プレフィックス → ollama
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model_name", [
    "qwen3-next-80b",        # vLLM 統一後の現行モデル
    "qwen3:32b",             # GX10 移行時代の旧モデル
    "qwen3:8b",              # Mac Studio 時代の旧モデル
    "qwen2.5:14b",           # さらに旧
    "qwen2.5-coder:14b",     # FactExtractor 旧モデル
    "qwen2.5-coder:32b",     # FactExtractor GX10 時代モデル
    "qwen3:30b-a3b",         # BACKLOG 候補に挙がっていた MoE 系
])
def test_qwen_models_route_to_ollama(model_name):
    """qwen 系（vLLM ホストでも Ollama provider 扱い）が正しく ollama に振られる。"""
    assert get_provider_from_model_name(model_name) == "ollama", (
        f"vLLM 経由 qwen 系モデル {model_name!r} は ollama provider に振られるべき"
    )


# ---------------------------------------------------------------------------
# (3) 未知プレフィックス → ValueError（防御的挙動の維持）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("unknown_name", [
    "deepseek-r1:14b",   # まだ未対応の vLLM/Ollama モデル（将来追加候補）
    "llava:7b",
    "totally-fake-model",
    "",
])
def test_unknown_models_raise_value_error(unknown_name):
    """未知のモデル名は明示的に ValueError を投げる（silent fallback しない）。"""
    with pytest.raises(ValueError, match="Unknown model name"):
        get_provider_from_model_name(unknown_name)
