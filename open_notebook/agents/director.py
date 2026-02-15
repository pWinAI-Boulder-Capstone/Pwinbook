# director agent - analyzes content and creates strategic podcast outline

from typing import Any, Dict

from ai_prompter import Prompter
from langchain_core.output_parsers.pydantic import PydanticOutputParser
from loguru import logger
from pydantic import BaseModel, Field

from open_notebook.domain.agentic_podcast import DirectorOutput, OutlineSegment
from open_notebook.graphs.utils import provision_langchain_model
from open_notebook.utils import clean_thinking_content


class PodcastOutline(BaseModel):
    reasoning: str = Field(
        description="Strategic reasoning for the outline structure"
    )
    segments: list[OutlineSegment] = Field(
        description="List of podcast segments with names and descriptions"
    )


async def director_agent(
    content: str,
    briefing: str,
    speakers: list[Dict[str, Any]],
    num_segments: int = 5,
    model_name: str | None = None,
) -> DirectorOutput:
    """analyzes content and creates strategic outline with segments that work well together"""
    logger.info(f"director starting outline generation for {num_segments} segments")

    try:
        prompt_data: Dict[str, Any] = {
            "briefing": briefing,
            "context": content,
            "speakers": speakers,
            "num_segments": num_segments,
        }

        parser = PydanticOutputParser(pydantic_object=PodcastOutline)
        system_prompt = Prompter(
            prompt_template="agents/director", parser=parser
        ).render(data=prompt_data)

        model = await provision_langchain_model(
            system_prompt,
            model_name,
            "tools",
            max_tokens=3000,
            structured={"type": "json"},
        )

        logger.debug("calling ai model for outline")
        ai_message = await model.ainvoke(system_prompt)

        content_text = (
            ai_message.content
            if isinstance(ai_message.content, str)
            else str(ai_message.content)
        )
        cleaned = clean_thinking_content(content_text)
        outline = parser.parse(cleaned)

        director_output = DirectorOutput(
            reasoning=outline.reasoning,
            segments=outline.segments,
            num_segments=len(outline.segments),
        )

        logger.info(f"director done: generated {len(director_output.segments)} segments")
        return director_output

    except Exception as e:
        logger.error(f"director failed: {e}")
        logger.exception(e)
        raise
