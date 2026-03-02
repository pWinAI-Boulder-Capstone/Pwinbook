# writer agent - generates natural dialogue for podcast segments

import asyncio
from typing import Any, Dict, List, Optional

from ai_prompter import Prompter
from langchain_core.output_parsers.pydantic import PydanticOutputParser
from loguru import logger
from pydantic import BaseModel, Field

from open_notebook.domain.agentic_podcast import (
    OutlineSegment,
    TranscriptLine,
    WriterOutput,
)
from open_notebook.graphs.utils import provision_langchain_model
from open_notebook.utils import clean_thinking_content


class SegmentTranscript(BaseModel):
    transcript: List[TranscriptLine] = Field(
        description="List of dialogue lines with speaker and dialogue"
    )


async def writer_agent(
    segment: OutlineSegment,
    segment_index: int,
    content: str,
    briefing: str,
    speakers: List[Dict[str, Any]],
    outline_segments: List[OutlineSegment],
    previous_segments: Optional[List[WriterOutput]] = None,
    model_name: Optional[str] = None,
    min_turns: int = 10,
    max_turns: int = 30,
    target_words_per_turn: Optional[int] = None,
    target_duration_minutes: Optional[int] = None,
    num_segments: int = 5,
) -> WriterOutput:
    """generates natural conversation for a segment, keeping speaker personalities consistent"""
    logger.info(f"writer starting segment {segment_index}: '{segment.name}'")

    try:
        # figure out how many turns based on segment size, capped by max_turns
        if segment.size == "short":
            target_turns = min(max(min_turns, 8), 15, max_turns)
        elif segment.size == "medium":
            target_turns = min(max(min_turns, 15), 25, max_turns)
        else:
            target_turns = min(max(min_turns, 20), max_turns)

        # Calculate word budget for this segment
        # TTS generates ~150 words/minute, so total_words ≈ duration_min × 150
        words_per_turn = target_words_per_turn or 40
        segment_word_budget = target_turns * words_per_turn

        if target_duration_minutes and num_segments > 0:
            # Distribute total word budget evenly across segments
            total_word_budget = target_duration_minutes * 150
            segment_word_budget = total_word_budget // num_segments
            # Adjust target_turns to fit the word budget
            target_turns = max(4, segment_word_budget // words_per_turn)

        # grab context from previous segments if we have them
        previous_transcript_text = None
        if previous_segments and len(previous_segments) > 0:
            recent_segments = previous_segments[-2:]  # last 1-2 for context
            prev_lines: List[str] = []
            for prev_seg in recent_segments:
                prev_lines.append(f"\n[Segment: {prev_seg.segment_name}]")
                for line in prev_seg.transcript:
                    prev_lines.append(f"{line.speaker}: {line.dialogue}")
            previous_transcript_text = "\n".join(prev_lines)
        prompt_data: Dict[str, Any] = {
            "segment": segment.model_dump(),
            "segment_index": segment_index,
            "segment_size": segment.size,
            "target_turns": target_turns,
            "words_per_turn": words_per_turn,
            "segment_word_budget": segment_word_budget,
            "target_duration_minutes": target_duration_minutes,
            "briefing": briefing,
            "content": content,
            "speakers": speakers,
            "speaker_names": [s.get("name") for s in speakers],
            "full_outline": [s.model_dump() for s in outline_segments],
            "previous_transcript": previous_transcript_text,
            "is_first_segment": segment_index == 0,
            "is_last_segment": segment_index == len(outline_segments) - 1,
        }

        logger.info(
            f"writer segment {segment_index}: target_turns={target_turns}, "
            f"words_per_turn={words_per_turn}, word_budget={segment_word_budget}"
        )

        parser = PydanticOutputParser(pydantic_object=SegmentTranscript)
        system_prompt = Prompter(prompt_template="agents/writer", parser=parser).render(
            data=prompt_data
        )

        model = await provision_langchain_model(
            system_prompt,
            model_name,
            "tools",
            max_tokens=4000,
            structured={"type": "json"},
        )

        logger.info(f"calling ai model for segment {segment_index} transcript")

        last_error = None
        for attempt in range(1, 4):
            try:
                # On retry, append a stronger instruction to skip thinking
                invoke_prompt = system_prompt
                if attempt > 1:
                    invoke_prompt = (
                        system_prompt
                        + "\n\nIMPORTANT: Output ONLY the JSON object. "
                        "Do NOT include any reasoning, thinking, or explanation. "
                        "Start your response with {\"transcript\": ["
                    )

                ai_message = await model.ainvoke(invoke_prompt)

                content_text = (
                    ai_message.content
                    if isinstance(ai_message.content, str)
                    else str(ai_message.content)
                )

                # Log raw content info at INFO level so it's always visible
                raw_len = len(content_text) if content_text else 0
                logger.info(
                    f"Writer segment {segment_index} attempt {attempt}: "
                    f"raw response length={raw_len}"
                )
                if raw_len > 0 and raw_len < 300:
                    logger.info(f"Writer segment {segment_index} raw content: {content_text!r}")
                elif raw_len > 0:
                    logger.info(
                        f"Writer segment {segment_index} raw preview: "
                        f"{content_text[:150]!r}...{content_text[-100:]!r}"
                    )

                cleaned = clean_thinking_content(content_text)

                if not cleaned or not cleaned.strip():
                    # Check if model spent all tokens on thinking
                    if content_text and "<think>" in content_text.lower():
                        logger.warning(
                            f"Writer segment {segment_index}: model used all tokens on "
                            f"<think> reasoning ({raw_len} chars), no JSON output produced"
                        )
                    raise ValueError("Model returned empty content")

                transcript_data = parser.parse(cleaned)
                break
            except Exception as parse_err:
                last_error = parse_err
                logger.warning(f"Writer segment {segment_index} attempt {attempt}/3 failed: {parse_err}")
                if attempt < 3:
                    await asyncio.sleep(2 * attempt)
        else:
            raise RuntimeError(f"Writer failed after 3 attempts: {last_error}")
        writer_output = WriterOutput(
            segment_index=segment_index,
            segment_name=segment.name,
            transcript=transcript_data.transcript,
            metadata={
                "segment_size": segment.size,
                "num_turns": len(transcript_data.transcript),
            },
        )

        logger.info(f"writer done segment {segment_index}: {len(writer_output.transcript)} turns")
        return writer_output

    except Exception as e:
        logger.error(f"writer failed for segment {segment_index}: {e}")
        logger.exception(e)
        raise
