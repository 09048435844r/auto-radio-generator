"""PR-E (Issue B): プロンプト明示圧力強化の回帰テスト。

本 PR の効果（LLM がフィールド省略をやめる）は実運用でしか検証できないが、
「プロンプトから重要な明示圧力の文言が将来のリファクタ等で消えないこと」は
単体テストで担保できる。このファイルはそのセーフティネット。

意図:
- TopicCurator プロンプトに「title は必須・20〜40文字・数値 or 固有名詞を含む」指示が存在する
- FactExtractor プロンプトに「facts は最低 5 件・空配列禁止」指示が存在する
- FactExtractor プロンプトの extractor_reasoning に「空文字禁止」指示が存在する
- FactExtractor ユーザープロンプト例示が英語圏 AI 文脈ではなく日本語医療系に差し替わっている
"""
from unittest.mock import MagicMock


def _load_curation_system_prompt() -> str:
    from core.prompt_manager import PromptManager
    return PromptManager().get_prompt("orchestrator", "curation")


def _load_fact_extractor_system_prompt() -> str:
    from core.prompt_manager import PromptManager
    return PromptManager().get_prompt("orchestrator", "fact_extractor")


def _build_topic_curator_user_prompt(mock_app_config) -> str:
    """TopicCurator の user prompt を構築（LLM 呼び出しせず文字列だけ取得）。"""
    from services.script_generation.topic_curator import TopicCurator

    mock_app_config.yaml.script_generator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.curator_model = "test"
    mock_app_config.yaml.script_generator.orchestrator.max_topics = 3
    mock_app_config.yaml.script_generator.orchestrator.topic_curator = MagicMock(max_tokens=8192)

    port = MagicMock()
    port.provider_name = "gemini"
    curator = TopicCurator(port, mock_app_config)

    rd = MagicMock(mode="trivia", content="dummy research content")
    return curator._build_curation_user_prompt(rd, target_count=3)


def _build_fact_extractor_user_prompt(mock_app_config) -> str:
    """FactExtractor の user prompt を構築。"""
    from services.script_generation.fact_extractor import FactExtractor

    mock_app_config.yaml.script_generator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.curator_model = "test"
    mock_app_config.yaml.script_generator.orchestrator.fact_extractor = MagicMock(
        model="", max_facts=30, max_tokens=8192,
    )
    port = MagicMock()
    port.provider_name = "gemini"
    extractor = FactExtractor(port, mock_app_config)

    rd = MagicMock(mode="trivia", content="dummy research content")
    return extractor._build_fact_extractor_user_prompt("亜麻仁油の健康効果", rd)


# ---------------------------------------------------------------------------
# TopicCurator: title 必須化 + 文字数 + 具体例
# ---------------------------------------------------------------------------

def test_curation_system_prompt_declares_title_required():
    """curation プロンプトで title の必須性と文字数が明示されている。"""
    p = _load_curation_system_prompt()
    # 「必須」「省略禁止」「空文字」など、省略を封じる文言がどこかにある
    assert any(kw in p for kw in ["必ず記述", "省略・空文字", "空文字・省略"])
    # 文字数制約
    assert "20〜40文字" in p
    # 「数値か固有名詞を最低1つ含める」制約
    assert "数値" in p and "固有名詞" in p


def test_curation_system_prompt_includes_good_and_bad_title_examples():
    """良い例 / 悪い例 の両方がプロンプトに含まれている（C: few-shot 強化）。"""
    p = _load_curation_system_prompt()
    # 悪い例（短すぎる国名+研究種別など）が NG として示されている
    assert "デンマークの研究" in p and "❌" in p
    # 良い例（数値+固有名詞を含む具体タイトル）が ✅ で示されている
    assert "デンマーク研究で70%が関節痛軽減" in p
    assert "✅" in p


def test_curation_system_prompt_forbids_title_placeholders():
    """'トピック1' のようなプレースホルダ使用を明示的に禁止している。"""
    p = _load_curation_system_prompt()
    assert "プレースホルダ" in p or "トピック1" in p


def test_curator_user_prompt_example_placeholder_reflects_title_constraint(mock_app_config):
    """user prompt の JSON 例示が 'トピックタイトル' プレースホルダを卒業している。"""
    up = _build_topic_curator_user_prompt(mock_app_config)
    # 旧プレースホルダ "トピックタイトル" 単独ではなく、制約付きの placeholder になっている
    # （具体例 or 制約記述を含む）
    assert "20〜40文字" in up
    assert "数値" in up or "固有名詞" in up


# ---------------------------------------------------------------------------
# FactExtractor: facts=0 回避指示
# ---------------------------------------------------------------------------

def test_fact_extractor_system_prompt_declares_minimum_facts():
    """facts=[] を避け、最低 5 件を抽出する指示が存在する。"""
    p = _load_fact_extractor_system_prompt()
    assert "最低 5 件" in p or "最低5件" in p
    # 「空配列禁止」相当の文言
    assert any(kw in p for kw in ["空配列", "空の配列"])


def test_fact_extractor_system_prompt_lowers_the_bar():
    """意外性スコア 4〜6（一般人にとって新情報）を積極的に含める指示が存在する。"""
    p = _load_fact_extractor_system_prompt()
    # スコア 4〜6 を積極的に含めるハードル緩和文言
    assert "4〜6" in p
    assert "一般人" in p


def test_fact_extractor_system_prompt_declares_extractor_reasoning_required():
    """extractor_reasoning を空文字にしない指示が存在する（副次改善）。"""
    p = _load_fact_extractor_system_prompt()
    assert "extractor_reasoning" in p
    # 「空文字禁止」相当
    assert "空文字" in p


def test_fact_extractor_user_prompt_example_uses_japanese_scientific_context(mock_app_config):
    """user prompt の例示が英語圏 AI 文脈（1200万円 / OpenAI）から日本語医療系に差し替わっている。"""
    up = _build_fact_extractor_user_prompt(mock_app_config)
    # 新しい例（日本語医療系）
    assert "亜麻仁油" in up or "デンマーク" in up
    # 旧例示（英語圏 AI 文脈）が撤去されている
    assert "1200万円" not in up
    assert "OpenAI" not in up


def test_fact_extractor_user_prompt_retains_format_constraints(mock_app_config):
    """例示差し替え後も、JSON 形式制約（コードブロック禁止等）が維持されている。"""
    up = _build_fact_extractor_user_prompt(mock_app_config)
    assert "コードブロック" in up and "禁止" in up
    assert "改行" in up  # 改行禁止指示
    # surprise_score の降順指示
    assert "降順" in up


def test_fact_extractor_user_prompt_mentions_minimum_five(mock_app_config):
    """user prompt にも「最低 5 件」指示が明示されている（system prompt との二重圧力）。"""
    up = _build_fact_extractor_user_prompt(mock_app_config)
    assert "最低 5 件" in up or "最低5件" in up
