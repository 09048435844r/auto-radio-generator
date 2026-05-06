"""Smoke test: structured_facts → FactSheet → key_facts → 台本 への反映確認

Phase 3 強化（Curator top_facts limit=50, key_facts 10〜15 件指示, 言語制約）の
動作確認用スモークテスト。output/_phase3_test/research_brief.json を入力として
台本生成を実行し、以下を計測する:

  1. CuratedTopic.key_facts の平均件数（10 件以上を目標）
  2. 簡体字中国語のリーク件数（0 件を期待）
  3. 元 structured_facts 由来の数値・固有名詞が台本本文に何件現れるか
"""
import asyncio
import json
import re
import sys
from pathlib import Path

# Windows console (cp932) 対策: stdout/stderr を UTF-8 にする
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.models import load_config
from core.models.artifacts import ResearchBrief
from core.session_manager import SessionManager
from services.pipeline import execute_scripting_phase
from workflow import ProgressCallback


# 簡体字中国語のみで使われる代表的な文字（**日本語の常用漢字には存在しない / 形が異なる**もののみ）
# Qwen3.5-122B の中文混入を検出するために使う。完全網羅ではないがリーク兆候の可視化に十分。
# NOTE: 「学」「国」「号」「会」など日本語と同形のものは除外（false positive を避ける）。
# 含むのは「日中で字形が異なり、簡体字 OR 中国語専用文字」のみ:
#   时(時) 间(間) 问(問) 题(題) 细(細) 说(説) 见(見) 进(進) 过(過) 开(開) 关(関)
#   读(読) 书(書) 车(車) 实(実) 价(価) 约(約) 让(譲) 觉(覚) 这 那 们
SIMPLIFIED_DIFFERENTIATORS = set("这那们时间问题细说见进过开关读书车实价该约让觉")


def count_simplified_chinese(text: str) -> dict:
    """テキスト中の簡体字差分文字の個数と検出文字一覧を返す"""
    found: dict[str, int] = {}
    for ch in text:
        if ch in SIMPLIFIED_DIFFERENTIATORS:
            found[ch] = found.get(ch, 0) + 1
    return found


def extract_fact_terms(structured_facts: dict) -> list[str]:
    """structured_facts から「台本で登場すべき具体語」（数値+単位、固有名詞）を抽出"""
    terms: list[str] = []
    for kn in (structured_facts.get("key_numbers") or []):
        v = (kn.get("value") or "").strip()
        u = (kn.get("unit") or "").strip()
        if v:
            terms.append(f"{v}{u}".strip())
    for ke in (structured_facts.get("key_entities") or []):
        n = (ke.get("name") or "").strip()
        if n:
            terms.append(n)
    return [t for t in terms if t]


async def main():
    config = load_config(PROJECT_ROOT)

    brief = ResearchBrief.model_validate_json(
        (PROJECT_ROOT / "output" / "_phase3_test" / "research_brief.json").read_text(encoding="utf-8")
    )
    print(f"=== Smoke test: {brief.theme!r} (mode={brief.research_mode}) ===")
    print(f"structured_facts: k_num={len(brief.structured_facts.get('key_numbers') or [])}, "
          f"k_ent={len(brief.structured_facts.get('key_entities') or [])}, "
          f"surprising={len(brief.structured_facts.get('surprising_claims') or [])}, "
          f"controversies={len(brief.structured_facts.get('controversies') or [])}")
    fact_terms = extract_fact_terms(brief.structured_facts or {})
    print(f"期待される事実語（数値+単位 / 固有名詞）{len(fact_terms)} 件")
    for t in fact_terms[:10]:
        print(f"  - {t}")

    # 専用セッション
    sm = SessionManager(project_root=PROJECT_ROOT, session_id=f"smoke_{brief.session_id}")
    print(f"\nSession dir: {sm.session_dir}")

    # 進捗ログは標準出力へ
    cb = ProgressCallback(
        log_callback=lambda m: print(m),
        progress_callback=lambda r, d: print(f"[{r*100:.0f}%] {d}"),
    )

    # 台本生成
    artifact = await execute_scripting_phase(
        research_brief=brief,
        session_manager=sm,
        config=config,
        provider="ollama",
        callbacks=cb,
    )

    # 計測
    print("\n=== 計測 ===")

    # 1. key_facts の件数（curation_result.json 経由で確認）
    cur_path = sm.get_curation_result_path()
    if cur_path.exists():
        cur = json.loads(cur_path.read_text(encoding="utf-8"))
        topics = cur.get("topics") or []
        kf_counts = [len(t.get("key_facts") or []) for t in topics]
        print(f"\n[1] CuratedTopic.key_facts 件数: {kf_counts} (avg={sum(kf_counts)/max(1,len(kf_counts)):.1f}, target=10〜15)")
        for i, t in enumerate(topics, 1):
            print(f"    Topic {i}: {t.get('title')!r} key_facts={len(t.get('key_facts') or [])}件")
    else:
        print("[1] curation_result.json なし（preset 経路の可能性）")

    # 2. 簡体字リーク
    script = artifact.script
    full_text = "\n".join(s.text or "" for s in script.sections if s.text)
    leaks = count_simplified_chinese(full_text)
    print(f"\n[2] 簡体字リーク: {sum(leaks.values())}件 / 文字種={len(leaks)}")
    if leaks:
        for ch, n in sorted(leaks.items(), key=lambda x: -x[1]):
            print(f"    '{ch}' x {n}")
    else:
        print("    (リークなし)")

    # 3. 事実語の出現
    hits = []
    for term in fact_terms:
        if term and term in full_text:
            hits.append(term)
    print(f"\n[3] 事実語の台本反映: {len(hits)}/{len(fact_terms)} 件")
    print(f"    Hit: {hits[:15]}")
    miss = [t for t in fact_terms if t not in full_text]
    print(f"    Miss: {miss[:15]}")

    # 4. 台本サイズ
    print(f"\n[4] 台本: {len(script.sections)} ターン / 本文 {len(full_text)} 文字")
    print(f"    タイトル: {script.title!r}")


if __name__ == "__main__":
    asyncio.run(main())
