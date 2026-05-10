"""Regression tests for jingle silent-after-3rd bug (index-based segment correspondence).

These tests verify that duplicate segment_ids (e.g., multiple "deep_dive" from Gemini)
no longer cause jingles to be placed at the same timestamp.
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.interfaces import SegmentTiming, SynthesisResult
from core.models.curation import ScriptSegment
from services.audio_synthesis.voicevox_segment_timing import calculate_segment_timings


def _make_segment(segment_id: str, num_turns: int = 2, segment_type: str = "deep_dive") -> ScriptSegment:
    """Helper: create a ScriptSegment with dummy turns."""
    turns = [
        {"speaker": "A", "text": f"dummy {i}", "section": segment_id if i == 0 else None}
        for i in range(num_turns)
    ]
    return ScriptSegment(
        segment_id=segment_id,
        segment_type=segment_type,
        topic_title=None,
        turns=turns,
        context_summary="",
    )


def _make_phrase_data(num_phrases: int, phrase_duration_ms: int = 1000, pause_ms: int = 250) -> list:
    """Helper: build phrase_data with sequential timestamps."""
    phrase_data = []
    current_ms = 0
    for i in range(num_phrases):
        phrase_data.append((
            MagicMock(),  # audio_segment
            current_ms,
            current_ms + phrase_duration_ms,
            f"text {i}",
            "A",
        ))
        current_ms += phrase_duration_ms + pause_ms
    return phrase_data


class TestSegmentPausesList:
    """Tests that segment_pauses is now a list (not dict) and preserves per-index info."""
    
    def test_calculate_segment_timings_uses_index_not_id(self):
        """Duplicate segment_ids should each get their corresponding jingle info by index."""
        from core.models import Script
        
        segments = [
            _make_segment("intro", num_turns=2, segment_type="intro"),
            _make_segment("deep_dive", num_turns=2),  # duplicate name
            _make_segment("deep_dive", num_turns=2),  # duplicate name
            _make_segment("conclusion", num_turns=2, segment_type="conclusion"),
        ]
        phrase_data = _make_phrase_data(num_phrases=8)
        
        # Index-based pauses: each segment has distinct jingle info
        segment_pauses = [
            (3.5, Path("jingle_A.wav"), 3.0),  # segment[0] after intro
            (3.5, Path("jingle_B.wav"), 3.0),  # segment[1] after 1st deep_dive
            (3.5, Path("jingle_C.wav"), 3.0),  # segment[2] after 2nd deep_dive
            (0.0, None, None),                  # segment[3] last, no jingle
        ]
        
        script = MagicMock(spec=Script)
        timings = calculate_segment_timings(script, segments, phrase_data, segment_pauses)
        
        # Invariant: len(timings) == len(segments)
        assert len(timings) == len(segments)
        
        # Each timing should have its OWN jingle (not all pointing to the same one)
        assert timings[0].jingle_path == Path("jingle_A.wav")
        assert timings[1].jingle_path == Path("jingle_B.wav")
        assert timings[2].jingle_path == Path("jingle_C.wav")
        assert timings[3].jingle_path is None
        
        # start/end_sec must be DIFFERENT for duplicate-id segments
        assert timings[1].start_sec != timings[2].start_sec, (
            "2nd and 3rd deep_dive segments must have different timestamps"
        )
        assert timings[1].end_sec != timings[2].end_sec

    def test_empty_segment_preserves_invariant(self):
        """Empty segments should get dummy timings to preserve len invariant."""
        from core.models import Script
        
        segments = [
            _make_segment("intro", num_turns=2),
            _make_segment("empty", num_turns=0),  # no turns
            _make_segment("conclusion", num_turns=2, segment_type="conclusion"),
        ]
        phrase_data = _make_phrase_data(num_phrases=4)
        segment_pauses = [(0.0, None, None)] * 3
        
        script = MagicMock(spec=Script)
        timings = calculate_segment_timings(script, segments, phrase_data, segment_pauses)
        
        assert len(timings) == len(segments)
        assert timings[1].duration_sec == 0.0  # dummy entry for empty segment

    def test_empty_last_segment_includes_post_roll(self):
        """Regression for Issue 1: when the last segment is empty and takes the
        dummy branch, its ``end_sec`` must still account for the 5s post-roll
        silence that is always appended to ``combined_audio``.
        """
        from core.models import Script
        
        segments = [
            _make_segment("intro", num_turns=2, segment_type="intro"),
            _make_segment("deep_dive", num_turns=2),
            _make_segment("empty_last", num_turns=0, segment_type="conclusion"),  # empty last
        ]
        phrase_data = _make_phrase_data(num_phrases=4)
        segment_pauses = [(0.0, None, None)] * 3
        
        script = MagicMock(spec=Script)
        timings = calculate_segment_timings(script, segments, phrase_data, segment_pauses)
        
        assert len(timings) == len(segments)
        last = timings[-1]
        prev = timings[-2]
        # Post-roll (5s) must push the last segment's end_sec beyond the previous end
        assert last.end_sec == pytest.approx(prev.end_sec + 5.0), (
            f"Empty last segment must include post-roll: last.end_sec={last.end_sec}, "
            f"prev.end_sec={prev.end_sec}"
        )
        assert last.duration_sec == pytest.approx(5.0)

    def test_phrase_exhaustion_on_last_segment_includes_post_roll(self):
        """Regression for Issue 1: when phrase_data is exhausted before reaching
        the last segment, that last segment still takes the dummy branch but
        must include the post-roll offset.
        """
        from core.models import Script
        
        segments = [
            _make_segment("intro", num_turns=4, segment_type="intro"),  # consumes all phrases
            _make_segment("conclusion", num_turns=2, segment_type="conclusion"),
        ]
        phrase_data = _make_phrase_data(num_phrases=4)  # only enough for first segment
        segment_pauses = [(0.0, None, None)] * 2
        
        script = MagicMock(spec=Script)
        timings = calculate_segment_timings(script, segments, phrase_data, segment_pauses)
        
        assert len(timings) == 2
        last = timings[-1]
        # Dummy entry still receives post-roll (+5s) so video duration matches audio.
        assert last.duration_sec == pytest.approx(5.0)


# Step 4 v2 (2026-05-10): TestUniqueIdExtraction は GeminiClient._extract_segments_from_script
# を直接呼ぶ Gemini 専用テストだったため、GeminiClient 物理削除に伴い削除。
# segment_id 一意性は外部台本モード経路 (RadioDirectorScriptLoader.build_script_segments)
# が担保するためそちらの test_radio_director_loader.py で検証している。


class TestTimelineCalculatorIndexBased:
    """Tests that TimelineCalculator uses index (not id) for timing lookup."""
    
    def test_duplicate_ids_use_distinct_timings(self, mock_app_config):
        """Even with duplicate segment_ids, each segment should use its OWN timing by index."""
        import anyio
        from services.video_rendering.timeline_calculator import TimelineCalculator
        
        segments = [
            _make_segment("intro", num_turns=1, segment_type="intro"),
            _make_segment("deep_dive", num_turns=1),
            _make_segment("deep_dive", num_turns=1),  # duplicate id
            _make_segment("conclusion", num_turns=1, segment_type="conclusion"),
        ]
        
        # Distinct timings per index
        timings = [
            SegmentTiming("intro", "intro", None, 0.0, 10.0, 10.0, Path("a.wav"), 3.0),
            SegmentTiming("deep_dive", "deep_dive", None, 13.5, 23.5, 10.0, Path("b.wav"), 3.0),
            SegmentTiming("deep_dive", "deep_dive", None, 27.0, 37.0, 10.0, Path("c.wav"), 3.0),
            SegmentTiming("conclusion", "conclusion", None, 40.5, 50.0, 9.5, None, None),
        ]
        
        synthesis_result = SynthesisResult(
            audio_path=Path("audio.wav"),
            subtitle_path=Path("subs.ass"),
            total_duration_sec=50.0,
            segment_timings=timings,
        )
        
        # Mock providers
        image_provider = MagicMock()
        
        async def mock_get_image(seg):
            return Path(f"bg_{seg.segment_id}.png")
        image_provider.get_image_for_segment = mock_get_image
        
        jingle_provider = MagicMock()
        
        calc = TimelineCalculator(mock_app_config)
        
        async def run():
            return await calc.calculate_timeline(
                segments=segments,
                synthesis_result=synthesis_result,
                image_provider=image_provider,
                jingle_provider=jingle_provider,
                bgm_path=Path("bgm.wav"),
            )
        
        timeline = anyio.run(run)
        
        # All 4 entries produced
        assert len(timeline.segments) == 4
        
        # Each uses its own timing (distinct jingle_start_sec for the two "deep_dive")
        dd1 = timeline.segments[1]
        dd2 = timeline.segments[2]
        assert dd1.jingle_start_sec != dd2.jingle_start_sec, (
            "Jingles for duplicate-id segments must be placed at different timestamps"
        )
        assert dd1.jingle_path == Path("b.wav")
        assert dd2.jingle_path == Path("c.wav")
