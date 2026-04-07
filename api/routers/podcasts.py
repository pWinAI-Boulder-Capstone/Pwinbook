import asyncio
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel

from api.podcast_service import (
    PodcastGenerationRequest,
    PodcastGenerationResponse,
    PodcastService,
    _running_workflows,
)

router = APIRouter()

# Per-episode locks to prevent duplicate concurrent cover generation
_cover_locks: Dict[str, asyncio.Lock] = {}


class PodcastCoverResponse(BaseModel):
    image_data_url: Optional[str] = None
    error: Optional[str] = None
    cached: bool = False


async def _build_podcast_cover_prompt(episode, text_model_id: str = None) -> str:
    """Use an LLM to generate a focused image prompt based on the podcast content."""
    name = getattr(episode, "name", None) or "Podcast episode"
    briefing = (getattr(episode, "briefing", None) or "")[:1500]
    t = getattr(episode, "transcript", None) or {}
    dialogue_snippets: List[str] = []
    if isinstance(t, dict):
        arr = t.get("transcript") or t.get("dialogue") or []
        if isinstance(arr, list):
            for item in arr[:10]:
                if isinstance(item, dict):
                    d = item.get("dialogue") or item.get("text") or ""
                    if isinstance(d, str) and d.strip():
                        dialogue_snippets.append(d.strip()[:300])
    dialogue_text = "\n".join(dialogue_snippets)[:3000]

    # Build a summary of the podcast content for the LLM
    content_parts = [f"Episode title: {name}"]
    if briefing.strip():
        content_parts.append(f"Briefing/description: {briefing}")
    if dialogue_text.strip():
        content_parts.append(f"Opening dialogue:\n{dialogue_text}")
    content_summary = "\n\n".join(content_parts)

    system_prompt = (
        "You are an image prompt writer. Your ONLY job: read the podcast content below "
        "and write a single image generation prompt (40-80 words) that visually represents "
        "the podcast's topic.\n\n"
        "The podcast is about: " + name + "\n\n"
        "Write an image prompt that shows something DIRECTLY RELATED to this topic. "
        "For example:\n"
        "- Podcast about 'Vision Transformers' → 'Wide 16:9 cinematic podcast cover illustration: "
        "a grid of image patches flowing through luminous neural network layers, attention lines "
        "connecting distant patches, vivid blues and purples, dramatic lighting, cinematic digital art'\n"
        "- Podcast about 'Climate Change' → 'Wide 16:9 cinematic podcast cover illustration: "
        "polar ice cap cracking apart under warm orange sunset, ocean water rising around glaciers, "
        "vivid colors, dramatic lighting, cinematic digital art'\n\n"
        "Your prompt MUST be about: " + name + "\n"
        "Style: vivid cinematic digital art with rich colors and dramatic lighting. "
        "Always start with 'Wide 16:9 cinematic podcast cover illustration:'.\n"
        "Do NOT generate charts, graphs, people sitting on benches, or generic stock-photo scenes.\n"
        "No text, no letters, no words, no logos, no watermarks in the image.\n"
        "Output ONLY the image prompt, nothing else."
    )

    try:
        from open_notebook.graphs.utils import provision_langchain_model
        from langchain_core.messages import SystemMessage, HumanMessage

        model = await provision_langchain_model(content_summary, text_model_id, "chat", max_tokens=2000)
        response = model.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Write an image prompt for this podcast:\n\n{content_summary}"),
        ])
        llm_prompt = (getattr(response, "content", None) or "").strip()
        if llm_prompt and len(llm_prompt) > 20:
            logger.info(f"Cover prompt: LLM generated for '{name}': {llm_prompt}")
            return llm_prompt[:4000]
        logger.warning(f"Cover prompt: LLM response too short for '{name}': {llm_prompt!r}")
    except Exception as e:
        logger.warning(f"Cover prompt: LLM failed ({e}), using fallback")

    # Fallback: simple direct prompt if LLM fails
    return (
        f"Wide 16:9 cinematic podcast cover illustration about: {name}. "
        f"{briefing[:500]} "
        "Style: vivid cinematic digital art with rich colors and dramatic lighting. "
        "No text, no letters, no words, no logos, no watermarks."
    )[:4000]


class PodcastEpisodeResponse(BaseModel):
    id: str
    name: str
    episode_profile: dict
    speaker_profile: dict
    briefing: str
    audio_file: Optional[str] = None
    audio_url: Optional[str] = None
    transcript: Optional[dict] = None
    outline: Optional[dict] = None
    created: Optional[str] = None
    job_status: Optional[str] = None


def _resolve_audio_path(audio_file: str) -> Path:
    if audio_file.startswith("file://"):
        parsed = urlparse(audio_file)
        return Path(unquote(parsed.path))
    return Path(audio_file)


@router.post("/podcasts/generate", response_model=PodcastGenerationResponse)
async def generate_podcast(request: PodcastGenerationRequest):
    """
    Generate a podcast episode using the multi-agent workflow.
    Returns immediately with episode ID for status tracking.
    The workflow runs in the background (Director → Writers → Reviewer → Compliance).
    """
    try:
        episode_id = await PodcastService.submit_generation_job(
            episode_profile_name=request.episode_profile,
            speaker_profile_name=request.speaker_profile,
            episode_name=request.episode_name,
            notebook_id=request.notebook_id,
            content=request.content,
            briefing_suffix=request.briefing_suffix,
            podcast_length=request.podcast_length,
        )

        return PodcastGenerationResponse(
            job_id=episode_id,
            status="running",
            message=f"Multi-agent podcast generation started for '{request.episode_name}'",
            episode_profile=request.episode_profile,
            episode_name=request.episode_name,
        )

    except Exception as e:
        logger.error(f"Error generating podcast: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to generate podcast: {str(e)}"
        )


@router.get("/podcasts/jobs/{job_id}")
async def get_podcast_job_status(job_id: str):
    """Get the status of a podcast generation job"""
    try:
        status_data = await PodcastService.get_job_status(job_id)
        return status_data

    except Exception as e:
        logger.error(f"Error fetching podcast job status: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch job status: {str(e)}"
        )


@router.get("/podcasts/episodes", response_model=List[PodcastEpisodeResponse])
async def list_podcast_episodes():
    """List all podcast episodes"""
    try:
        episodes = await PodcastService.list_episodes()

        response_episodes = []
        for episode in episodes:
            episode_id_str = str(episode.id)

            # Determine job status from multiple sources
            job_status = None
            status_override = getattr(episode, "job_status_override", None)

            if episode_id_str in _running_workflows:
                # Active background workflow
                job_status = "running"
            elif status_override:
                # Status set by background workflow completion/failure
                job_status = status_override
            elif episode.command:
                # Legacy: old surreal-commands job
                try:
                    job_status = await episode.get_job_status()
                except Exception:
                    job_status = "unknown"
            elif episode.audio_file:
                # No command but has audio file = completed import
                job_status = "completed"
            elif episode.transcript and isinstance(episode.transcript, dict) and (episode.transcript.get("transcript") or episode.transcript.get("dialogue")):
                # Has transcript from agentic workflow = completed
                job_status = "completed"
            else:
                # No command, no audio, no transcript — skip
                continue

            audio_url = None
            if episode.audio_file:
                audio_path = _resolve_audio_path(episode.audio_file)
                if audio_path.exists():
                    audio_url = f"/api/podcasts/episodes/{episode.id}/audio"

            response_episodes.append(
                PodcastEpisodeResponse(
                    id=str(episode.id),
                    name=episode.name,
                    episode_profile=episode.episode_profile,
                    speaker_profile=episode.speaker_profile,
                    briefing=episode.briefing,
                    audio_file=episode.audio_file,
                    audio_url=audio_url,
                    transcript=episode.transcript,
                    outline=episode.outline,
                    created=str(episode.created) if episode.created else None,
                    job_status=job_status,
                )
            )

        return response_episodes

    except Exception as e:
        logger.error(f"Error listing podcast episodes: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to list podcast episodes: {str(e)}"
        )


@router.post("/podcasts/episodes/{episode_id}/cover-image", response_model=PodcastCoverResponse)
async def generate_podcast_episode_cover(
    episode_id: str,
    force: bool = Query(False, description="Regenerate even if a cover is already stored"),
):
    """
    Generate cover art for an episode using the default OpenRouter image model.
    Caches the data URL on the episode transcript under `cover_image_data_url`.
    Uses per-episode locking to prevent duplicate concurrent generation.
    """
    # Acquire a per-episode lock so only one generation runs at a time
    if episode_id not in _cover_locks:
        _cover_locks[episode_id] = asyncio.Lock()
    lock = _cover_locks[episode_id]

    async with lock:
        try:
            episode = await PodcastService.get_episode(episode_id)
        except Exception as e:
            logger.error(f"Cover image: episode not found {episode_id}: {e}")
            raise HTTPException(status_code=404, detail="Episode not found")

        t = episode.transcript if isinstance(episode.transcript, dict) else {}
        existing = t.get("cover_image_data_url") if isinstance(t, dict) else None
        if (
            not force
            and isinstance(existing, str)
            and existing.startswith("data:image/")
        ):
            logger.debug(f"Cover image: returning cached cover for {episode_id}")
            return PodcastCoverResponse(image_data_url=existing, cached=True)

        try:
            from open_notebook.utils.openrouter_api import generate_image
            from open_notebook.domain.podcast import EpisodeProfile

            # Use the LIVE profile from DB (not the frozen snapshot on the episode)
            # so that model changes in settings take effect for cover generation
            ep_profile = episode.episode_profile if isinstance(episode.episode_profile, dict) else {}
            profile_name = ep_profile.get("name")
            live_profile = await EpisodeProfile.get_by_name(profile_name) if profile_name else None

            if live_profile:
                profile_image_model = live_profile.image_model or None
                text_model_id = live_profile.outline_model or None
                logger.info(f"Cover image: using LIVE profile '{profile_name}', outline_model={text_model_id!r}, image_model={profile_image_model!r}")
            else:
                profile_image_model = ep_profile.get("image_model") or None
                text_model_id = ep_profile.get("outline_model") or None
                logger.info(f"Cover image: live profile '{profile_name}' not found, using snapshot: outline_model={text_model_id!r}, image_model={profile_image_model!r}")

            prompt = await _build_podcast_cover_prompt(episode, text_model_id=text_model_id)
            logger.info(f"Cover image: generating for {episode_id} (force={force})")

            result = await generate_image(prompt, model_id=profile_image_model)
        except Exception as e:
            logger.exception(f"Cover image generation failed for {episode_id}: {e}")
            return PodcastCoverResponse(error=str(e)[:500])

        if isinstance(result, str) and result.startswith("data:image/"):
            merged = dict(t) if isinstance(t, dict) else {}
            merged["cover_image_data_url"] = result
            episode.transcript = merged
            await episode.save()
            logger.info(f"Cover image: saved new cover for {episode_id}")
            return PodcastCoverResponse(image_data_url=result, cached=False)

        err = result if isinstance(result, str) else "Image generation failed"
        logger.warning(f"Cover image: generation returned non-image for {episode_id}: {err[:200]}")
        return PodcastCoverResponse(error=err[:500])


@router.get("/podcasts/episodes/{episode_id}", response_model=PodcastEpisodeResponse)
async def get_podcast_episode(episode_id: str):
    """Get a specific podcast episode"""
    try:
        episode = await PodcastService.get_episode(episode_id)

        # Determine job status from multiple sources
        episode_id_str = str(episode.id)
        job_status = None
        status_override = getattr(episode, "job_status_override", None)

        if episode_id_str in _running_workflows:
            job_status = "running"
        elif status_override:
            job_status = status_override
        elif episode.command:
            try:
                job_status = await episode.get_job_status()
            except Exception:
                job_status = "unknown"
        elif episode.audio_file:
            job_status = "completed"
        elif episode.transcript and isinstance(episode.transcript, dict) and (episode.transcript.get("transcript") or episode.transcript.get("dialogue")):
            job_status = "completed"
        else:
            job_status = "unknown"

        audio_url = None
        if episode.audio_file:
            audio_path = _resolve_audio_path(episode.audio_file)
            if audio_path.exists():
                audio_url = f"/api/podcasts/episodes/{episode.id}/audio"

        return PodcastEpisodeResponse(
            id=str(episode.id),
            name=episode.name,
            episode_profile=episode.episode_profile,
            speaker_profile=episode.speaker_profile,
            briefing=episode.briefing,
            audio_file=episode.audio_file,
            audio_url=audio_url,
            transcript=episode.transcript,
            outline=episode.outline,
            created=str(episode.created) if episode.created else None,
            job_status=job_status,
        )

    except Exception as e:
        logger.error(f"Error fetching podcast episode: {str(e)}")
        raise HTTPException(status_code=404, detail=f"Episode not found: {str(e)}")


@router.get("/podcasts/episodes/{episode_id}/audio")
async def stream_podcast_episode_audio(episode_id: str):
    """Stream the audio file associated with a podcast episode"""
    try:
        episode = await PodcastService.get_episode(episode_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching podcast episode for audio: {str(e)}")
        raise HTTPException(status_code=404, detail=f"Episode not found: {str(e)}")

    if not episode.audio_file:
        raise HTTPException(status_code=404, detail="Episode has no audio file")

    audio_path = _resolve_audio_path(episode.audio_file)
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found on disk")

    return FileResponse(
        audio_path,
        media_type="audio/mpeg",
        filename=audio_path.name,
    )


@router.delete("/podcasts/episodes/{episode_id}")
async def delete_podcast_episode(episode_id: str):
    """Delete a podcast episode and its associated audio file"""
    try:
        # Get the episode first to check if it exists and get the audio file path
        episode = await PodcastService.get_episode(episode_id)
        
        # Delete the physical audio file if it exists
        if episode.audio_file:
            audio_path = _resolve_audio_path(episode.audio_file)
            if audio_path.exists():
                try:
                    audio_path.unlink()
                    logger.info(f"Deleted audio file: {audio_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete audio file {audio_path}: {e}")
        
        # Delete the episode from the database
        await episode.delete()
        
        logger.info(f"Deleted podcast episode: {episode_id}")
        return {"message": "Episode deleted successfully", "episode_id": episode_id}
        
    except Exception as e:
        logger.error(f"Error deleting podcast episode: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete episode: {str(e)}")
