# reviewer agent - evaluates transcript quality and produces a revised version

from typing import Any, Dict, List, Optional

from ai_prompter import Prompter
from langchain_core.output_parsers.pydantic import PydanticOutputParser
from loguru import logger
from pydantic import BaseModel, Field

from open_notebook.domain.agentic_podcast import (
    OutlineSegment,
    ReviewerOutput,
    TranscriptLine,
)
from open_notebook.graphs.utils import provision_langchain_model
from open_notebook.utils import clean_thinking_content


class ReviewIssue(BaseModel):
    severity: str = Field(description="high, medium, or low")
    category: str = Field(description="Category of the issue")
    description: str = Field(description="Clear description of the issue")
    location: str = Field(description="Where in the transcript the issue occurs")
    suggestion: str = Field(description="How to fix the issue")


class ReviewResult(BaseModel):
    overall_score: float = Field(description="Overall quality score 0-10")
    scores: Dict[str, float] = Field(
        description="Individual category scores"
    )
    issues: List[ReviewIssue] = Field(
        default_factory=list, description="List of issues found"
    )
    summary: str = Field(description="Brief overall assessment")
    revised_transcript: List[TranscriptLine] = Field(
        description="Revised and improved transcript"
    )


async def reviewer_agent(
    transcript: List[TranscriptLine],
    content: str,
    briefing: str,
    speakers: List[Dict[str, Any]],
    outline_segments: List[OutlineSegment],
    model_name: Optional[str] = None,
) -> ReviewerOutput:
    """evaluates transcript quality and produces a revised, polished version"""
    logger.info(
        f"reviewer starting evaluation of {len(transcript)} transcript lines"
    )

    try:
        prompt_data: Dict[str, Any] = {
            "briefing": briefing,
            "content": content,
            "speakers": speakers,
            "speaker_names": [s.get("name") for s in speakers],
            "outline_segments": [s.model_dump() for s in outline_segments],
            "transcript": [t.model_dump() for t in transcript],
        }

        parser = PydanticOutputParser(pydantic_object=ReviewResult)
        system_prompt = Prompter(
            prompt_template="agents/reviewer", parser=parser
        ).render(data=prompt_data)

        model = await provision_langchain_model(
            system_prompt,
            model_name,
            "tools",
            max_tokens=8000,
            structured={"type": "json"},
        )

        logger.debug("calling ai model for transcript review")
        ai_message = await model.ainvoke(system_prompt)

        content_text = (
            ai_message.content
            if isinstance(ai_message.content, str)
            else str(ai_message.content)
        )
        cleaned = clean_thinking_content(content_text)
        review = parser.parse(cleaned)

        reviewer_output = ReviewerOutput(
            overall_score=review.overall_score,
            scores=review.scores,
            issues=[i.model_dump() for i in review.issues],
            summary=review.summary,
            revised_transcript=review.revised_transcript,
        )

        logger.info(
            f"reviewer done: score={review.overall_score}, "
            f"issues={len(review.issues)}, "
            f"revised_turns={len(review.revised_transcript)}"
        )
        return reviewer_output

    except Exception as e:
        logger.error(f"reviewer failed: {e}")
        logger.exception(e)
        raise
