# compliance agent - final safety and quality gate before production

from typing import Any, Dict, List, Optional

from ai_prompter import Prompter
from langchain_core.output_parsers.pydantic import PydanticOutputParser
from loguru import logger
from pydantic import BaseModel, Field

from open_notebook.domain.agentic_podcast import (
    ComplianceOutput,
    TranscriptLine,
)
from open_notebook.graphs.utils import provision_langchain_model
from open_notebook.utils import clean_thinking_content


class ComplianceCheck(BaseModel):
    passed: bool = Field(description="Whether this check passed")
    notes: str = Field(description="Brief assessment for this check")


class ComplianceFlag(BaseModel):
    severity: str = Field(description="critical, warning, or info")
    category: str = Field(description="Category of the flag")
    description: str = Field(description="Clear description of the issue")
    location: str = Field(description="Where in the transcript the issue occurs")
    recommendation: str = Field(description="How to address it")


class ComplianceResult(BaseModel):
    approved: bool = Field(description="Whether the transcript is approved")
    overall_risk_level: str = Field(description="low, medium, or high")
    checks: Dict[str, ComplianceCheck] = Field(
        description="Individual compliance checks"
    )
    flags: List[ComplianceFlag] = Field(
        default_factory=list, description="List of compliance flags"
    )
    summary: str = Field(description="Overall compliance assessment")


async def compliance_agent(
    transcript: List[TranscriptLine],
    content: str,
    briefing: str,
    speakers: List[Dict[str, Any]],
    reviewer_summary: Optional[str] = None,
    model_name: Optional[str] = None,
) -> ComplianceOutput:
    """performs final safety and quality gate check on a transcript"""
    logger.info(
        f"compliance starting check on {len(transcript)} transcript lines"
    )

    try:
        prompt_data: Dict[str, Any] = {
            "briefing": briefing,
            "content": content,
            "speakers": speakers,
            "transcript": [t.model_dump() for t in transcript],
            "reviewer_summary": reviewer_summary,
        }

        parser = PydanticOutputParser(pydantic_object=ComplianceResult)
        system_prompt = Prompter(
            prompt_template="agents/compliance", parser=parser
        ).render(data=prompt_data)

        model = await provision_langchain_model(
            system_prompt,
            model_name,
            "tools",
            max_tokens=4000,
            structured={"type": "json"},
        )

        logger.debug("calling ai model for compliance check")
        ai_message = await model.ainvoke(system_prompt)

        content_text = (
            ai_message.content
            if isinstance(ai_message.content, str)
            else str(ai_message.content)
        )
        cleaned = clean_thinking_content(content_text)
        result = parser.parse(cleaned)

        compliance_output = ComplianceOutput(
            approved=result.approved,
            overall_risk_level=result.overall_risk_level,
            checks={k: v.model_dump() for k, v in result.checks.items()},
            flags=[f.model_dump() for f in result.flags],
            summary=result.summary,
        )

        logger.info(
            f"compliance done: approved={result.approved}, "
            f"risk={result.overall_risk_level}, "
            f"flags={len(result.flags)}"
        )
        return compliance_output

    except Exception as e:
        logger.error(f"compliance check failed: {e}")
        logger.exception(e)
        raise
