"""Smoke test: DeepSeekV4Flash 移行後の本運用 LLM 3 経路の実機確認 (2026-07)

GX10 バックエンドが Qwen3.5-122B → DeepSeekV4Flash (2 ノードクラスター) に
移行した後、外部台本モード本運用で実際に LLM を呼ぶ 3 経路を実 LLM
(Mac Studio Proxy http://192.168.0.3:11435/v1 経由) で叩いて検証する。

検証経路（本運用 verified_script.json → mp4 で発火する全 LLM コール）:
  ① VisualPaletteGenerator.generate_identity — json_object モード。
     応答の JSON parse + Pydantic (VisualIdentity) validate まで確認
  ② ImagePromptGenerator.generate_thumbnail_prompt — text モード。
     日本語混入 sanitize の通過確認（最終プロンプトに日本語ゼロ）
  ③ ImagePromptGenerator.generate_prompt（セグメント背景用）— text モード

各経路の fail 判定:
  - finish_reason == "length" → FAIL
  - content が空文字 / 空白のみ → FAIL（Adapter が例外化するため例外も FAIL）
  - usage.completion_tokens をログ出力
  - 応答に reasoning_content があり非 null → WARNING（Proxy の思考抑制が
    効いていない兆候）

使い方:
  python scripts/manual_tests/smoke_test_deepseek_migration.py
結果ログ: output/smoke_test_deepseek_migration.log（毎回上書き）
終了コード: 0=全経路 PASS / 1=いずれか FAIL

NOTE: pytest 対象外（実 LLM 接続が必要な手動スモークテスト）。
"""
import asyncio
import re
import sys
from pathlib import Path

# Windows console (cp932) 対策: stdout/stderr を UTF-8 にする
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.interfaces.llm_port import ILLMPort, LLMRequest, LLMResponse
from core.models import load_config
from core.models.curation import ScriptSegment
from core.models.visual import VisualIdentity

LOG_PATH = PROJECT_ROOT / "output" / "smoke_test_deepseek_migration.log"

# 日本語文字（ひらがな・カタカナ・漢字）検出。②③ の sanitize 通過確認に使う
JAPANESE_CHARS = re.compile(r"[぀-ゟ゠-ヿ一-鿿]")

THEME = "睡眠の質と深部体温の関係"
SCRIPT_SUMMARY = (
    "就寝90分前の入浴で深部体温を一時的に上げると、その後の急降下が"
    "入眠を促進する。皮膚温と深部体温の差が縮まるタイミングが眠気のピークで、"
    "室温18〜19度が推奨される。"
)

_log_lines: list[str] = []


def log(msg: str) -> None:
    print(msg)
    _log_lines.append(msg)


class RecordingPort(ILLMPort):
    """実 Adapter をラップし、生の LLMRequest/LLMResponse/例外を記録するプロキシ。

    上位ジェネレーター (VisualPaletteGenerator 等) は LLM 失敗を fallback で
    握り潰すため、スモーク判定は本レコーダーの記録を根拠とする。
    """

    def __init__(self, inner: ILLMPort):
        self._inner = inner
        self.records: list[dict] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        record: dict = {"request": request, "response": None, "error": None}
        self.records.append(record)
        try:
            response = await self._inner.generate(request)
        except Exception as e:
            record["error"] = e
            raise
        record["response"] = response
        return response

    async def health_check(self) -> bool:
        return await self._inner.health_check()

    @property
    def provider_name(self) -> str:
        return self._inner.provider_name

    @property
    def model_name(self) -> str:
        return self._inner.model_name


def evaluate_record(label: str, record: dict) -> bool:
    """1 レコードを fail 判定基準で評価し、詳細をログ出力する。True=PASS。"""
    ok = True

    if record["error"] is not None:
        log(f"  [{label}] FAIL: LLM 呼び出しが例外: {record['error']!r}")
        return False

    response: LLMResponse = record["response"]
    log(f"  [{label}] finish_reason={response.finish_reason}")
    log(f"  [{label}] completion_tokens={response.usage.output_tokens} "
        f"(prompt_tokens={response.usage.input_tokens})")

    if response.finish_reason == "length":
        log(f"  [{label}] FAIL: finish_reason=length（max_tokens 到達）")
        ok = False

    if not response.content or not response.content.strip():
        log(f"  [{label}] FAIL: content が空 / 空白のみ")
        ok = False
    else:
        log(f"  [{label}] content 長={len(response.content)} 文字, "
            f"先頭 80 字: {response.content[:80]!r}")

    # reasoning_content の確認（Proxy が思考抑制済みなら null のはず）
    raw = response.raw_response
    if raw is not None:
        try:
            message = raw.choices[0].message
            reasoning = getattr(message, "reasoning_content", None)
            if reasoning is None:
                model_extra = getattr(message, "model_extra", None)
                if isinstance(model_extra, dict):
                    reasoning = model_extra.get("reasoning_content")
            log(f"  [{label}] reasoning_content={reasoning!r}")
            if reasoning is not None:
                log(f"  [{label}] WARNING: reasoning_content が非 null。"
                    "Proxy の思考抑制 (reasoning_effort=none) が効いていない兆候")
        except Exception as e:  # raw 形式差異はスモーク失敗にしない
            log(f"  [{label}] reasoning_content 確認不可: {e!r}")

    return ok


async def path1_visual_palette(config) -> bool:
    """① VisualPaletteGenerator.generate_identity (json_object モード)"""
    from services.script_generation.visual_palette_generator import (
        VisualPaletteGenerator,
    )

    log("\n=== 経路① VisualPaletteGenerator.generate_identity (json_object) ===")
    generator = VisualPaletteGenerator(config)
    recorder = RecordingPort(generator._llm_port)
    generator._llm_port = recorder

    identity = await generator.generate_identity(THEME, SCRIPT_SUMMARY)

    if not recorder.records:
        log("  [①] FAIL: LLM が一度も呼ばれなかった")
        return False

    ok = evaluate_record("①", recorder.records[-1])

    # JSON parse + Pydantic validate（generator は失敗時 fallback を返すため、
    # 生応答を独立に validate して構造化出力の信頼性を直接確認する）
    response = recorder.records[-1]["response"]
    if response is not None:
        try:
            validated = VisualIdentity.model_validate_json(response.content)
            log(f"  [①] Pydantic validate: OK "
                f"(primary={validated.primary_color}, "
                f"secondary={validated.secondary_color})")
        except Exception as e:
            log(f"  [①] FAIL: VisualIdentity validate エラー: {e}")
            ok = False

    log(f"  [①] generate_identity 戻り値: {identity.primary_color} / "
        f"{identity.secondary_color}")
    return ok


async def path2_thumbnail_prompt(config) -> bool:
    """② ImagePromptGenerator.generate_thumbnail_prompt (text モード)"""
    from services.script_generation.image_prompt_generator import (
        ImagePromptGenerator,
    )

    log("\n=== 経路② ImagePromptGenerator.generate_thumbnail_prompt (text) ===")
    generator = ImagePromptGenerator(config)
    recorder = RecordingPort(generator._llm_port)
    generator._llm_port = recorder

    prompt = await generator.generate_thumbnail_prompt(
        theme=THEME,
        script_summary=SCRIPT_SUMMARY,
        topic_title="深部体温と入眠の科学",
    )

    if not recorder.records:
        log("  [②] FAIL: LLM が一度も呼ばれなかった")
        return False

    ok = evaluate_record("②", recorder.records[-1])

    # sanitize 通過確認: 最終プロンプトに日本語が残っていないこと
    jp_chars = JAPANESE_CHARS.findall(prompt or "")
    if jp_chars:
        log(f"  [②] FAIL: sanitize 後のプロンプトに日本語が残存: {''.join(jp_chars[:20])!r}")
        ok = False
    else:
        log("  [②] sanitize 通過確認: OK（日本語混入なし）")
    log(f"  [②] 最終プロンプト先頭 100 字: {(prompt or '')[:100]!r}")
    return ok


async def path3_segment_prompt(config) -> bool:
    """③ ImagePromptGenerator.generate_prompt（セグメント背景用, text モード）"""
    from services.script_generation.image_prompt_generator import (
        ImagePromptGenerator,
    )

    log("\n=== 経路③ ImagePromptGenerator.generate_prompt (text) ===")
    generator = ImagePromptGenerator(config)
    recorder = RecordingPort(generator._llm_port)
    generator._llm_port = recorder

    segment = ScriptSegment(
        segment_id="deep_dive_1",
        segment_type="deep_dive",
        topic_title="深部体温と入眠の科学",
        turns=[
            {"speaker": "A", "text": "就寝90分前の入浴が入眠を助けるって本当？"},
            {"speaker": "B", "text": "深部体温が一度上がってから急降下するタイミングで強い眠気が来るんです。"},
            {"speaker": "A", "text": "室温は18度から19度が推奨されているんですね。"},
        ],
    )

    prompt = await generator.generate_prompt(segment, visual_identity=None)

    if not recorder.records:
        log("  [③] FAIL: LLM が一度も呼ばれなかった")
        return False

    ok = evaluate_record("③", recorder.records[-1])

    jp_chars = JAPANESE_CHARS.findall(prompt or "")
    if jp_chars:
        log(f"  [③] WARNING: プロンプトに日本語が混入: {''.join(jp_chars[:20])!r}")
    log(f"  [③] 最終プロンプト先頭 100 字: {(prompt or '')[:100]!r}")
    return ok


async def main() -> int:
    config = load_config()
    ollama_cfg = config.yaml.script_generator.ollama
    log("DeepSeekV4Flash 移行スモークテスト")
    log(f"base_url={ollama_cfg.base_url}")
    log(f"ollama.model={ollama_cfg.model}")
    log(f"curator_model={config.yaml.script_generator.orchestrator.curator_model}")
    log(f"inject_no_think={getattr(ollama_cfg, 'inject_no_think', '(未定義)')}")

    results = {
        "① VisualPalette (json_object)": await path1_visual_palette(config),
        "② ThumbnailPrompt (text)": await path2_thumbnail_prompt(config),
        "③ SegmentPrompt (text)": await path3_segment_prompt(config),
    }

    log("\n=== 結果サマリ ===")
    all_ok = True
    for name, ok in results.items():
        log(f"  {'PASS' if ok else 'FAIL'}: {name}")
        all_ok = all_ok and ok

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text("\n".join(_log_lines) + "\n", encoding="utf-8")
    print(f"\nログ保存先: {LOG_PATH}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
