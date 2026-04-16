"""Audio generation for agentic podcast workflows.

Takes the reviewed transcript from the multi-agent pipeline and
produces TTS audio clips + a combined final MP3 using pydub for
fast concatenation with natural pauses between speakers.
"""

import asyncio
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger
from pydub import AudioSegment

from open_notebook.domain.agentic_podcast import TranscriptLine

# Silence durations (milliseconds)
SAME_SPEAKER_PAUSE_MS = 200    # brief pause within same speaker
SPEAKER_CHANGE_PAUSE_MS = 500  # longer pause when speaker changes

# TTS retry / fallback settings
TTS_MAX_RETRIES = 2  # initial attempt + 1 retry
TTS_RETRY_DELAY_S = 2.0

# Duration validation targets (seconds)
DURATION_TARGET_RANGE = {
    "short": (150, 420),    # 2.5-7 min
    "medium": (360, 720),   # 6-12 min
    "long": (600, 1080),    # 10-18 min
}
DEFAULT_DURATION_RANGE = (150, 900)  # 2.5-15 min fallback


async def _create_tts(provider: str, model: str):
    """Create a TTS instance via ModelManager (respects DB provider config).

    Tries multiple lookup strategies to find the model in the DB:
    1. Exact model name (e.g. 'openai/gpt-audio-mini')
    2. provider/model combo (e.g. 'openai' + 'gpt-4o-mini-tts' -> 'openai/gpt-4o-mini-tts')
    3. Default TTS model from DB settings

    Falls back to direct AIFactory only if all DB lookups fail.
    """
    from open_notebook.domain.models import ModelManager

    mgr = ModelManager()

    # Try exact name, then provider/model, then default TTS
    candidates = [model]
    if "/" not in model and provider:
        candidates.append(f"{provider}/{model}")
    for candidate in candidates:
        try:
            tts = await mgr.get_model(candidate)
            if tts is not None:
                logger.debug(f"ModelManager resolved TTS '{candidate}' successfully")
                return tts
        except Exception as e:
            logger.debug(f"ModelManager lookup failed for '{candidate}': {e}")

    # Try the system default TTS model
    try:
        tts = await mgr.get_text_to_speech()
        if tts is not None:
            logger.info(
                f"Using system default TTS model (speaker profile model "
                f"'{model}' not found in DB)"
            )
            return tts
    except Exception as e:
        logger.debug(f"Default TTS lookup also failed: {e}")

    # Last resort: direct AIFactory (will likely fail without proper API key)
    logger.warning(
        f"No DB model found for TTS '{model}' — using AIFactory directly "
        f"with provider='{provider}'. This may fail if API keys aren't set."
    )
    from esperanto import AIFactory
    return AIFactory.create_text_to_speech(provider, model)


async def generate_single_clip(
    text: str,
    speaker: str,
    index: int,
    clips_dir: Path,
    tts_provider: str,
    tts_model: str,
    voice_mapping: Dict[str, str],
    fallback_tts_provider: Optional[str] = None,
    fallback_tts_model: Optional[str] = None,
) -> Path:
    """Generate a single TTS audio clip with retry and fallback.

    Attempts TTS generation up to TTS_MAX_RETRIES times with the primary
    provider. If all retries fail and a fallback provider is configured,
    attempts once with the fallback. All fallback usage is logged.

    Args:
        text: Dialogue text to synthesize
        speaker: Speaker name (used to look up voice)
        index: Clip index for filename ordering
        clips_dir: Directory to write clip files
        tts_provider: Primary TTS provider name
        tts_model: Primary TTS model name
        voice_mapping: {speaker_name: voice_id} dict
        fallback_tts_provider: Optional fallback TTS provider
        fallback_tts_model: Optional fallback TTS model

    Returns:
        Path to the generated .mp3 clip

    Raises:
        RuntimeError: If all TTS attempts (including fallback) fail
    """
    voice_id = voice_mapping.get(speaker)
    if not voice_id:
        logger.warning(
            f"No voice mapping for speaker '{speaker}', "
            f"available: {list(voice_mapping.keys())}"
        )
        voice_id = next(iter(voice_mapping.values()))

    filename = f"{index:04d}.mp3"
    clip_path = clips_dir / filename

    # --- Primary provider: attempt + retry ---
    last_error: Optional[Exception] = None
    for attempt in range(1, TTS_MAX_RETRIES + 1):
        try:
            tts = await _create_tts(tts_provider, tts_model)
            await tts.agenerate_speech(text=text, voice=voice_id, output_file=clip_path)
            logger.debug(f"Generated clip {filename} for {speaker} (attempt {attempt})")
            return clip_path
        except Exception as e:
            last_error = e
            logger.warning(
                f"TTS clip {index} attempt {attempt}/{TTS_MAX_RETRIES} failed "
                f"(provider={tts_provider}): {e}"
            )
            if attempt < TTS_MAX_RETRIES:
                await asyncio.sleep(TTS_RETRY_DELAY_S)

    # --- Fallback provider ---
    fb_provider = fallback_tts_provider or os.getenv("FALLBACK_TTS_PROVIDER")
    fb_model = fallback_tts_model or os.getenv("FALLBACK_TTS_MODEL")

    if fb_provider and fb_model:
        logger.warning(
            f"Primary TTS failed for clip {index} after {TTS_MAX_RETRIES} attempts. "
            f"Falling back to {fb_provider}/{fb_model}"
        )
        try:
            tts = await _create_tts(fb_provider, fb_model)
            await tts.agenerate_speech(text=text, voice=voice_id, output_file=clip_path)
            logger.info(
                f"FALLBACK TTS succeeded for clip {index} "
                f"(provider={fb_provider}, model={fb_model}, speaker={speaker})"
            )
            return clip_path
        except Exception as fb_err:
            logger.error(
                f"Fallback TTS also failed for clip {index}: {fb_err}"
            )
            raise RuntimeError(
                f"TTS generation failed for clip {index} with both primary "
                f"({tts_provider}) and fallback ({fb_provider}): "
                f"primary error: {last_error}, fallback error: {fb_err}"
            ) from fb_err
    else:
        raise RuntimeError(
            f"TTS generation failed for clip {index} after {TTS_MAX_RETRIES} "
            f"attempts (provider={tts_provider}). No fallback TTS configured. "
            f"Set FALLBACK_TTS_PROVIDER and FALLBACK_TTS_MODEL env vars to "
            f"enable fallback. Last error: {last_error}"
        )


def _prepare_tts_text(line: TranscriptLine) -> str:
    """Prepare dialogue text for TTS, optionally weaving in pronunciation hints.

    If pronunciation_notes are present, we prepend a silent-friendly hint
    so the TTS engine reads technical terms more naturally.
    Standard TTS APIs ignore SSML, so we embed hints as natural text.
    """
    text = line.dialogue

    # If pronunciation notes exist, try to apply them to the text
    if line.pronunciation_notes and line.pronunciation_notes.strip():
        # pronunciation_notes format: "ViT: vit, rhymes with bit"
        # We don't modify the dialogue — TTS handles most words fine.
        # Just log for awareness.
        logger.debug(
            f"Pronunciation notes for line {line.speaker}: {line.pronunciation_notes}"
        )

    return text


def _combine_clips_with_pauses(
    clip_paths: List[Path],
    transcript: List[TranscriptLine],
    output_path: Path,
) -> Tuple[Path, float, List[Dict]]:
    """Combine audio clips with natural pauses using pydub (fast, no re-encoding).

    Adds a short pause between same-speaker lines and a longer pause
    when the speaker changes, creating a natural conversational rhythm.

    Args:
        clip_paths: Ordered list of MP3 clip file paths
        transcript: Original transcript lines (for speaker info)
        output_path: Where to write the final combined MP3

    Returns:
        Tuple of (path to combined MP3, duration in seconds, line_timings list)
        where line_timings is [{lineIndex, start, end}, ...] with exact seconds.
    """
    if not clip_paths:
        raise ValueError("No clips to combine")

    same_pause = AudioSegment.silent(duration=SAME_SPEAKER_PAUSE_MS)
    change_pause = AudioSegment.silent(duration=SPEAKER_CHANGE_PAUSE_MS)

    logger.info(f"Combining {len(clip_paths)} clips with natural pauses...")

    line_timings: List[Dict] = []
    cursor_ms = 0.0  # running position in milliseconds

    combined = AudioSegment.from_mp3(str(clip_paths[0]))
    clip_dur_ms = len(combined)
    line_timings.append({
        "lineIndex": 0,
        "start": round(cursor_ms / 1000, 3),
        "end": round((cursor_ms + clip_dur_ms) / 1000, 3),
    })
    cursor_ms += clip_dur_ms

    for i in range(1, len(clip_paths)):
        # Pick pause duration based on speaker change
        prev_speaker = transcript[i - 1].speaker if i - 1 < len(transcript) else ""
        curr_speaker = transcript[i].speaker if i < len(transcript) else ""

        if prev_speaker != curr_speaker:
            combined += change_pause
            cursor_ms += SPEAKER_CHANGE_PAUSE_MS
        else:
            combined += same_pause
            cursor_ms += SAME_SPEAKER_PAUSE_MS

        clip = AudioSegment.from_mp3(str(clip_paths[i]))
        clip_dur_ms = len(clip)
        line_timings.append({
            "lineIndex": i,
            "start": round(cursor_ms / 1000, 3),
            "end": round((cursor_ms + clip_dur_ms) / 1000, 3),
        })
        cursor_ms += clip_dur_ms
        combined += clip

    # Export as MP3
    combined.export(str(output_path), format="mp3")
    duration_secs = len(combined) / 1000.0
    logger.info(
        f"Combined audio: {duration_secs:.1f}s ({duration_secs / 60:.1f} min), "
        f"saved to {output_path}"
    )
    return output_path, duration_secs, line_timings


def validate_audio_duration(
    duration_secs: float,
    podcast_length: str = "medium",
) -> Dict[str, any]:
    """Validate audio duration against target range for the podcast length.

    Args:
        duration_secs: Actual audio duration in seconds
        podcast_length: 'short', 'medium', or 'long'

    Returns:
        Dict with 'valid', 'duration_secs', 'duration_minutes',
        'target_range_minutes', and optional 'warning'
    """
    target_range = DURATION_TARGET_RANGE.get(podcast_length, DEFAULT_DURATION_RANGE)
    min_secs, max_secs = target_range
    duration_min = duration_secs / 60.0

    result = {
        "valid": True,
        "duration_secs": round(duration_secs, 1),
        "duration_minutes": round(duration_min, 1),
        "target_range_minutes": (round(min_secs / 60, 1), round(max_secs / 60, 1)),
    }

    if duration_secs < min_secs:
        result["valid"] = False
        result["warning"] = (
            f"Audio duration ({duration_min:.1f} min) is shorter than target "
            f"range ({min_secs / 60:.0f}-{max_secs / 60:.0f} min) for "
            f"'{podcast_length}' podcast"
        )
        logger.warning(result["warning"])
    elif duration_secs > max_secs:
        result["valid"] = False
        result["warning"] = (
            f"Audio duration ({duration_min:.1f} min) exceeds target "
            f"range ({min_secs / 60:.0f}-{max_secs / 60:.0f} min) for "
            f"'{podcast_length}' podcast"
        )
        logger.warning(result["warning"])
    else:
        logger.info(
            f"Audio duration ({duration_min:.1f} min) is within target range "
            f"({min_secs / 60:.0f}-{max_secs / 60:.0f} min) ✓"
        )

    return result


async def generate_audio_from_transcript(
    transcript: List[TranscriptLine],
    episode_name: str,
    tts_provider: str,
    tts_model: str,
    voice_mapping: Dict[str, str],
    output_base_dir: str = "data/podcasts/episodes",
    batch_size: int | None = None,
    fallback_tts_provider: Optional[str] = None,
    fallback_tts_model: Optional[str] = None,
    podcast_length: str = "medium",
) -> Tuple[Path, Dict]:
    """Generate full audio from a reviewed transcript.

    Creates individual clips in batches with retry/fallback, then combines
    them into a single MP3 file with natural pauses between speakers.
    Validates final duration against the target range.

    Args:
        transcript: List of TranscriptLine (speaker + dialogue)
        episode_name: Name used for output directory and final file
        tts_provider: Primary TTS provider
        tts_model: Primary TTS model name
        voice_mapping: {speaker_name: voice_id} mapping
        output_base_dir: Base directory for podcast episode output
        batch_size: Concurrent TTS requests per batch (default: env or 5)
        fallback_tts_provider: Optional fallback TTS provider
        fallback_tts_model: Optional fallback TTS model
        podcast_length: 'short', 'medium', or 'long' for duration validation

    Returns:
        Tuple of (path to final MP3, duration_info dict)
    """
    if batch_size is None:
        batch_size = int(os.getenv("TTS_BATCH_SIZE", "5"))

    total_clips = len(transcript)
    if total_clips == 0:
        raise ValueError("Cannot generate audio from empty transcript")

    # Create output directories
    output_dir = Path(output_base_dir) / episode_name
    clips_dir = output_dir / "clips"
    audio_dir = output_dir / "audio"
    clips_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        f"Generating {total_clips} audio clips for '{episode_name}' "
        f"(batch_size={batch_size}, provider={tts_provider}, model={tts_model})"
    )

    # Process in sequential batches to respect API rate limits
    all_clip_paths: List[Path] = []
    total_batches = (total_clips + batch_size - 1) // batch_size

    for batch_start in range(0, total_clips, batch_size):
        batch_end = min(batch_start + batch_size, total_clips)
        batch_num = batch_start // batch_size + 1

        logger.info(
            f"Processing TTS batch {batch_num}/{total_batches} "
            f"(clips {batch_start}-{batch_end - 1})"
        )

        tasks = []
        for i in range(batch_start, batch_end):
            line = transcript[i]
            tts_text = _prepare_tts_text(line)
            tasks.append(
                generate_single_clip(
                    text=tts_text,
                    speaker=line.speaker,
                    index=i,
                    clips_dir=clips_dir,
                    tts_provider=tts_provider,
                    tts_model=tts_model,
                    voice_mapping=voice_mapping,
                    fallback_tts_provider=fallback_tts_provider,
                    fallback_tts_model=fallback_tts_model,
                )
            )

        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in batch_results:
            if isinstance(result, Exception):
                logger.error(f"TTS clip generation failed: {result}")
                raise result
            all_clip_paths.append(result)

        # Small delay between batches for API rate limiting
        if batch_end < total_clips:
            await asyncio.sleep(1)

    logger.info(f"Generated all {len(all_clip_paths)} clips, combining audio...")

    # Combine clips with natural pauses using pydub (fast path)
    final_filename = f"{episode_name}.mp3"
    final_path = audio_dir / final_filename

    final_path, duration_secs, line_timings = _combine_clips_with_pauses(
        all_clip_paths, transcript, final_path
    )

    # Validate duration against target range
    duration_info = validate_audio_duration(duration_secs, podcast_length)
    duration_info["line_timings"] = line_timings

    logger.info(f"Final audio saved to: {final_path}")
    return final_path, duration_info
