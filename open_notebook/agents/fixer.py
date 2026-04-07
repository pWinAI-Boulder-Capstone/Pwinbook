# fixer agent - applies targeted corrections to a transcript based on reviewer feedback

import asyncio
from typing import Any, Dict, List, Optional

from ai_prompter import Prompter
from langchain_core.output_parsers.pydantic import PydanticOutputParser
from loguru import logger
from pydantic import BaseModel, Field

from open_notebook.domain.agentic_podcast import (
    FixerOutput,
    TranscriptLine,
)
from open_notebook.graphs.utils import provision_langchain_model
from open_notebook.utils import clean_thinking_content


class FixerResult(BaseModel):
    """internal model for parsing the fixer LLM output"""

    transcript: List[TranscriptLine] = Field(
        description="The full corrected transcript"
    )
    fix_summary: str = Field(
        description="Brief description of what was changed and why"
    )


async def fixer_agent(
    transcript: List[TranscriptLine],
    content: str,
    briefing: str,
    speakers: List[Dict[str, Any]],
    overall_score: float,
    scores: Dict[str, float],
    issues: List[Dict[str, Any]],
    reviewer_summary: str,
    revision_round: int = 1,
    model_name: Optional[str] = None,
) -> FixerOutput:
    """applies targeted corrections to a transcript based on reviewer feedback

    Args:
        transcript: The current transcript lines to fix
        content: Source content for fact-checking corrections
        briefing: Episode briefing
        speakers: Speaker profiles
        overall_score: Reviewer's overall score
        scores: Per-category scores from reviewer
        issues: List of issues identified by reviewer
        reviewer_summary: Reviewer's summary assessment
        revision_round: Which revision round this is (1-based)
        model_name: Optional model override

    Returns:
        FixerOutput with corrected transcript and fix summary
    """
    logger.info(
        f"fixer starting revision round {revision_round}: "
        f"{len(issues)} issues to address, score={overall_score}"
    )

    try:
        prompt_data: Dict[str, Any] = {
            "briefing": briefing,
            "content": content,
            "speakers": speakers,
            "speaker_names": [s.get("name") for s in speakers],
            "transcript": [t.model_dump() for t in transcript],
            "overall_score": overall_score,
            "scores": scores,
            "issues": issues,
            "reviewer_summary": reviewer_summary,
            "revision_round": revision_round,
        }

        parser = PydanticOutputParser(pydantic_object=FixerResult)
        system_prompt = Prompter(
            prompt_template="agents/fixer", parser=parser
        ).render(data=prompt_data)

        model = await provision_langchain_model(
            system_prompt,
            model_name,
            "tools",
            max_tokens=8192,
            structured={"type": "json"},
        )

        logger.debug(f"calling ai model for transcript fix (round {revision_round})")

        last_error = None
        for attempt in range(1, 4):
            try:
                invoke_prompt = system_prompt
                if attempt > 1:
                    invoke_prompt = (
                        system_prompt
                        + "\n\nIMPORTANT: Output ONLY the JSON object. "
                        "Do NOT include any reasoning, thinking, or explanation. "
                        'Start your response with {"transcript": ['
                    )

                ai_message = await model.ainvoke(invoke_prompt)

                content_text = (
                    ai_message.content
                    if isinstance(ai_message.content, str)
                    else str(ai_message.content)
                )
                cleaned = clean_thinking_content(content_text)

                if not cleaned or not cleaned.strip():
                    raise ValueError("Model returned empty content")

                result = parser.parse(cleaned)
                break
            except Exception as parse_err:
                last_error = parse_err
                logger.warning(
                    f"Fixer attempt {attempt}/3 (round {revision_round}) failed: {parse_err}"
                )
                if attempt < 3:
                    await asyncio.sleep(2 * attempt)
        else:
            raise RuntimeError(
                f"Fixer failed after 3 attempts (round {revision_round}): {last_error}"
            )

        fixer_output = FixerOutput(
            revised_transcript=result.transcript,
            fix_summary=result.fix_summary,
            revision_round=revision_round,
        )

        logger.info(
            f"fixer done (round {revision_round}): "
            f"{len(result.transcript)} lines, summary={result.fix_summary[:100]}"
        )
        return fixer_output

    except Exception as e:
        logger.error(f"fixer failed (round {revision_round}): {e}")
        logger.exception(e)
        raise
