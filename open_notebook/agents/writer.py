# writer agent - generates natural dialogue for podcast segments

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
) -> WriterOutput:
    """generates natural conversation for a segment, keeping speaker personalities consistent"""
    logger.info(f"writer starting segment {segment_index}: '{segment.name}'")

    try:
        # figure out how many turns based on segment size
        if segment.size == "short":
            target_turns = min(max(min_turns, 8), 15)
        elif segment.size == "medium":
            target_turns = min(max(min_turns, 15), 25)
        else:
            target_turns = min(max(min_turns, 20), max_turns)

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
            "briefing": briefing,
            "content": content,
            "speakers": speakers,
            "speaker_names": [s.get("name") for s in speakers],
            "full_outline": [s.model_dump() for s in outline_segments],
            "previous_transcript": previous_transcript_text,
            "is_first_segment": segment_index == 0,
            "is_last_segment": segment_index == len(outline_segments) - 1,
        }

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

        logger.debug(f"calling ai model for segment {segment_index} transcript")
        ai_message = await model.ainvoke(system_prompt)

        content_text = (
            ai_message.content
            if isinstance(ai_message.content, str)
            else str(ai_message.content)
        )
        cleaned = clean_thinking_content(content_text)
        transcript_data = parser.parse(cleaned)
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
