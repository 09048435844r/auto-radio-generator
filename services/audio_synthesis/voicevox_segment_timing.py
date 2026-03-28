"""Segment timing calculation utilities for VoicevoxClient

Calculates segment-level timing information from phrase data and script segments.
"""
from typing import Optional

from core.interfaces import SegmentTiming
from core.models import Script


def calculate_segment_timings(
    script: Script,
    segments: Optional[list],
    phrase_data: list
) -> list[SegmentTiming]:
    """Calculate segment-level timing information
    
    Maps phrase-level timing data to segment boundaries based on
    the number of turns in each segment.
    
    Args:
        script: Script object
        segments: List of ScriptSegment objects
        phrase_data: List of (audio_segment, start_ms, end_ms, text, speaker) tuples
    
    Returns:
        List of SegmentTiming objects
    """
    if not segments or not phrase_data:
        return []
    
    segment_timings = []
    phrase_index = 0
    pre_roll_offset_ms = 2000  # Pre-roll silence added to audio
    
    for segment in segments:
        # Count turns in this segment
        num_turns = len(segment.turns)
        
        if num_turns == 0:
            continue
        
        # Calculate start time from first phrase in segment
        if phrase_index < len(phrase_data):
            start_ms = phrase_data[phrase_index][1]  # start_time from phrase_data
            start_sec = (start_ms + pre_roll_offset_ms) / 1000.0
        else:
            # No more phrases, skip this segment
            continue
        
        # Calculate end time from last phrase in segment
        end_phrase_index = min(phrase_index + num_turns - 1, len(phrase_data) - 1)
        end_ms = phrase_data[end_phrase_index][2]  # end_time from phrase_data
        end_sec = (end_ms + pre_roll_offset_ms) / 1000.0
        
        duration_sec = end_sec - start_sec
        
        segment_timings.append(SegmentTiming(
            segment_id=segment.segment_id,
            segment_type=segment.segment_type,
            topic_title=segment.topic_title,
            start_sec=start_sec,
            end_sec=end_sec,
            duration_sec=duration_sec,
        ))
        
        # Move to next segment's phrases
        phrase_index += num_turns
    
    return segment_timings
