"""Phase 3 実機検証用: structured_facts を注入した research_brief を作る。

リサーチ側 Phase 2（structured_facts 出力）が未実装のため、
本スクリプトは台本側の Phase 3 経路を検証するためのテストフィクスチャを作る。
合成 structured_facts は元 research_content から人手で抽出した内容の縮約版。
"""
import json
from pathlib import Path

SOURCE = Path("output/20260502_021602/research_brief.json")
OUT = Path("output/_phase3_test/research_brief.json")
OUT.parent.mkdir(parents=True, exist_ok=True)

with SOURCE.open(encoding="utf-8") as f:
    brief = json.load(f)

# === 合成 structured_facts ===
# 実 research_content（内臓脂肪のメリデメ・落とし方、lecture モード、18,568 文字）
# から人手で抽出した代表的なファクト。
# interface_spec.md 3.1 節の形式に準拠。
# 注: 本来はリサーチ側パイプラインが生成する。本テストでは台本側 Phase 3
#     コードパスの実機検証のみが目的。
brief["structured_facts"] = {
    "key_numbers": [
        {
            "value": "100",
            "unit": "cm²",
            "context": "CTスキャンで内臓脂肪面積が100cm²超で内臓脂肪型肥満と診断される",
            "source_idx": 3,
        },
        {
            "value": "85",
            "unit": "cm",
            "context": "ウエスト周囲径が男性85cm以上で内臓脂肪型肥満が疑われる",
            "source_idx": 3,
        },
        {
            "value": "90",
            "unit": "cm",
            "context": "ウエスト周囲径が女性90cm以上で内臓脂肪型肥満が疑われる",
            "source_idx": 3,
        },
        {
            "value": "5",
            "unit": "kg",
            "context": "体重を5kg減らすだけで内臓脂肪は大幅に減少しメタボリックシンドロームのリスクが下がる",
            "source_idx": 9,
        },
    ],
    "key_entities": [
        {
            "name": "メタボリックシンドローム",
            "type": "concept",
            "role": "内臓脂肪型肥満を中核とする生活習慣病の総称、診断基準は腹囲＋脂質・血圧・血糖の2項目以上",
            "source_idx": 1,
        },
        {
            "name": "アディポサイトカイン",
            "type": "concept",
            "role": "脂肪細胞から分泌される生理活性物質、善玉(アディポネクチン)と悪玉(TNF-α・レジスチン等)に分類",
            "source_idx": 2,
        },
        {
            "name": "GLP-1受容体作動薬",
            "type": "technology",
            "role": "内臓脂肪型肥満症の治療薬、食欲抑制とインスリン分泌促進で体重減少を促す",
            "source_idx": 11,
        },
        {
            "name": "HIIT",
            "type": "technology",
            "role": "高強度インターバルトレーニング、短時間で内臓脂肪を効率的に燃焼させる運動法",
            "source_idx": 7,
        },
    ],
    "surprising_claims": [
        {
            "statement": "内臓脂肪は皮下脂肪より代謝活性が高く溜まりやすい一方で、運動・食事改善で皮下脂肪より先に落ちやすい",
            "why_surprising": "見た目に出る皮下脂肪より見えない内臓脂肪のほうが先に減るという直感に反する事実",
            "source_idx": 5,
        },
        {
            "statement": "BMIが正常範囲でも内臓脂肪が過剰な「隠れ肥満」が日本人成人の約20%に存在する",
            "why_surprising": "見た目では判別できず、健診で初めて発覚するケースが多い",
            "source_idx": 6,
        },
        {
            "statement": "極端なカロリー制限はかえって基礎代謝低下とリバウンドを招き内臓脂肪減少に逆効果となる",
            "why_surprising": "「食べなければ痩せる」という常識と真逆のメカニズム",
            "source_idx": 8,
        },
    ],
    "controversies": [
        {
            "position_a": "BMI基準で正常範囲なら内臓脂肪を気にする必要はない",
            "position_b": "BMIに関わらずウエスト周囲径と腹部CTで内臓脂肪量を独立に評価すべき",
            "source_indices": [6, 9],
        },
        {
            "position_a": "有酸素運動が内臓脂肪減少に最も効果的",
            "position_b": "筋トレ＋HIITによる短時間高強度運動が現代エビデンスでは優位",
            "source_indices": [7, 10],
        },
    ],
}

with OUT.open("w", encoding="utf-8") as f:
    json.dump(brief, f, ensure_ascii=False, indent=2)

print(f"✓ Wrote test brief with synthesized structured_facts:")
print(f"  {OUT}")
print(f"  key_numbers      : {len(brief['structured_facts']['key_numbers'])}")
print(f"  key_entities     : {len(brief['structured_facts']['key_entities'])}")
print(f"  surprising_claims: {len(brief['structured_facts']['surprising_claims'])}")
print(f"  controversies    : {len(brief['structured_facts']['controversies'])}")
