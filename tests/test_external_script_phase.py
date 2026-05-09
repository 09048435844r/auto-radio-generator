"""execute_external_script_phase のテスト

Step 3 外部台本モード化の commit 4。Phase 1+2 を完全 bypass し、VerifiedScript JSON
から Script + segments + pre_built_metadata を構築する phase の挙動を担保する。
"""
import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from core.models.script import Script, RadioScriptArtifact
from core.session_manager import SessionManager
from services.pipeline import (
    execute_external_script_phase,
    ExternalScriptPhaseResult,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "verified_script_sample.json"


def _make_session_manager(tmp_path: Path) -> SessionManager:
    return SessionManager(project_root=tmp_path, session_id="ext_test")


def _make_callbacks() -> MagicMock:
    cb = MagicMock()
    cb.log = MagicMock()
    return cb


# ---------------------------------------------------------------------------
# (1) VerifiedScript fixture から Script + segments + pre_built_metadata を構築する
# ---------------------------------------------------------------------------

def test_phase_returns_script_segments_and_metadata(tmp_path: Path):
    sm = _make_session_manager(tmp_path)
    cfg = MagicMock()  # 本 phase は config を実際には使用しない

    result = asyncio.run(execute_external_script_phase(
        verified_script_path=FIXTURE_PATH,
        session_manager=sm,
        config=cfg,
        callbacks=_make_callbacks(),
    ))

    assert isinstance(result, ExternalScriptPhaseResult)
    assert isinstance(result.script, Script)
    assert len(result.segments) >= 2
    assert "title" in result.pre_built_metadata
    assert "thumbnail_title" in result.pre_built_metadata
    assert "description" in result.pre_built_metadata
    assert "hashtags" in result.pre_built_metadata


# ---------------------------------------------------------------------------
# (2) pre_built_metadata の中身が VerifiedScript.metadata と一致する
# ---------------------------------------------------------------------------

def test_phase_pre_built_metadata_matches_verified_script(tmp_path: Path):
    sm = _make_session_manager(tmp_path)
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    md = raw["metadata"]

    result = asyncio.run(execute_external_script_phase(
        verified_script_path=FIXTURE_PATH,
        session_manager=sm,
        config=MagicMock(),
        callbacks=_make_callbacks(),
    ))

    assert result.pre_built_metadata["title"] == md["title"]
    assert result.pre_built_metadata["thumbnail_title"] == md["thumbnail_title"]
    assert result.pre_built_metadata["description"] == md["description"]
    assert list(result.pre_built_metadata["hashtags"]) == list(md["hashtags"])


# ---------------------------------------------------------------------------
# (3) session_manager に RadioScriptArtifact を永続化する
# ---------------------------------------------------------------------------

def test_phase_persists_script_artifact_to_session(tmp_path: Path):
    sm = _make_session_manager(tmp_path)
    asyncio.run(execute_external_script_phase(
        verified_script_path=FIXTURE_PATH,
        session_manager=sm,
        config=MagicMock(),
        callbacks=_make_callbacks(),
    ))

    artifact_path = sm.get_script_artifact_path()
    assert artifact_path.exists()
    # JSON として load 可能 + RadioScriptArtifact に validate できる
    artifact = RadioScriptArtifact.model_validate_json(artifact_path.read_text(encoding="utf-8"))
    assert artifact.session_id == "ext_test"
    assert isinstance(artifact.script, Script)


# ---------------------------------------------------------------------------
# (4) FileNotFoundError 伝播 (silent fallback 禁止)
# ---------------------------------------------------------------------------

def test_phase_raises_filenotfound_for_missing_path(tmp_path: Path):
    sm = _make_session_manager(tmp_path)
    with pytest.raises(FileNotFoundError):
        asyncio.run(execute_external_script_phase(
            verified_script_path=tmp_path / "missing.json",
            session_manager=sm,
            config=MagicMock(),
        ))


# ---------------------------------------------------------------------------
# (5) ValidationError 伝播 (壊れた JSON で silent fallback 禁止)
# ---------------------------------------------------------------------------

def test_phase_raises_validation_error_for_broken_json(tmp_path: Path):
    sm = _make_session_manager(tmp_path)
    broken = tmp_path / "broken.json"
    broken.write_text('{"script": "not an object"}', encoding="utf-8")

    with pytest.raises(ValidationError):
        asyncio.run(execute_external_script_phase(
            verified_script_path=broken,
            session_manager=sm,
            config=MagicMock(),
        ))


# ---------------------------------------------------------------------------
# (6) Phase 1+2 完全 bypass: LLM API は一切呼ばれない
# ---------------------------------------------------------------------------

def test_phase_does_not_call_any_llm_api(tmp_path: Path, monkeypatch):
    """本 phase 内で Gemini / Perplexity / Ollama 等の adapter が呼ばれていないこと。

    モジュールロードのみで callable な経路は無いため、phase 関数のソースに
    'create_script_generator' / 'PerplexityResearcher' / 'execute_planning_phase'
    が含まれないことを構造的に確認する。
    """
    src = (Path(__file__).resolve().parent.parent
           / "services" / "pipeline" / "external_script_phase.py").read_text(encoding="utf-8")
    forbidden_symbols = [
        "create_script_generator",
        "PerplexityResearcher",
        "GeminiClient",
        "execute_planning_phase",
        "execute_research_phase",
        "execute_scripting_phase",
    ]
    for sym in forbidden_symbols:
        assert sym not in src, f"external_script_phase.py に LLM 経路 '{sym}' が混入している"
