"""FactChecker - 生成台本のハルシネーション検出エージェント

ScriptOrchestrator が台本を生成し、MetadataGenerator がメタデータを充填した後の
**後処理エージェント**。生成台本（Script）と元のリサーチデータ（ResearchBrief）を
LLM に投げ込み、ハルシネーション・誇張・出典不明な主張を検出して
FactCheckReport を返す。

設計方針:
  - FactExtractor / TopicCurator / ShowRunner と同型のアーキテクチャ
    - ILLMPort 経由で provider-agnostic
    - PromptManager から system_prompt を取得（SSOT）
    - JSON レスポンスをサニタイズ付きでパース
    - last_usage / last_report でトークン使用量と結果を公開

  - **フェイルオープン契約**: 呼び出し側（scripting_phase）は FactChecker の
    例外を except Exception で WARNING に落とすため、本クラス内では
    積極的に raise してよい（パイプラインを止める責任は持たない）。

  - 入力サイズ制限: 台本本文 / リサーチ本文をそれぞれ
    config.fact_checker.script_char_limit / research_char_limit で先頭切り出し。
    Qwen3-Next-80B でもコンテキスト長の暴走を防ぐ。
"""
import json
import logging
from typing import Optional, TYPE_CHECKING

from rich.console import Console

from core.models import AppConfig, LLMUsage
from core.models.fact_check_report import (
    FactCheckIssue,
    FactCheckReport,
    FactCheckSeverity,
)
from core.models.script import Script
from core.utils import sanitize_json_response
from core.prompt_manager import PromptManager
from core.interfaces.llm_port import ILLMPort, LLMRequest

if TYPE_CHECKING:
    from core.interfaces.researcher import ResearchResult

logger = logging.getLogger(__name__)
console = Console()

# severity の SSOT。core/models/fact_check_report.py::FactCheckSeverity と
# 双方向に連動する（プロンプト指示も同 3 値）。
_VALID_SEVERITIES: frozenset[str] = frozenset({"high", "medium", "low"})
_DEFAULT_SEVERITY: FactCheckSeverity = "medium"


class FactChecker:
    """生成台本のハルシネーション・誇張・出典不明な主張を検出するエージェント

    1 回の LLM 呼び出しで台本全体をチェックする。LLM への入力は
    config.fact_checker.script_char_limit / research_char_limit で
    トークン消費を抑制する。
    """

    def __init__(self, llm_port: ILLMPort, config: AppConfig):
        """Initialize FactChecker

        Args:
            llm_port: LLM port interface for provider-agnostic communication
            config: Application configuration
        """
        self._llm = llm_port
        self.config = config
        self.prompt_manager = PromptManager()

        orch_cfg = config.yaml.script_generator.orchestrator
        # FactChecker config (backward compatible: falls back to defaults if not set)
        fc_cfg = getattr(orch_cfg, "fact_checker", None)
        self.fact_checker_model = (getattr(fc_cfg, "model", "") or "").strip() or orch_cfg.curator_model
        self.max_tokens = int(getattr(fc_cfg, "max_tokens", 8192) or 8192)
        self.min_confidence_warning = int(getattr(fc_cfg, "min_confidence_warning", 60) or 60)
        self.script_char_limit = int(getattr(fc_cfg, "script_char_limit", 8000) or 8000)
        self.research_char_limit = int(getattr(fc_cfg, "research_char_limit", 8000) or 8000)

        self.last_usage: Optional[LLMUsage] = None
        # Expose the last successfully-produced FactCheckReport so the pipeline
        # layer can persist it without re-invoking the agent.
        self.last_report: Optional[FactCheckReport] = None

    async def check(
        self,
        theme: str,
        script: Script,
        research_data: "ResearchResult",
        progress_log=None,
    ) -> FactCheckReport:
        """生成台本をリサーチデータと照合してファクトチェックする

        Args:
            theme: 番組のテーマ
            script: 生成済みの Script オブジェクト
            research_data: Perplexity から取得したリサーチ結果
            progress_log: 進捗ログ関数（オプション）

        Returns:
            FactCheckReport: ファクトチェック結果（issues / overall_confidence / summary）

        Raises:
            ValueError: script が空 or research_data.content が空の場合
            Exception: LLM 呼び出し or JSON パース失敗時（呼び出し側でフェイルオープン）
        """
        log = progress_log or (lambda msg: console.print(msg))

        script_text = self._extract_script_text(script)
        if not script_text:
            raise ValueError("FactChecker.check: script has no dialogue text to check")

        research_text = (getattr(research_data, "content", "") or "").strip()
        if not research_text:
            raise ValueError("FactChecker.check: research_data has no content to check against")

        # 入力サイズ制限（先頭から切り出し）
        script_truncated = script_text[: self.script_char_limit]
        research_truncated = research_text[: self.research_char_limit]
        script_was_truncated = len(script_text) > self.script_char_limit
        research_was_truncated = len(research_text) > self.research_char_limit

        log(
            f"[cyan]🔍 ファクトチェック開始 "
            f"(プロバイダー: {self._llm.provider_name}, モデル: {self.fact_checker_model})[/cyan]"
        )
        log(
            f"  台本: {len(script_text)}文字"
            + (f" → 先頭{self.script_char_limit}文字に制限" if script_was_truncated else "")
        )
        log(
            f"  リサーチ: {len(research_text)}文字"
            + (f" → 先頭{self.research_char_limit}文字に制限" if research_was_truncated else "")
        )

        system_prompt = self.prompt_manager.get_prompt("orchestrator", "fact_checker")
        user_prompt = self._build_user_prompt(
            theme=theme,
            script_text=script_truncated,
            research_text=research_truncated,
            script_was_truncated=script_was_truncated,
            research_was_truncated=research_was_truncated,
        )

        try:
            response_text, usage = await self._call_api(system_prompt, user_prompt)
            self.last_usage = usage
            report = self._parse_report_response(response_text)

            log(
                f"[green]✓ ファクトチェック完了: "
                f"信頼度={report.overall_confidence}, issues={len(report.issues)}件[/green]"
            )
            self.last_report = report
            self._emit_warning_if_low_confidence(report)
            self._emit_warnings_for_issues(report)
            return report

        except Exception as e:
            log(f"[red]✗ ファクトチェックエラー: {e}[/red]")
            logger.error(f"FactChecker.check failed: {e}", exc_info=True)
            raise

    # ------------------------------------------------------------------
    # Internal: script extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_script_text(script: Script) -> str:
        """Script のセリフを 1 つの文字列に結合する

        DialogueTurn のうち is_dialogue() が True のものだけを対象とし、
        speaker/text を「A: text」「B: text」形式で連結する。
        action（ジングル等）はスキップ。
        """
        lines: list[str] = []
        for turn in getattr(script, "sections", []) or []:
            if not getattr(turn, "is_dialogue", lambda: False)():
                continue
            speaker = getattr(turn, "speaker", "?") or "?"
            text = (getattr(turn, "text", "") or "").strip()
            if not text:
                continue
            lines.append(f"{speaker}: {text}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal: prompt building
    # ------------------------------------------------------------------

    def _build_user_prompt(
        self,
        theme: str,
        script_text: str,
        research_text: str,
        script_was_truncated: bool,
        research_was_truncated: bool,
    ) -> str:
        """FactChecker 用ユーザープロンプトを構築"""
        parts: list[str] = []
        parts.append(f"## テーマ\n{theme}\n\n")
        parts.append(
            "## 生成された台本（チェック対象）\n"
            + ("**注**: 台本が長すぎるため先頭部分のみ評価対象\n" if script_was_truncated else "")
            + script_text
            + "\n\n"
        )
        parts.append(
            "## リサーチデータ（事実の照合元）\n"
            + ("**注**: リサーチが長すぎるため先頭部分のみ提示\n" if research_was_truncated else "")
            + research_text
            + "\n\n"
        )
        parts.append(
            "## 指示\n"
            "上記の台本のセリフを 1 つずつリサーチデータと照合し、"
            "ハルシネーション・誇張・出典不明な主張を検出してください。\n"
            "- system プロンプトの severity 基準と overall_confidence 目安に従う\n"
            "- issues は severity 降順（high → medium → low）で並べる\n"
            "- 重大な問題が無い場合は issues=[]、overall_confidence=95 以上で返す\n"
            "- JSON のみ出力（コードブロック・前置き・後置き禁止）\n"
        )
        return "".join(parts)

    # ------------------------------------------------------------------
    # Internal: API call (same pattern as FactExtractor / TopicCurator)
    # ------------------------------------------------------------------

    async def _call_api(self, system_prompt: str, user_prompt: str) -> tuple[str, LLMUsage]:
        """Call LLM API for fact checking"""
        # Defensive: if configured model looks Ollama-specific but provider isn't Ollama, fall back
        model_to_use = self.fact_checker_model
        if model_to_use and self._llm.provider_name != "ollama":
            if ":" in model_to_use or model_to_use.startswith("ollama/"):
                logger.warning(
                    f"fact_checker.model '{model_to_use}' appears to be Ollama-specific "
                    f"but provider is '{self._llm.provider_name}'. Using provider default."
                )
                model_to_use = None

        request = LLMRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model_to_use,
            max_tokens=self.max_tokens,
            temperature=0.2,  # ファクトチェックは最低温度で安定性を確保
            response_format="json",
        )

        response = await self._llm.generate(request)

        # finish_reason="length" は fail-fast。partial JSON を信用しない。
        # 呼び出し側でフェイルオープンするため、ここで raise しても
        # パイプラインは止まらない（factcheck_report.json が生成されないだけ）。
        if response.finish_reason == "length":
            msg = (
                "FactChecker output was truncated (finish_reason=length). "
                f"Current max_tokens={self.max_tokens}. "
                "Increase fact_checker.max_tokens in config.yaml or lower script/research_char_limit. "
                "Aborting rather than returning a partial FactCheckReport."
            )
            logger.error(msg)
            raise RuntimeError(msg)

        logger.debug(
            f"FactChecker API: provider={response.usage.provider}, model={response.usage.model_name}, "
            f"in={response.usage.input_tokens}, out={response.usage.output_tokens}"
        )
        return response.content, response.usage

    # ------------------------------------------------------------------
    # Internal: response parsing
    # ------------------------------------------------------------------

    def _parse_report_response(self, response_text: str) -> FactCheckReport:
        """API レスポンスを FactCheckReport に変換。失敗時は sanitize を試行。"""
        try:
            data = json.loads(response_text.strip(), strict=False)
        except json.JSONDecodeError as e:
            logger.error(f"[FactChecker] JSON parse error: {e}")
            logger.error(
                f"[FactChecker] Full raw response text ({len(response_text)} chars):\n"
                f"{'=' * 80}\n{response_text}\n{'=' * 80}"
            )
            console.print("[yellow]⚠️ FactChecker JSONパースエラー。サニタイズ処理を試行中...[/yellow]")
            cleaned = sanitize_json_response(response_text, "FactChecker")
            try:
                data = json.loads(cleaned, strict=False)
                console.print("[green]✓ サニタイズ後のパースに成功[/green]")
            except json.JSONDecodeError as e2:
                logger.error(f"[FactChecker] JSON parse failed after sanitization: {e2}")
                console.print("[red]✗ FactChecker: サニタイズ後もJSONパース失敗[/red]")
                raise

        # overall_confidence: 0-100 の整数にクランプ
        try:
            confidence = int(data.get("overall_confidence", 50))
        except (TypeError, ValueError):
            confidence = 50
        confidence = max(0, min(100, confidence))

        summary = str(data.get("summary", "") or "").strip()

        # issues: 各エントリを防御的に正規化
        issues: list[FactCheckIssue] = []
        for raw_i in data.get("issues", []) or []:
            if not isinstance(raw_i, dict):
                logger.warning(
                    "[FactChecker] Skipping non-dict issue entry: %r", raw_i
                )
                continue
            try:
                raw_severity = str(raw_i.get("severity", "") or "").strip().lower()
                if raw_severity in _VALID_SEVERITIES:
                    severity: FactCheckSeverity = raw_severity  # type: ignore[assignment]
                else:
                    if raw_severity:
                        logger.warning(
                            f"[FactChecker] Unknown severity '{raw_severity}' "
                            f"(not in SSOT {sorted(_VALID_SEVERITIES)}); "
                            f"normalizing to '{_DEFAULT_SEVERITY}'."
                        )
                    severity = _DEFAULT_SEVERITY

                script_quote = str(raw_i.get("script_quote", "") or "").strip()
                issue_text = str(raw_i.get("issue", "") or "").strip()
                suggestion = str(raw_i.get("suggestion", "") or "").strip()

                # 必須フィールドが空の場合はスキップ（破損エントリ）
                if not script_quote or not issue_text:
                    logger.warning(
                        "[FactChecker] Skipping issue with empty script_quote or issue: %r",
                        raw_i,
                    )
                    continue

                issues.append(FactCheckIssue(
                    severity=severity,
                    script_quote=script_quote,
                    issue=issue_text,
                    suggestion=suggestion,
                ))
            except Exception as e:
                logger.warning(f"[FactChecker] Skipping malformed issue: {raw_i} ({e})")
                continue

        # severity 降順で並べる（high → medium → low）
        _severity_rank = {"high": 0, "medium": 1, "low": 2}
        issues.sort(key=lambda x: _severity_rank.get(x.severity, 99))

        return FactCheckReport(
            overall_confidence=confidence,
            issues=issues,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # Internal: warning emission
    # ------------------------------------------------------------------

    def _emit_warning_if_low_confidence(self, report: FactCheckReport) -> None:
        """overall_confidence が閾値以下なら processing_log.txt に WARNING を残す"""
        if report.overall_confidence <= self.min_confidence_warning:
            logger.warning(
                "[FactChecker] Low confidence detected: overall_confidence=%d "
                "(threshold=%d). Manual review recommended. summary=%r",
                report.overall_confidence,
                self.min_confidence_warning,
                report.summary[:200],
            )

    def _emit_warnings_for_issues(self, report: FactCheckReport) -> None:
        """high / medium severity の issues を WARNING ログに残す（PR-C/F の収集機構経由）"""
        for issue in report.issues:
            if issue.severity == "high":
                logger.warning(
                    "[FactChecker][HIGH] %s | quote=%r",
                    issue.issue[:200],
                    issue.script_quote[:120],
                )
            elif issue.severity == "medium":
                logger.warning(
                    "[FactChecker][MEDIUM] %s | quote=%r",
                    issue.issue[:200],
                    issue.script_quote[:120],
                )
            # low は WARNING にしない（ログ汚染回避、UI 表示にのみ含まれる）
