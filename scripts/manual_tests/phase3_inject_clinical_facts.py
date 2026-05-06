"""Phase 3 実機検証用 (clinical edition):

structured_facts に「効果サイズ・95%信頼区間・p値・ハザード比」など、リサーチ側で
本来抽出されるべき**統計指標**を含めた fixture を作る。
output/_phase3_clinical/research_brief.json に書き出す。

意図: 台本生成 LLM が key_facts → 台本本文への反映で、これらの
具体数値（例: 95%CI: 1.32-2.18 / Cohen's d=0.85 / p<0.001）まで
取り込めるかを評価する。
"""
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
OUT = PROJECT_ROOT / "output" / "_phase3_clinical" / "research_brief.json"
OUT.parent.mkdir(parents=True, exist_ok=True)

THEME = "HIIT高強度インターバルトレーニングと内臓脂肪減少の臨床エビデンス"

# 本物のリサーチ生テキストの代わりに、人手で書いた要約。LLM が「リサーチ全文には書いてない」
# と誤判定しないよう、structured_facts に出てくる数値・固有名詞を本文にも散りばめてある。
RESEARCH_CONTENT = """\
# HIIT（高強度インターバルトレーニング）と内臓脂肪の関係に関する臨床エビデンス

## 主要メタアナリシス
2024年に Sports Medicine 誌に掲載された Maillard らのメタアナリシスは、HIIT vs MICT
（中強度持続性運動）を比較した39件のRCTを統合した。総被験者は2,418名、平均年齢
38.4歳、追跡期間8〜16週。主要評価項目は内臓脂肪面積（VAT）の変化。

結果として HIIT 群は MICT 群と比較して内臓脂肪面積を平均14.8%多く減少させ、
標準化平均差（SMD）は 0.42（95%CI: 0.27-0.57, p<0.001）であった。
特に肥満（BMI≥30）サブグループでは SMD 0.85（95%CI: 0.61-1.09, p<0.0001）と
効果サイズが顕著に大きかった。

## サブ解析
腰囲ウエスト周囲径の減少は HIIT 群で平均3.2cm（95%CI: 2.4-4.0）、MICT 群で
1.8cm（95%CI: 1.1-2.5）。両群間の差は統計的に有意（p=0.002）。

体脂肪率の絶対減少は HIIT 群で2.1%pt（95%CI: 1.5-2.7）、MICT 群で1.4%pt（95%CI: 0.9-1.9）。
HIIT は MICT の約1.5倍の効率で脂肪減少を達成。

時間効率は特筆すべき指標である: HIIT 群の平均運動時間は週84分、MICT 群は週225分で、
HIIT は MICT の37%の時間で同等以上の効果を出した。

## 心血管リスク
追跡期間内の心血管イベント（HR 0.71, 95%CI: 0.58-0.87）は HIIT 群で有意に低く、
インスリン感受性の指標 HOMA-IR も HIIT 群で1.42 から 1.05 へと26%改善した。

## 個別研究の例
- Trapp 2008 RCT (n=45, 15週間): HIIT 群で皮下腹部脂肪が17%減少、対照群は変化なし
- Heydari 2012 RCT (n=46, 12週間): HIIT 群で内臓脂肪が17%、皮下脂肪が9.5%減少
- Zhang 2017 RCT (n=80, 12週間): 高齢肥満女性で HIIT が MICT より腹部内臓脂肪を
  約2倍効果的に減少（SMD=0.92, 95%CI: 0.45-1.39）

## 安全性
副作用としては筋骨格系の損傷リスクが MICT より約1.6倍高いという報告（HR 1.58,
95%CI: 1.12-2.23）があり、開始4週間は監視下のプロトコル推奨。
"""

structured_facts = {
    "key_numbers": [
        {"value": "39", "unit": "件", "context": "Maillard 2024 メタアナリシスが統合した RCT 件数（HIIT vs MICT 比較）", "source_idx": 1},
        {"value": "2418", "unit": "名", "context": "Maillard 2024 メタアナリシスの総被験者数", "source_idx": 1},
        {"value": "14.8", "unit": "%", "context": "HIIT 群が MICT 群と比較して内臓脂肪面積を多く減少させた割合（メタアナリシス）", "source_idx": 1},
        {"value": "0.42", "unit": "(SMD)", "context": "HIIT vs MICT の内臓脂肪減少の標準化平均差（95%CI: 0.27-0.57, p<0.001）", "source_idx": 1},
        {"value": "0.85", "unit": "(SMD)", "context": "肥満（BMI≥30）サブグループでの効果サイズ（95%CI: 0.61-1.09, p<0.0001）", "source_idx": 1},
        {"value": "3.2", "unit": "cm", "context": "HIIT 群のウエスト周囲径平均減少（95%CI: 2.4-4.0）", "source_idx": 1},
        {"value": "2.1", "unit": "%pt", "context": "HIIT 群の体脂肪率絶対減少（95%CI: 1.5-2.7）", "source_idx": 1},
        {"value": "84", "unit": "分/週", "context": "HIIT 群の平均運動時間", "source_idx": 1},
        {"value": "225", "unit": "分/週", "context": "MICT 群の平均運動時間", "source_idx": 1},
        {"value": "37", "unit": "%", "context": "HIIT は MICT の何%の時間で同等以上の脂肪減少効果を出したか", "source_idx": 1},
        {"value": "0.71", "unit": "(HR)", "context": "HIIT 群の心血管イベントのハザード比（95%CI: 0.58-0.87）", "source_idx": 1},
        {"value": "26", "unit": "%", "context": "HIIT 群のインスリン感受性 HOMA-IR 改善率（1.42 → 1.05）", "source_idx": 1},
        {"value": "1.58", "unit": "(HR)", "context": "HIIT の筋骨格系損傷リスクのハザード比（vs MICT、95%CI: 1.12-2.23）", "source_idx": 1},
        {"value": "0.92", "unit": "(SMD)", "context": "Zhang 2017 RCT の高齢肥満女性での HIIT 効果サイズ（95%CI: 0.45-1.39）", "source_idx": 4},
    ],
    "key_entities": [
        {"name": "Maillard 2024 メタアナリシス", "type": "study", "role": "Sports Medicine 誌掲載、HIIT vs MICT を39件のRCTで統合", "source_idx": 1},
        {"name": "Trapp 2008 RCT", "type": "study", "role": "n=45, 15週間 HIIT 介入で皮下腹部脂肪が17%減少", "source_idx": 2},
        {"name": "Heydari 2012 RCT", "type": "study", "role": "n=46, 12週間 HIIT で内臓脂肪17%・皮下脂肪9.5%減", "source_idx": 3},
        {"name": "Zhang 2017 RCT", "type": "study", "role": "n=80 高齢肥満女性で HIIT が MICT の約2倍腹部内臓脂肪を減らした", "source_idx": 4},
        {"name": "MICT", "type": "concept", "role": "Moderate-Intensity Continuous Training（中強度持続性運動）", "source_idx": 1},
        {"name": "HOMA-IR", "type": "concept", "role": "インスリン抵抗性の指標、低値ほどインスリン感受性が良い", "source_idx": 1},
        {"name": "標準化平均差（SMD）", "type": "concept", "role": "メタアナリシスで効果サイズを比較する統計指標、Cohen's d 系列", "source_idx": 1},
        {"name": "Sports Medicine", "type": "concept", "role": "スポーツ医学分野の主要査読付き学術誌", "source_idx": 1},
    ],
    "surprising_claims": [
        {
            "statement": "HIIT は MICT の37%の運動時間で同等以上の内臓脂肪減少効果を出す",
            "why_surprising": "「運動時間が長いほど脂肪が減る」という直感を覆す",
            "source_idx": 1,
        },
        {
            "statement": "肥満サブグループでの HIIT の効果サイズ SMD=0.85 は『大効果』レベル",
            "why_surprising": "Cohen の慣例で 0.8 以上は大効果。臨床介入研究では稀",
            "source_idx": 1,
        },
        {
            "statement": "HIIT 群は心血管イベントが MICT 群より29%少ない（HR 0.71）",
            "why_surprising": "「高強度＝心臓に悪い」のイメージと逆の結果",
            "source_idx": 1,
        },
    ],
    "controversies": [
        {
            "position_a": "HIIT は短時間で効率的に脂肪を落とせるため一般人にも推奨できる",
            "position_b": "HIIT は筋骨格系損傷リスクが MICT より1.6倍高い（HR 1.58）ため初心者には監視必須",
            "source_indices": [1],
        },
        {
            "position_a": "標準化平均差 0.42 は中等度効果で、HIIT の優位性は実用的には限定的",
            "position_b": "肥満サブグループでは SMD 0.85 と大効果に達するため、ターゲット集団では明確に優位",
            "source_indices": [1],
        },
    ],
}

brief = {
    "session_id": "20260506_clinical_test",
    "theme": THEME,
    "research_mode": "lecture",
    "created_at": "2026-05-06T18:00:00",
    "research_content": RESEARCH_CONTENT,
    "research_sources": [],
    "queries": ["HIIT 内臓脂肪 メタアナリシス 効果サイズ"],
    "angle": "数値根拠で語る HIIT の真実",
    "curated_topics": None,
    "structured_facts": structured_facts,
    "perplexity_usage": None,
    "gemini_usage_planning": None,
}

with OUT.open("w", encoding="utf-8") as f:
    json.dump(brief, f, ensure_ascii=False, indent=2)

print(f"✓ Wrote clinical test brief:")
print(f"  {OUT}")
print(f"  key_numbers      : {len(brief['structured_facts']['key_numbers'])}")
print(f"  key_entities     : {len(brief['structured_facts']['key_entities'])}")
print(f"  surprising_claims: {len(brief['structured_facts']['surprising_claims'])}")
print(f"  controversies    : {len(brief['structured_facts']['controversies'])}")
