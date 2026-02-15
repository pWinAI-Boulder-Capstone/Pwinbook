# domain models for agentic podcast workflow (phase 1: director + writer)

from typing import Any, ClassVar, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from open_notebook.domain.base import ObjectModel


# workflow stages and statuses
WorkflowStage = Literal["director", "writer", "completed", "failed"]
WorkflowStatus = Literal["pending", "in_progress", "completed", "failed"]
SegmentSize = Literal["short", "medium", "long"]


class OutlineSegment(BaseModel):
    name: str = Field(..., description="Name of the segment")
    description: str = Field(..., description="Detailed description of segment content")
    size: SegmentSize = Field(
        default="medium", description="Duration/size of the segment"
    )


class DirectorOutput(BaseModel):
    reasoning: str = Field(
        ..., description="Director's strategic reasoning for the outline"
    )
    segments: List[OutlineSegment] = Field(
        ..., description="List of podcast segments"
    )
    num_segments: int = Field(..., description="Total number of segments")

    @property
    def outline_dict(self) -> Dict[str, Any]:
        """for compatibility with existing code"""
        return {"segments": [s.model_dump() for s in self.segments]}


class TranscriptLine(BaseModel):
    speaker: str = Field(..., description="Name of the speaker")
    dialogue: str = Field(..., description="What the speaker says")


class WriterOutput(BaseModel):
    segment_index: int = Field(..., description="Index of the segment (0-based)")
    segment_name: str = Field(..., description="Name of the segment")
    transcript: List[TranscriptLine] = Field(
        ..., description="Dialogue lines for this segment"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional metadata (timing, tone notes, etc.)"
    )


class AgenticPodcastWorkflow(ObjectModel):
    """tracks multi-agent workflow state through director and writer stages"""

    table_name: ClassVar[str] = "agentic_podcast_workflow"

    name: str = Field(..., description="Name of the podcast episode")
    content: Optional[str] = Field(
        default=None, description="Source content for the podcast"
    )
    notebook_id: Optional[str] = Field(
        default=None, description="ID of notebook to extract content from"
    )

    episode_profile_name: str = Field(
        ..., description="Name of the episode profile to use"
    )
    speaker_profile_name: str = Field(
        ..., description="Name of the speaker profile to use"
    )
    briefing: str = Field(..., description="Full briefing text for the podcast")

    current_stage: WorkflowStage = Field(
        default="director", description="Current stage of the workflow"
    )
    status: WorkflowStatus = Field(
        default="pending", description="Current status of the workflow"
    )

    # phase 1: just director and writer outputs
    director_output: Optional[Dict[str, Any]] = Field(
        default=None, description="Output from Director agent (stored as dict)"
    )
    writer_outputs: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Outputs from Writer agent for each segment"
    )

    error_message: Optional[str] = Field(
        default=None, description="Error message if workflow failed"
    )

    def get_director_output(self) -> Optional[DirectorOutput]:
        """parse director output from dict"""
        if self.director_output:
            return DirectorOutput(**self.director_output)
        return None

    def set_director_output(self, output: DirectorOutput) -> None:
        """save director output as dict"""
        self.director_output = output.model_dump()

    def get_writer_outputs(self) -> List[WriterOutput]:
        """parse writer outputs from dicts"""
        if self.writer_outputs:
            return [WriterOutput(**w) for w in self.writer_outputs]
        return []

    def set_writer_outputs(self, outputs: List[WriterOutput]) -> None:
        """save writer outputs as dicts"""
        self.writer_outputs = [w.model_dump() for w in outputs]

    def get_full_transcript(self) -> List[TranscriptLine]:
        """combine all segments into one transcript, sorted by segment index"""
        transcript: List[TranscriptLine] = []
        writer_outputs = self.get_writer_outputs()

        sorted_outputs = sorted(writer_outputs, key=lambda x: x.segment_index)

        for output in sorted_outputs:
            transcript.extend(output.transcript)

        return transcript

    async def mark_completed(self) -> None:
        """mark workflow as done"""
        self.status = "completed"
        self.current_stage = "completed"
        await self.save()

    async def mark_failed(self, error_message: str) -> None:
        """mark workflow as failed with error message"""
        self.status = "failed"
        self.current_stage = "failed"
        self.error_message = error_message
        await self.save()

    async def update_stage(
        self, stage: WorkflowStage, status: WorkflowStatus = "in_progress"
    ) -> None:
        """update current stage and status"""
        self.current_stage = stage
        self.status = status
        await self.save()
