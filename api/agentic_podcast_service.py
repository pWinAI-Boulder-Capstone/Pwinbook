# service layer for agentic podcast workflows

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from open_notebook.domain.agentic_podcast import (
    AgenticPodcastWorkflow,
    TranscriptLine,
)
from open_notebook.domain.notebook import Notebook
from open_notebook.domain.podcast import EpisodeProfile, SpeakerProfile


class AgenticWorkflowRequest(BaseModel):
    episode_profile: str = Field(..., description="Name of episode profile to use")
    episode_name: str = Field(..., description="Name for the podcast episode")
    content: Optional[str] = Field(
        default=None, description="Source content for the podcast"
    )
    notebook_id: Optional[str] = Field(
        default=None, description="Notebook ID to extract content from"
    )
    briefing_suffix: Optional[str] = Field(
        default=None, description="Additional briefing instructions"
    )
    num_segments: Optional[int] = Field(
        default=None, description="Number of segments (uses profile default if not specified)"
    )


class AgenticWorkflowResponse(BaseModel):
    workflow_id: str
    name: str
    status: str
    current_stage: str
    episode_profile: str
    speaker_profile: str
    message: Optional[str] = None


class AgenticWorkflowDetailResponse(BaseModel):
    workflow_id: str
    name: str
    status: str
    current_stage: str
    episode_profile: str
    speaker_profile: str
    briefing: str
    created: Optional[str] = None
    updated: Optional[str] = None
    director_output: Optional[Dict[str, Any]] = None
    writer_outputs: Optional[List[Dict[str, Any]]] = None
    error_message: Optional[str] = None


class TranscriptResponse(BaseModel):
    workflow_id: str
    episode_name: str
    transcript: List[Dict[str, str]]
    total_turns: int


class AgenticPodcastService:

    @staticmethod
    async def _gather_notebook_content(
        notebook_id: str,
        max_chars_total: int = 100_000,
        max_chars_per_item: int = 15_000,
    ) -> str:
        """pull all sources and notes from a notebook into one text blob"""
        notebook = await Notebook.get(notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")

        parts: List[str] = [
            f"# {notebook.name}\n\n{notebook.description or ''}\n\n"
        ]
        total = len(parts[0])

        # grab all sources
        try:
            sources = await notebook.get_sources()
            for source_stub in sources:
                if total >= max_chars_total:
                    break
                try:
                    from open_notebook.domain.notebook import Source

                    full_source = await Source.get(str(source_stub.id))
                    if not full_source:
                        continue
                    title = getattr(full_source, "title", None) or "(untitled)"
                    full_text = getattr(full_source, "full_text", None) or ""
                    excerpt = full_text[:max_chars_per_item]
                    block = f"\n## Source: {title}\n\n{excerpt}\n"
                    parts.append(block)
                    total += len(block)
                except Exception as e:
                    logger.warning(f"couldn't load source {source_stub.id}: {e}")
                    continue
        except Exception as e:
            logger.warning(f"couldn't load notebook sources: {e}")

        # grab all notes
        try:
            notes = await notebook.get_notes()
            for note_stub in notes:
                if total >= max_chars_total:
                    break
                try:
                    from open_notebook.domain.notebook import Note

                    full_note = await Note.get(str(note_stub.id))
                    if not full_note:
                        continue
                    title = getattr(full_note, "title", None) or "(untitled)"
                    content = getattr(full_note, "content", None) or ""
                    excerpt = content[:max_chars_per_item]
                    block = f"\n## Note: {title}\n\n{excerpt}\n"
                    parts.append(block)
                    total += len(block)
                except Exception as e:
                    logger.warning(f"couldn't load note {note_stub.id}: {e}")
                    continue
        except Exception as e:
            logger.warning(f"couldn't load notebook notes: {e}")

        return "".join(parts).strip()

    @staticmethod
    def _build_briefing(
        episode_name: str, base_briefing: str, briefing_suffix: Optional[str]
    ) -> str:
        """combine base briefing with any extra instructions from user"""
        briefing = f"Episode: {episode_name}\n\n{base_briefing}".strip()
        if briefing_suffix and briefing_suffix.strip():
            briefing += f"\n\nAdditional instructions:\n{briefing_suffix.strip()}"
        return briefing

    @staticmethod
    async def create_workflow(request: AgenticWorkflowRequest) -> AgenticWorkflowResponse:
        """create workflow and run director + writer agents"""
        try:
            # make sure profiles exist
            episode_profile = await EpisodeProfile.get_by_name(request.episode_profile)
            if not episode_profile:
                raise HTTPException(
                    status_code=404,
                    detail=f"Episode profile '{request.episode_profile}' not found",
                )

            speaker_profile = await SpeakerProfile.get_by_name(
                episode_profile.speaker_config
            )
            if not speaker_profile:
                raise HTTPException(
                    status_code=404,
                    detail=f"Speaker profile '{episode_profile.speaker_config}' not found",
                )

            # get content from direct input or notebook
            content: str
            if request.content:
                content = request.content
            elif request.notebook_id:
                content = await AgenticPodcastService._gather_notebook_content(
                    request.notebook_id
                )
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Either 'content' or 'notebook_id' must be provided",
                )

            briefing = AgenticPodcastService._build_briefing(
                request.episode_name,
                episode_profile.default_briefing,
                request.briefing_suffix,
            )

            num_segments = request.num_segments or episode_profile.num_segments

            # create workflow record first
            workflow = AgenticPodcastWorkflow(
                name=request.episode_name,
                content=content,
                notebook_id=request.notebook_id,
                episode_profile_name=episode_profile.name,
                speaker_profile_name=speaker_profile.name,
                briefing=briefing,
                current_stage="director",
                status="pending",
            )
            await workflow.save()

            logger.info(f"created workflow {workflow.id} for '{request.episode_name}'")

            # run the whole thing (phase 1: synchronous)
            try:
                from open_notebook.graphs.agentic_podcast import (
                    run_agentic_podcast_workflow,
                )

                completed_workflow = await run_agentic_podcast_workflow(
                    workflow_id=str(workflow.id),
                    content=content,
                    briefing=briefing,
                    speakers=speaker_profile.speakers,
                    episode_profile_name=episode_profile.name,
                    speaker_profile_name=speaker_profile.name,
                    num_segments=num_segments,
                    outline_model=episode_profile.outline_model,
                    transcript_model=episode_profile.transcript_model,
                )

                return AgenticWorkflowResponse(
                    workflow_id=str(completed_workflow.id),
                    name=completed_workflow.name,
                    status=completed_workflow.status,
                    current_stage=completed_workflow.current_stage,
                    episode_profile=episode_profile.name,
                    speaker_profile=speaker_profile.name,
                    message="Workflow completed successfully"
                    if completed_workflow.status == "completed"
                    else f"Workflow failed: {completed_workflow.error_message}",
                )

            except Exception as e:
                logger.error(f"workflow execution failed: {e}")
                await workflow.mark_failed(str(e))
                raise HTTPException(
                    status_code=500, detail=f"Workflow execution failed: {str(e)}"
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"couldn't create workflow: {e}")
            logger.exception(e)
            raise HTTPException(
                status_code=500, detail=f"Failed to create workflow: {str(e)}"
            )

    @staticmethod
    async def get_workflow(workflow_id: str) -> AgenticWorkflowDetailResponse:
        """get full workflow details including all agent outputs"""
        try:
            workflow = await AgenticPodcastWorkflow.get(workflow_id)
            if not workflow:
                raise HTTPException(status_code=404, detail="Workflow not found")

            return AgenticWorkflowDetailResponse(
                workflow_id=str(workflow.id),
                name=workflow.name,
                status=workflow.status,
                current_stage=workflow.current_stage,
                episode_profile=workflow.episode_profile_name,
                speaker_profile=workflow.speaker_profile_name,
                briefing=workflow.briefing,
                created=workflow.created.isoformat() if workflow.created else None,
                updated=workflow.updated.isoformat() if workflow.updated else None,
                director_output=workflow.director_output,
                writer_outputs=workflow.writer_outputs,
                error_message=workflow.error_message,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"couldn't get workflow {workflow_id}: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to get workflow: {str(e)}"
            )

    @staticmethod
    async def get_transcript(workflow_id: str) -> TranscriptResponse:
        """get the full transcript with all segments combined in order"""
        try:
            workflow = await AgenticPodcastWorkflow.get(workflow_id)
            if not workflow:
                raise HTTPException(status_code=404, detail="Workflow not found")

            if workflow.status != "completed":
                raise HTTPException(
                    status_code=400,
                    detail=f"Workflow is not completed (status: {workflow.status})",
                )

            transcript = workflow.get_full_transcript()

            return TranscriptResponse(
                workflow_id=str(workflow.id),
                episode_name=workflow.name,
                transcript=[
                    {"speaker": line.speaker, "dialogue": line.dialogue}
                    for line in transcript
                ],
                total_turns=len(transcript),
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"couldn't get transcript for {workflow_id}: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to get transcript: {str(e)}"
            )

    @staticmethod
    async def list_workflows() -> List[AgenticWorkflowResponse]:
        """list all workflows, newest first"""
        try:
            workflows = await AgenticPodcastWorkflow.get_all(order_by="created desc")

            return [
                AgenticWorkflowResponse(
                    workflow_id=str(w.id),
                    name=w.name,
                    status=w.status,
                    current_stage=w.current_stage,
                    episode_profile=w.episode_profile_name,
                    speaker_profile=w.speaker_profile_name,
                )
                for w in workflows
            ]

        except Exception as e:
            logger.error(f"couldn't list workflows: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to list workflows: {str(e)}"
            )

    @staticmethod
    async def delete_workflow(workflow_id: str) -> Dict[str, str]:
        """delete a workflow"""
        try:
            workflow = await AgenticPodcastWorkflow.get(workflow_id)
            if not workflow:
                raise HTTPException(status_code=404, detail="Workflow not found")

            await workflow.delete()
            logger.info(f"deleted workflow {workflow_id}")

            return {"message": "Workflow deleted successfully"}

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"couldn't delete workflow {workflow_id}: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to delete workflow: {str(e)}"
            )
