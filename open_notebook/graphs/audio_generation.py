"""Audio generation for agentic podcast workflows.

Takes the reviewed transcript from the multi-agent pipeline and
produces TTS audio clips + a combined final MP3 using the same
TTS stack as podcast_creator (esperanto AIFactory + moviepy combine).
"""

import asyncio
import os
from pathlib import Path
from typing import Dict, List

from loguru import logger

from open_notebook.domain.agentic_podcast import TranscriptLine


async def generate_single_clip(
    text: str,
    speaker: str,
    index: int,
    clips_dir: Path,
    tts_provider: str,
    tts_model: str,
    voice_mapping: Dict[str, str],
) -> Path:
    """Generate a single TTS audio clip.

    Args:
        text: Dialogue text to synthesize
        speaker: Speaker name (used to look up voice)
        index: Clip index for filename ordering
        clips_dir: Directory to write clip files
        tts_provider: TTS provider name (openai, elevenlabs, etc.)
        tts_model: TTS model name
        voice_mapping: {speaker_name: voice_id} dict

    Returns:
        Path to the generated .mp3 clip
    """
    from esperanto import AIFactory

    voice_id = voice_mapping.get(speaker)
    if not voice_id:
        # Fallback: use first available voice if speaker name doesn't match exactly
        logger.warning(
            f"No voice mapping for speaker '{speaker}', "
            f"available: {list(voice_mapping.keys())}"
        )
        voice_id = next(iter(voice_mapping.values()))

    filename = f"{index:04d}.mp3"
    clip_path = clips_dir / filename

    tts = AIFactory.create_text_to_speech(tts_provider, tts_model)
    await tts.agenerate_speech(text=text, voice=voice_id, output_file=clip_path)

    logger.debug(f"Generated clip {filename} for {speaker}")
    return clip_path


async def generate_audio_from_transcript(
    transcript: List[TranscriptLine],
    episode_name: str,
    tts_provider: str,
    tts_model: str,
    voice_mapping: Dict[str, str],
    output_base_dir: str = "data/podcasts/episodes",
    batch_size: int | None = None,
) -> Path:
    """Generate full audio from a reviewed transcript.

    Creates individual clips in batches, then combines them into
    a single MP3 file.

    Args:
        transcript: List of TranscriptLine (speaker + dialogue)
        episode_name: Name used for output directory and final file
        tts_provider: TTS provider (openai, elevenlabs, etc.)
        tts_model: TTS model name
        voice_mapping: {speaker_name: voice_id} mapping
        output_base_dir: Base directory for podcast episode output
        batch_size: Number of concurrent TTS requests per batch
                    (default: TTS_BATCH_SIZE env var or 5)

    Returns:
        Path to the final combined MP3 file
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
            tasks.append(
                generate_single_clip(
                    text=line.dialogue,
                    speaker=line.speaker,
                    index=i,
                    clips_dir=clips_dir,
                    tts_provider=tts_provider,
                    tts_model=tts_model,
                    voice_mapping=voice_mapping,
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

    # Combine clips into final MP3 using podcast_creator's combine function
    from podcast_creator import combine_audio_files

    result = await combine_audio_files(
        clips_dir, f"{episode_name}.mp3", audio_dir
    )

    final_path = Path(result["combined_audio_path"])

    if "ERROR" in str(final_path):
        raise RuntimeError(f"Audio combination failed: {final_path}")

    logger.info(f"Final audio saved to: {final_path}")
    return final_path
