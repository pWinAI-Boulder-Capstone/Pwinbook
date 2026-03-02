import asyncio
from typing import Any, Dict, Optional

from fastapi import HTTPException
from loguru import logger
from pydantic import BaseModel

from open_notebook.domain.notebook import Notebook
from open_notebook.domain.podcast import EpisodeProfile, PodcastEpisode, SpeakerProfile
from api.agentic_podcast_service import AgenticPodcastService, AgenticWorkflowRequest


# in-memory tracking of background workflow tasks
_running_workflows: Dict[str, asyncio.Task] = {}


class PodcastGenerationRequest(BaseModel):
    """Request model for podcast generation"""

    episode_profile: str
    speaker_profile: str
    episode_name: str
    content: Optional[str] = None
    notebook_id: Optional[str] = None
    briefing_suffix: Optional[str] = None
    podcast_length: Optional[str] = None  # 'short', 'medium', 'long'


# Podcast length presets
# TTS generates ~150 words/minute, so we set total word budgets
# to achieve deterministic audio durations.
# target_words_per_turn controls how verbose each dialogue line is.
PODCAST_LENGTH_PRESETS = {
    "short": {
        "max_turns": 10,
        "num_segments": 3,
        "target_duration_minutes": 4,
        "target_words_per_turn": 30,
    },
    "medium": {
        "max_turns": 14,
        "num_segments": 4,
        "target_duration_minutes": 8,
        "target_words_per_turn": 30,
    },
    "long": {
        "max_turns": 18,
        "num_segments": 5,
        "target_duration_minutes": 14,
        "target_words_per_turn": 35,
    },
}


class PodcastGenerationResponse(BaseModel):
    """Response model for podcast generation"""

    job_id: str
    status: str
    message: str
    episode_profile: str
    episode_name: str


async def _run_workflow_background(
    episode_id: str,
    workflow_request: AgenticWorkflowRequest,
    episode_profile: EpisodeProfile,
    speaker_profile: SpeakerProfile,
    podcast_length: str = "medium",
) -> None:
    """Run the multi-agent workflow in background and update the PodcastEpisode when done."""
    try:
        logger.info(f"Background workflow starting for episode {episode_id}")
        response = await AgenticPodcastService.create_workflow(workflow_request)

        # reload the episode record to update it
        try:
            episode = await PodcastEpisode.get(episode_id)
        except Exception:
            logger.error(f"Episode {episode_id} disappeared during workflow (deleted?)")
            return
        if not episode:
            logger.error(f"Episode {episode_id} disappeared during workflow")
            return

        # fetch the completed workflow to get transcript and outline
        from open_notebook.domain.agentic_podcast import AgenticPodcastWorkflow

        workflow = await AgenticPodcastWorkflow.get(response.workflow_id)
        if not workflow:
            logger.error(f"Workflow {response.workflow_id} not found after completion")
            episode.job_status_override = "failed"
            await episode.save()
            return

        # build transcript from workflow — format must match frontend expectations:
        # { "transcript": [{speaker, dialogue, citation, pacing_cue, pronunciation_notes}, ...] }
        transcript_lines = workflow.get_full_transcript()
        episode.transcript = {
            "transcript": [
                {
                    "speaker": line.speaker,
                    "dialogue": line.dialogue,
                    "citation": line.citation,
                    "pacing_cue": line.pacing_cue,
                    "pronunciation_notes": line.pronunciation_notes,
                }
                for line in transcript_lines
            ],
            "workflow_id": response.workflow_id,
        }

        # build outline from director output — format must match frontend:
        # { "segments": [{name, description, size}, ...] }
        if workflow.director_output:
            director = workflow.director_output
            # director_output is stored as a dict; extract segments list
            if isinstance(director, dict) and "segments" in director:
                episode.outline = {"segments": director["segments"]}
            else:
                episode.outline = director

        # add reviewer/compliance info to transcript metadata
        if workflow.reviewer_output:
            episode.transcript["reviewer"] = {
                "overall_score": workflow.reviewer_output.get("overall_score"),
                "summary": workflow.reviewer_output.get("summary"),
            }
        if workflow.compliance_output:
            episode.transcript["compliance"] = {
                "approved": workflow.compliance_output.get("approved"),
                "summary": workflow.compliance_output.get("summary"),
            }

        # save transcript progress before starting audio (so it's visible in UI)
        episode.job_status_override = "processing"
        await episode.save()

        logger.info(
            f"Transcript ready for episode {episode_id} "
            f"({len(transcript_lines)} lines), starting audio generation..."
        )

        # --- Transcript Word Count Validation ---
        preset = PODCAST_LENGTH_PRESETS.get(podcast_length, PODCAST_LENGTH_PRESETS["medium"])
        total_words = sum(len(line.dialogue.split()) for line in transcript_lines)
        expected_words = preset.get("target_duration_minutes", 7) * 120  # 120 wpm effective rate
        min_words = int(expected_words * 0.5)  # lower bound: 50% of target
        logger.info(
            f"Transcript word count: {total_words} words "
            f"(target: {expected_words}, minimum: {min_words})"
        )
        if total_words < min_words:
            logger.warning(
                f"Transcript too short for episode {episode_id}: "
                f"{total_words} words < {min_words} minimum. "
                f"Expected ~{expected_words} words for {podcast_length or 'medium'} podcast."
            )
            episode.transcript["word_count_warning"] = (
                f"Transcript is {total_words} words — target was ~{expected_words}. "
                f"Audio may be shorter than expected."
            )

        # --- Audio Generation ---
        # Compliance is advisory only — log warnings but always proceed with audio
        if workflow.compliance_output:
            compliance_approved = workflow.compliance_output.get("approved", True)
            if not compliance_approved:
                risk = workflow.compliance_output.get("risk_level", "unknown")
                logger.warning(
                    f"Compliance flagged transcript for episode {episode_id} "
                    f"(risk={risk}), proceeding with audio anyway"
                )

        if transcript_lines:
            try:
                from open_notebook.graphs.audio_generation import (
                    generate_audio_from_transcript,
                )

                # Build voice mapping from speaker profile
                voice_mapping = {
                    s["name"]: s["voice_id"] for s in speaker_profile.speakers
                }

                final_audio_path, duration_info = await generate_audio_from_transcript(
                    transcript=transcript_lines,
                    episode_name=workflow_request.episode_name,
                    tts_provider=speaker_profile.tts_provider,
                    tts_model=speaker_profile.tts_model,
                    voice_mapping=voice_mapping,
                    podcast_length=podcast_length,
                )

                episode.audio_file = str(final_audio_path)
                episode.transcript["duration_info"] = duration_info
                episode.job_status_override = "completed"
                await episode.save()

                logger.info(
                    f"Audio generation complete for episode {episode_id}: "
                    f"{final_audio_path} "
                    f"({duration_info.get('duration_minutes', '?')} min)"
                )

            except Exception as audio_err:
                logger.error(
                    f"Audio generation failed for episode {episode_id}: {audio_err}"
                )
                # Transcript is still saved — mark as completed but note audio failure
                episode.transcript["audio_error"] = str(audio_err)
                episode.job_status_override = "completed"
                await episode.save()
        else:
            logger.warning(f"No transcript lines for episode {episode_id}")
            episode.job_status_override = "completed"
            await episode.save()

        logger.info(
            f"Background workflow fully completed for episode {episode_id} "
            f"(workflow: {response.workflow_id})"
        )

    except Exception as e:
        logger.error(f"Background workflow failed for episode {episode_id}: {e}")
        try:
            episode = await PodcastEpisode.get(episode_id)
            if episode:
                episode.job_status_override = "failed"
                await episode.save()
        except Exception as save_err:
            logger.error(f"Failed to mark episode as failed: {save_err}")
    finally:
        _running_workflows.pop(episode_id, None)


class PodcastService:
    """Service layer for podcast operations"""

    @staticmethod
    async def submit_generation_job(
        episode_profile_name: str,
        speaker_profile_name: str,
        episode_name: str,
        notebook_id: Optional[str] = None,
        content: Optional[str] = None,
        briefing_suffix: Optional[str] = None,
        podcast_length: Optional[str] = None,
    ) -> str:
        """Submit a podcast generation job using the new multi-agent workflow.
        
        Creates a PodcastEpisode record immediately, then runs the
        Director → Writers → Reviewer → Compliance pipeline in the background.
        Returns the episode ID so the frontend can poll for status.
        """
        try:
            # Resolve podcast length preset
            length_preset = PODCAST_LENGTH_PRESETS.get(
                podcast_length or "medium",
                PODCAST_LENGTH_PRESETS["medium"],
            )

            # Validate profiles exist
            episode_profile = await EpisodeProfile.get_by_name(episode_profile_name)
            if not episode_profile:
                raise ValueError(f"Episode profile '{episode_profile_name}' not found")

            speaker_profile = await SpeakerProfile.get_by_name(speaker_profile_name)
            if not speaker_profile:
                raise ValueError(f"Speaker profile '{speaker_profile_name}' not found")

            # Create PodcastEpisode record immediately so it shows up in the UI
            episode = PodcastEpisode(
                name=episode_name,
                episode_profile={
                    "name": episode_profile.name,
                    "description": episode_profile.description or "",
                    "outline_provider": episode_profile.outline_provider,
                    "outline_model": episode_profile.outline_model,
                    "transcript_provider": episode_profile.transcript_provider,
                    "transcript_model": episode_profile.transcript_model,
                    "num_segments": episode_profile.num_segments,
                    "default_briefing": episode_profile.default_briefing,
                },
                speaker_profile={
                    "name": speaker_profile.name,
                    "description": speaker_profile.description or "",
                    "tts_provider": speaker_profile.tts_provider,
                    "tts_model": speaker_profile.tts_model,
                    "speakers": speaker_profile.speakers,
                },
                briefing=episode_profile.default_briefing,
                content=content or f"Notebook: {notebook_id}",
                job_status_override="running",
            )
            await episode.save()
            episode_id = str(episode.id)

            logger.info(
                f"Created episode {episode_id} for '{episode_name}' "
                f"(length={podcast_length or 'medium'}, "
                f"segments={length_preset['num_segments']}, "
                f"max_turns={length_preset['max_turns']}, "
                f"~{length_preset['target_duration_minutes']} min target)"
            )

            # Build the agentic workflow request
            workflow_request = AgenticWorkflowRequest(
                episode_profile=episode_profile_name,
                episode_name=episode_name,
                content=content,
                notebook_id=notebook_id,
                briefing_suffix=briefing_suffix,
                max_turns=length_preset["max_turns"],
                num_segments=length_preset["num_segments"],
                target_words_per_turn=length_preset["target_words_per_turn"],
                target_duration_minutes=length_preset["target_duration_minutes"],
            )

            # Launch workflow in background — returns immediately
            task = asyncio.create_task(
                _run_workflow_background(
                    episode_id, workflow_request, episode_profile, speaker_profile,
                    podcast_length=podcast_length or "medium",
                )
            )
            _running_workflows[episode_id] = task

            return episode_id

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to submit multi-agent workflow: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to submit multi-agent workflow: {str(e)}",
            )

    @staticmethod
    async def get_job_status(job_id: str) -> Dict[str, Any]:
        """Get status of a podcast generation job.
        
        The job_id is now a PodcastEpisode ID. We check if a background
        workflow task is still running, or return info from the episode record.
        """
        try:
            episode = await PodcastEpisode.get(job_id)
            if not episode:
                raise HTTPException(status_code=404, detail="Episode not found")

            # determine status
            is_running = job_id in _running_workflows
            status_override = getattr(episode, "job_status_override", None)

            if is_running:
                status = "running"
            elif status_override:
                status = status_override
            elif episode.transcript and (episode.transcript.get("transcript") or episode.transcript.get("dialogue")):
                status = "completed"
            else:
                status = "pending"

            workflow_id = None
            if episode.transcript and isinstance(episode.transcript, dict):
                workflow_id = episode.transcript.get("workflow_id")

            return {
                "job_id": job_id,
                "status": status,
                "workflow_id": workflow_id,
                "episode_name": episode.name,
                "episode_profile": episode.episode_profile.get("name", ""),
                "speaker_profile": episode.speaker_profile.get("name", ""),
                "created": str(episode.created) if episode.created else None,
                "has_transcript": bool(
                    episode.transcript and (episode.transcript.get("transcript") or episode.transcript.get("dialogue"))
                ),
                "has_outline": bool(episode.outline),
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get job status: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to get job status: {str(e)}"
            )

    @staticmethod
    async def list_episodes() -> list:
        """List all podcast episodes"""
        try:
            episodes = await PodcastEpisode.get_all(order_by="created desc")
            return episodes
        except Exception as e:
            logger.error(f"Failed to list podcast episodes: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to list episodes: {str(e)}"
            )

    @staticmethod
    async def get_episode(episode_id: str) -> PodcastEpisode:
        """Get a specific podcast episode"""
        try:
            episode = await PodcastEpisode.get(episode_id)
            return episode
        except Exception as e:
            logger.error(f"Failed to get podcast episode {episode_id}: {e}")
            raise HTTPException(status_code=404, detail=f"Episode not found: {str(e)}")


class DefaultProfiles:
    """Utility class for creating default profiles (if needed beyond migration data)"""

    @staticmethod
    async def create_default_episode_profiles():
        """Create default episode profiles if they don't exist"""
        try:
            # Check if profiles already exist
            existing = await EpisodeProfile.get_all()
            if existing:
                logger.info(f"Episode profiles already exist: {len(existing)} found")
                return existing

            # This would create profiles, but since we have migration data,
            # this is mainly for future extensibility
            logger.info(
                "Default episode profiles should be created via database migration"
            )
            return []

        except Exception as e:
            logger.error(f"Failed to create default episode profiles: {e}")
            raise

    @staticmethod
    async def create_default_speaker_profiles():
        """Create default speaker profiles if they don't exist"""
        try:
            # Check if profiles already exist
            existing = await SpeakerProfile.get_all()
            if existing:
                logger.info(f"Speaker profiles already exist: {len(existing)} found")
                return existing

            # This would create profiles, but since we have migration data,
            # this is mainly for future extensibility
            logger.info(
                "Default speaker profiles should be created via database migration"
            )
            return []

        except Exception as e:
            logger.error(f"Failed to create default speaker profiles: {e}")
            raise
