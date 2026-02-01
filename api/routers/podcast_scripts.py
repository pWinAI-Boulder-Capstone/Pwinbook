from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Literal, Optional

from ai_prompter import Prompter
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.output_parsers.pydantic import PydanticOutputParser
from loguru import logger
from pydantic import BaseModel, Field

from open_notebook.domain.notebook import Note, Notebook, Source
from open_notebook.domain.podcast import EpisodeProfile, SpeakerProfile
from open_notebook.graphs.utils import provision_langchain_model
from open_notebook.utils import clean_thinking_content
from open_notebook.domain.notebook import vector_search
from open_notebook.utils.web_search import WebSearchError, tavily_search

router = APIRouter()


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _extract_json_object(text: str) -> str:
    """Best-effort extraction of a JSON object from an LLM response.

    The model sometimes wraps JSON in code fences or adds brief pre/post text.
    We keep parsing strict JSON (no coercion), but extract the most likely JSON
    object substring to reduce OUTPUT_PARSING_FAILURE occurrences.
    """

    if not text:
        return text

    cleaned = text.strip()

    # Remove common markdown code fences.
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.replace("```json", "").replace("```", "").strip()

    # Extract the first top-level JSON object by bounding braces.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return cleaned

    return cleaned[start : end + 1].strip()


SegmentSize = Literal["short", "medium", "long"]
FactCheckMode = Literal["none", "notebook", "internet", "both"]


class OutlineSegment(BaseModel):
    name: str
    description: str
    size: SegmentSize = "medium"


class PodcastOutline(BaseModel):
    segments: List[OutlineSegment] = Field(default_factory=list)


class TranscriptLine(BaseModel):
    speaker: str
    dialogue: str


class InteractiveTranscript(BaseModel):
    transcript: List[TranscriptLine] = Field(default_factory=list)
    questions: List[str] = Field(default_factory=list)


class LiveTranscriptResponse(BaseModel):
    transcript: List[TranscriptLine] = Field(default_factory=list)
    next_suggestions: List[str] = Field(default_factory=list)
    await_user_question: Optional[str] = None


class CustomSpeaker(BaseModel):
    name: str
    backstory: str = ""
    personality: str = ""
    role: Optional[str] = None


class PodcastScriptOutlineRequest(BaseModel):
    episode_profile: str
    episode_name: str
    notebook_id: Optional[str] = None
    content: Optional[str] = None
    briefing_suffix: Optional[str] = None
    num_segments: Optional[int] = None
    model_override: Optional[str] = None


class PodcastScriptOutlineResponse(BaseModel):
    episode_profile: str
    speaker_profile: str
    episode_name: str
    briefing: str
    outline: PodcastOutline


class PodcastScriptSegmentRequest(BaseModel):
    episode_profile: str
    episode_name: str
    notebook_id: Optional[str] = None
    content: Optional[str] = None
    briefing_suffix: Optional[str] = None
    model_override: Optional[str] = None

    outline: PodcastOutline
    segment_index: int = Field(ge=0)

    transcript_so_far: Optional[List[TranscriptLine]] = None
    turns: int = Field(default=14, ge=4, le=80)
    ask_questions: bool = True
    user_interrupt: Optional[str] = None


class PodcastScriptSegmentResponse(BaseModel):
    episode_profile: str
    speaker_profile: str
    episode_name: str
    segment_index: int
    segment: OutlineSegment
    result: InteractiveTranscript


class PodcastLiveDiscussionRequest(BaseModel):
    episode_profile: Optional[str] = None
    episode_name: Optional[str] = None
    notebook_id: Optional[str] = None
    content: Optional[str] = None
    briefing_suffix: Optional[str] = None
    model_override: Optional[str] = None

    speakers_override: Optional[List[CustomSpeaker]] = None

    transcript_so_far: Optional[List[TranscriptLine]] = None
    turns: int = Field(default=6, ge=2, le=40)

    user_message: Optional[str] = Field(
        default=None,
        description="Optional user question/interrupt to incorporate now; if omitted, the panel continues on its own.",
    )
    fact_check_mode: FactCheckMode = "notebook"
    max_evidence: int = Field(default=5, ge=1, le=10)


def _build_evidence_query(
    *,
    user_message: Optional[str],
    transcript_so_far: Optional[List[TranscriptLine]],
    episode_name: str,
) -> str:
    msg = (user_message or "").strip()
    if msg:
        return msg
    if transcript_so_far:
        tail = [t.dialogue for t in transcript_so_far[-3:] if (t.dialogue or "").strip()]
        if tail:
            return " ".join(tail).strip()
    return (episode_name or "Live panel").strip()


def _default_live_briefing() -> str:
    return (
        "You are running a live, interruptible multi-speaker panel discussion. "
        "Keep turns short, interactive, and grounded in evidence when available."
    )


class PodcastLiveDiscussionEnvelopeResponse(BaseModel):
    episode_profile: str
    speaker_profile: str
    episode_name: str
    fact_check_mode: FactCheckMode
    trace: List[Dict[str, Any]] = Field(default_factory=list)
    evidence: Optional[List[Dict[str, Any]]] = None
    result: LiveTranscriptResponse


async def _gather_notebook_text_context(
    notebook_id: str,
    *,
    max_chars_total: int = 80_000,
    max_chars_per_item: int = 12_000,
) -> str:
    """Build a plain-text context blob from notebook sources and notes.

    Notes/sources returned via Notebook.get_sources/get_notes omit large fields, so we refetch each item.
    """

    notebook = await Notebook.get(notebook_id)
    if not notebook:
        raise HTTPException(status_code=404, detail="Notebook not found")

    parts: List[str] = [
        f"Notebook: {notebook.name}\nDescription: {notebook.description}\n"
    ]
    total = len(parts[0])

    # Sources
    try:
        sources = await notebook.get_sources()
    except Exception as e:
        logger.warning(f"Failed to load notebook sources: {e}")
        sources = []

    for source_stub in sources:
        if total >= max_chars_total:
            break
        try:
            full_source = await Source.get(str(source_stub.id))
            if not full_source:
                continue
            title = getattr(full_source, "title", None) or "(untitled source)"
            full_text = getattr(full_source, "full_text", None) or ""
            excerpt = full_text[:max_chars_per_item]
            block = f"\n=== SOURCE: {title} ({full_source.id}) ===\n{excerpt}\n"
            parts.append(block)
            total += len(block)
        except Exception as e:
            logger.warning(f"Failed to load source {source_stub.id}: {e}")
            continue

    # Notes
    try:
        notes = await notebook.get_notes()
    except Exception as e:
        logger.warning(f"Failed to load notebook notes: {e}")
        notes = []

    for note_stub in notes:
        if total >= max_chars_total:
            break
        try:
            full_note = await Note.get(str(note_stub.id))
            if not full_note:
                continue
            title = getattr(full_note, "title", None) or "(untitled note)"
            content = getattr(full_note, "content", None) or ""
            excerpt = content[:max_chars_per_item]
            block = f"\n=== NOTE: {title} ({full_note.id}) ===\n{excerpt}\n"
            parts.append(block)
            total += len(block)
        except Exception as e:
            logger.warning(f"Failed to load note {note_stub.id}: {e}")
            continue

    return "".join(parts).strip()


async def _get_content_or_notebook_context(content: Optional[str], notebook_id: Optional[str]) -> str:
    if content and content.strip():
        return content
    if notebook_id:
        return await _gather_notebook_text_context(notebook_id)
    raise HTTPException(status_code=400, detail="Provide either content or notebook_id")


def _build_briefing(episode_name: str, base_briefing: str, briefing_suffix: Optional[str]) -> str:
    briefing = f"Episode name: {episode_name}\n\n{base_briefing}".strip()
    if briefing_suffix:
        briefing += f"\n\nAdditional instructions from user:\n{briefing_suffix.strip()}"
    return briefing


def _normalize_speakers_for_prompt(
    *,
    speaker_profile: SpeakerProfile,
    speakers_override: Optional[List[CustomSpeaker]],
) -> List[Dict[str, Any]]:
    if speakers_override:
        speakers: List[Dict[str, Any]] = []
        for sp in speakers_override:
            speakers.append(
                {
                    "name": sp.name,
                    "backstory": (sp.backstory or "").strip() or (sp.role or "").strip(),
                    "personality": (sp.personality or "").strip(),
                }
            )
        return speakers

    # Default to profile
    return speaker_profile.speakers


async def _gather_evidence(
    *,
    mode: FactCheckMode,
    query: str,
    max_results: int,
) -> tuple[Optional[List[Dict[str, Any]]], List[Dict[str, Any]]]:
    query = (query or "").strip()
    trace: List[Dict[str, Any]] = []

    trace.append(
        {
            "step": "evidence.start",
            "mode": mode,
            "query": query,
            "max_results": max_results,
        }
    )

    if not query or mode == "none":
        trace.append(
            {
                "step": "evidence.skip",
                "reason": "empty_query" if not query else "mode_none",
            }
        )
        return None, trace

    if mode == "notebook":
        results = await vector_search(query, max_results, True, True)
        evidence: List[Dict[str, Any]] = []
        for r in results[:max_results]:
            if not isinstance(r, dict):
                continue
            evidence.append(
                {
                    "source": "notebook",
                    "id": r.get("id"),
                    "score": r.get("score"),
                    "type": r.get("type"),
                    "content": r.get("content") or r.get("text") or r.get("snippet"),
                }
            )
        trace.append(
            {
                "step": "evidence.done",
                "provider": "notebook.vector_search",
                "results": len(evidence),
                "found_nothing": len(evidence) == 0,
            }
        )
        return evidence, trace

    if mode == "internet":
        results = await tavily_search(query, max_results=max_results)
        for r in results:
            if isinstance(r, dict):
                r.setdefault("source", "internet")
        urls = [r.get("url") for r in results if isinstance(r, dict) and r.get("url")]
        trace.append(
            {
                "step": "evidence.done",
                "provider": "tavily.search",
                "results": len(results),
                "urls": urls,
                "found_nothing": len(results) == 0,
            }
        )
        return results, trace

    if mode == "both":
        notebook_evidence: List[Dict[str, Any]] = []
        internet_evidence: List[Dict[str, Any]] = []

        try:
            results = await vector_search(query, max_results, True, True)
            for r in results[:max_results]:
                if not isinstance(r, dict):
                    continue
                notebook_evidence.append(
                    {
                        "source": "notebook",
                        "id": r.get("id"),
                        "score": r.get("score"),
                        "type": r.get("type"),
                        "content": r.get("content")
                        or r.get("text")
                        or r.get("snippet"),
                    }
                )
            trace.append(
                {
                    "step": "evidence.done",
                    "provider": "notebook.vector_search",
                    "results": len(notebook_evidence),
                    "found_nothing": len(notebook_evidence) == 0,
                }
            )
        except Exception as e:
            trace.append(
                {
                    "step": "evidence.error",
                    "provider": "notebook.vector_search",
                    "error": str(e),
                }
            )

        try:
            results = await tavily_search(query, max_results=max_results)
            for r in results:
                if isinstance(r, dict):
                    r.setdefault("source", "internet")
                    internet_evidence.append(r)
            urls = [r.get("url") for r in internet_evidence if isinstance(r, dict) and r.get("url")]
            trace.append(
                {
                    "step": "evidence.done",
                    "provider": "tavily.search",
                    "results": len(internet_evidence),
                    "urls": urls,
                    "found_nothing": len(internet_evidence) == 0,
                }
            )
        except WebSearchError as e:
            trace.append(
                {
                    "step": "evidence.error",
                    "provider": "tavily.search",
                    "error": str(e),
                }
            )

        merged = [*notebook_evidence, *internet_evidence]
        return merged, trace

    trace.append({"step": "evidence.error", "error": "unknown_mode"})
    return None, trace


@router.post("/podcast-scripts/outline", response_model=PodcastScriptOutlineResponse)
async def generate_podcast_script_outline(request: PodcastScriptOutlineRequest):
    """Generate an outline for an agentic, multi-speaker podcast script."""
    try:
        episode_profile = await EpisodeProfile.get_by_name(request.episode_profile)
        if not episode_profile:
            raise HTTPException(status_code=404, detail="Episode profile not found")

        speaker_profile = await SpeakerProfile.get_by_name(episode_profile.speaker_config)
        if not speaker_profile:
            raise HTTPException(status_code=404, detail="Speaker profile not found")

        context = await _get_content_or_notebook_context(request.content, request.notebook_id)
        briefing = _build_briefing(request.episode_name, episode_profile.default_briefing, request.briefing_suffix)

        parser = PydanticOutputParser(pydantic_object=PodcastOutline)
        prompt_data: Dict[str, Any] = {
            "briefing": briefing,
            "context": context,
            "speakers": speaker_profile.speakers,
            "num_segments": request.num_segments or episode_profile.num_segments,
        }
        system_prompt = Prompter(prompt_template="podcast/outline", parser=parser).render(data=prompt_data)

        model = await provision_langchain_model(
            system_prompt,
            request.model_override,
            "tools",
            max_tokens=2500,
            structured={"type": "json"},
        )
        ai_message = await model.ainvoke(system_prompt)
        content = ai_message.content if isinstance(ai_message.content, str) else str(ai_message.content)
        cleaned = clean_thinking_content(content)
        outline = parser.parse(cleaned)

        return PodcastScriptOutlineResponse(
            episode_profile=episode_profile.name,
            speaker_profile=speaker_profile.name,
            episode_name=request.episode_name,
            briefing=briefing,
            outline=outline,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate podcast script outline: {e}")
        logger.exception(e)
        raise HTTPException(status_code=500, detail=f"Failed to generate outline: {str(e)}")


@router.post("/podcast-scripts/segment", response_model=PodcastScriptSegmentResponse)
async def generate_podcast_script_segment(request: PodcastScriptSegmentRequest):
    """Generate one segment of a multi-speaker podcast script, with optional pause questions."""
    try:
        episode_profile = await EpisodeProfile.get_by_name(request.episode_profile)
        if not episode_profile:
            raise HTTPException(status_code=404, detail="Episode profile not found")

        speaker_profile = await SpeakerProfile.get_by_name(episode_profile.speaker_config)
        if not speaker_profile:
            raise HTTPException(status_code=404, detail="Speaker profile not found")

        if request.segment_index >= len(request.outline.segments):
            raise HTTPException(status_code=400, detail="segment_index out of range")

        context = await _get_content_or_notebook_context(request.content, request.notebook_id)
        briefing = _build_briefing(request.episode_name, episode_profile.default_briefing, request.briefing_suffix)

        segment = request.outline.segments[request.segment_index]
        speaker_names = [s.get("name") for s in speaker_profile.speakers if s.get("name")]

        transcript_json: Optional[str] = None
        if request.transcript_so_far:
            transcript_json = InteractiveTranscript(
                transcript=request.transcript_so_far,
                questions=[],
            ).model_dump_json()

        parser = PydanticOutputParser(pydantic_object=InteractiveTranscript)
        prompt_data: Dict[str, Any] = {
            "briefing": briefing,
            "context": context,
            "speakers": speaker_profile.speakers,
            "outline": request.outline.model_dump_json(),
            "segment": segment.model_dump_json(),
            "speaker_names": speaker_names,
            "turns": request.turns,
            "transcript": transcript_json,
            "user_interrupt": request.user_interrupt,
            "ask_questions": request.ask_questions,
        }
        system_prompt = Prompter(
            prompt_template="podcast/interactive_transcript",
            parser=parser,
        ).render(data=prompt_data)

        model = await provision_langchain_model(
            system_prompt,
            request.model_override,
            "tools",
            max_tokens=3500,
            structured={"type": "json"},
        )
        ai_message = await model.ainvoke(system_prompt)
        content = ai_message.content if isinstance(ai_message.content, str) else str(ai_message.content)
        cleaned = _extract_json_object(clean_thinking_content(content))
        try:
            result = parser.parse(cleaned)
        except Exception as e:
            logger.error(f"Segment output parsing failure: {e}")
            logger.debug(f"Raw model output (cleaned/extracted): {cleaned[:2000]}")
            raise

        if not request.ask_questions:
            result.questions = []

        return PodcastScriptSegmentResponse(
            episode_profile=episode_profile.name,
            speaker_profile=speaker_profile.name,
            episode_name=request.episode_name,
            segment_index=request.segment_index,
            segment=segment,
            result=result,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate podcast script segment: {e}")
        logger.exception(e)
        raise HTTPException(status_code=500, detail=f"Failed to generate segment: {str(e)}")


@router.post("/podcast-scripts/live", response_model=PodcastLiveDiscussionEnvelopeResponse)
async def generate_live_podcast_discussion(request: PodcastLiveDiscussionRequest):
    """Generate the next few turns of a live multi-speaker discussion.

    This is designed for mid-conversation interruption by keeping each call small (few turns).
    """
    try:
        episode_profile: Optional[EpisodeProfile] = None
        speaker_profile: Optional[SpeakerProfile] = None

        episode_profile_name = (request.episode_profile or "").strip() or "custom_live"
        episode_name = (request.episode_name or "").strip() or "Live panel"

        if (request.episode_profile or "").strip():
            episode_profile = await EpisodeProfile.get_by_name(episode_profile_name)
            if not episode_profile:
                raise HTTPException(status_code=404, detail="Episode profile not found")

            speaker_profile = await SpeakerProfile.get_by_name(episode_profile.speaker_config)
            if not speaker_profile:
                raise HTTPException(status_code=404, detail="Speaker profile not found")

            base_briefing = episode_profile.default_briefing
            speaker_profile_name = speaker_profile.name
        else:
            if not request.speakers_override or len(request.speakers_override) < 1:
                raise HTTPException(
                    status_code=400,
                    detail="Live mode without an episode profile requires speakers_override.",
                )
            base_briefing = _default_live_briefing()
            speaker_profile_name = "custom_live"

        context = await _get_content_or_notebook_context(request.content, request.notebook_id)
        briefing = _build_briefing(episode_name, base_briefing, request.briefing_suffix)

        if speaker_profile is not None:
            speakers = _normalize_speakers_for_prompt(
                speaker_profile=speaker_profile,
                speakers_override=request.speakers_override,
            )
        else:
            speakers = [s.model_dump() for s in (request.speakers_override or [])]

        speaker_names = [s.get("name") for s in speakers if s.get("name")]

        evidence: Optional[List[Dict[str, Any]]] = None
        trace: List[Dict[str, Any]] = []
        try:
            evidence_query = _build_evidence_query(
                user_message=request.user_message,
                transcript_so_far=request.transcript_so_far,
                episode_name=episode_name,
            )
            evidence, trace = await _gather_evidence(
                mode=request.fact_check_mode,
                query=evidence_query,
                max_results=request.max_evidence,
            )
        except WebSearchError as e:
            trace.append(
                {
                    "step": "evidence.error",
                    "provider": "tavily.search",
                    "error": str(e),
                }
            )
            raise HTTPException(status_code=400, detail=str(e))

        transcript_json: Optional[str] = None
        if request.transcript_so_far:
            transcript_json = LiveTranscriptResponse(
                transcript=request.transcript_so_far,
                next_suggestions=[],
            ).model_dump_json()

        parser = PydanticOutputParser(pydantic_object=LiveTranscriptResponse)
        prompt_data: Dict[str, Any] = {
            "briefing": briefing,
            "context": context,
            "speakers": speakers,
            "speaker_names": speaker_names,
            "transcript": transcript_json,
            "turns": request.turns,
            "user_message": (request.user_message or "").strip(),
            "fact_check_mode": request.fact_check_mode,
            "research_evidence": evidence,
        }

        system_prompt = Prompter(
            prompt_template="podcast/live_discussion",
            parser=parser,
        ).render(data=prompt_data)

        model = await provision_langchain_model(
            system_prompt,
            request.model_override,
            "tools",
            max_tokens=1800,
            structured={"type": "json"},
        )
        ai_message = await model.ainvoke(system_prompt)
        content = ai_message.content if isinstance(ai_message.content, str) else str(ai_message.content)
        cleaned = _extract_json_object(clean_thinking_content(content))
        try:
            result = parser.parse(cleaned)
        except Exception as e:
            trace.append(
                {
                    "step": "output.parse.error",
                    "error": str(e),
                }
            )
            logger.error(f"Live output parsing failure: {e}")
            logger.debug(f"Raw model output (cleaned/extracted): {cleaned[:2000]}")
            raise

        # Fallback: if the model only used a single speaker name, relabel turns
        # round-robin across the allowed speaker list to preserve the multi-speaker UX.
        try:
            allowed_names: List[str] = []
            if request.speakers_override:
                allowed_names = [
                    s.name for s in request.speakers_override if (s.name or "").strip()
                ]
            else:
                allowed_names = [
                    str(s.get("name"))
                    for s in ((speaker_profile.speakers if speaker_profile else []) or [])
                    if isinstance(s, dict) and str(s.get("name") or "").strip()
                ]

            if allowed_names:
                used = [
                    t.speaker for t in result.transcript if (t.speaker or "").strip()
                ]
                unique_used = {u.strip() for u in used if u.strip()}
                if (
                    len(unique_used) <= 1
                    and len(allowed_names) >= 2
                    and len(result.transcript) >= 2
                ):
                    for idx, t in enumerate(result.transcript):
                        t.speaker = allowed_names[idx % len(allowed_names)]
                    trace.append(
                        {
                            "step": "speakers.relabel",
                            "reason": "model_returned_single_speaker",
                            "results": len(result.transcript),
                        }
                    )
        except Exception as e:
            trace.append({"step": "speakers.relabel.error", "error": str(e)})

        return PodcastLiveDiscussionEnvelopeResponse(
            episode_profile=episode_profile_name,
            speaker_profile=speaker_profile_name,
            episode_name=episode_name,
            fact_check_mode=request.fact_check_mode,
            trace=trace,
            evidence=evidence,
            result=result,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate live podcast discussion: {e}")
        logger.exception(e)
        raise HTTPException(status_code=500, detail=f"Failed to generate live discussion: {str(e)}")


@router.post("/podcast-scripts/live/stream")
async def stream_live_podcast_discussion(request: PodcastLiveDiscussionRequest):
    """Stream a live multi-speaker discussion as SSE.

    This is not true token streaming; we generate once, then stream trace + lines progressively.
    """

    async def _gen():
        trace: List[Dict[str, Any]] = []
        evidence: Optional[List[Dict[str, Any]]] = None

        try:
            episode_profile: Optional[EpisodeProfile] = None
            speaker_profile: Optional[SpeakerProfile] = None

            episode_profile_name = (request.episode_profile or "").strip() or "custom_live"
            episode_name = (request.episode_name or "").strip() or "Live panel"

            if (request.episode_profile or "").strip():
                episode_profile = await EpisodeProfile.get_by_name(episode_profile_name)
                if not episode_profile:
                    yield _sse("error", {"detail": "Episode profile not found"})
                    return

                speaker_profile = await SpeakerProfile.get_by_name(
                    episode_profile.speaker_config
                )
                if not speaker_profile:
                    yield _sse("error", {"detail": "Speaker profile not found"})
                    return

                base_briefing = episode_profile.default_briefing
                speaker_profile_name = speaker_profile.name
            else:
                if not request.speakers_override or len(request.speakers_override) < 1:
                    yield _sse(
                        "error",
                        {
                            "detail": "Live mode without an episode profile requires speakers_override.",
                        },
                    )
                    return
                base_briefing = _default_live_briefing()
                speaker_profile_name = "custom_live"

            context = await _get_content_or_notebook_context(
                request.content, request.notebook_id
            )
            briefing = _build_briefing(episode_name, base_briefing, request.briefing_suffix)

            if speaker_profile is not None:
                speakers = _normalize_speakers_for_prompt(
                    speaker_profile=speaker_profile,
                    speakers_override=request.speakers_override,
                )
            else:
                speakers = [s.model_dump() for s in (request.speakers_override or [])]

            speaker_names = [s.get("name") for s in speakers if s.get("name")]

            yield _sse(
                "meta",
                {
                    "episode_profile": episode_profile_name,
                    "speaker_profile": speaker_profile_name,
                    "episode_name": episode_name,
                    "fact_check_mode": request.fact_check_mode,
                    "speakers": speaker_names,
                },
            )

            try:
                evidence_query = _build_evidence_query(
                    user_message=request.user_message,
                    transcript_so_far=request.transcript_so_far,
                    episode_name=episode_name,
                )
                evidence, trace = await _gather_evidence(
                    mode=request.fact_check_mode,
                    query=evidence_query,
                    max_results=request.max_evidence,
                )
            except WebSearchError as e:
                yield _sse("trace", {"step": "evidence.error", "provider": "tavily.search", "error": str(e)})
                yield _sse("error", {"detail": str(e)})
                return

            for t in trace:
                yield _sse("trace", t)

            if evidence is not None:
                yield _sse("evidence", evidence)

            transcript_json: Optional[str] = None
            if request.transcript_so_far:
                transcript_json = LiveTranscriptResponse(
                    transcript=request.transcript_so_far,
                    next_suggestions=[],
                ).model_dump_json()

            parser = PydanticOutputParser(pydantic_object=LiveTranscriptResponse)
            prompt_data: Dict[str, Any] = {
                "briefing": briefing,
                "context": context,
                "speakers": speakers,
                "speaker_names": speaker_names,
                "transcript": transcript_json,
                "turns": request.turns,
                "user_message": (request.user_message or "").strip(),
                "fact_check_mode": request.fact_check_mode,
                "research_evidence": evidence,
            }

            system_prompt = Prompter(
                prompt_template="podcast/live_discussion",
                parser=parser,
            ).render(data=prompt_data)

            model = await provision_langchain_model(
                system_prompt,
                request.model_override,
                "tools",
                max_tokens=1800,
                structured={"type": "json"},
            )
            ai_message = await model.ainvoke(system_prompt)
            content = (
                ai_message.content
                if isinstance(ai_message.content, str)
                else str(ai_message.content)
            )
            cleaned = _extract_json_object(clean_thinking_content(content))
            try:
                result = parser.parse(cleaned)
            except Exception as e:
                yield _sse("trace", {"step": "output.parse.error", "error": str(e)})
                logger.error(f"Stream live output parsing failure: {e}")
                logger.debug(f"Raw model output (cleaned/extracted): {cleaned[:2000]}")
                yield _sse(
                    "error",
                    {
                        "detail": "Failed to parse model JSON output. Try reducing turns or re-running.",
                    },
                )
                return

            # Relabel if the model collapsed to a single speaker.
            try:
                allowed_names: List[str] = []
                if request.speakers_override:
                    allowed_names = [
                        s.name
                        for s in request.speakers_override
                        if (s.name or "").strip()
                    ]
                else:
                    allowed_names = [
                        str(s.get("name"))
                        for s in ((speaker_profile.speakers if speaker_profile else []) or [])
                        if isinstance(s, dict) and str(s.get("name") or "").strip()
                    ]

                used = [t.speaker for t in result.transcript if (t.speaker or "").strip()]
                unique_used = {u.strip() for u in used if u.strip()}
                if len(unique_used) <= 1 and len(allowed_names) >= 2 and len(result.transcript) >= 2:
                    for idx, t in enumerate(result.transcript):
                        t.speaker = allowed_names[idx % len(allowed_names)]
                    yield _sse(
                        "trace",
                        {
                            "step": "speakers.relabel",
                            "reason": "model_returned_single_speaker",
                            "results": len(result.transcript),
                        },
                    )
            except Exception as e:
                yield _sse("trace", {"step": "speakers.relabel.error", "error": str(e)})

            for line in result.transcript:
                yield _sse("line", {"speaker": line.speaker, "dialogue": line.dialogue})
                await asyncio.sleep(0)

            if (result.await_user_question or "").strip():
                yield _sse("await_user", {"question": result.await_user_question})

            yield _sse("done", {"next_suggestions": result.next_suggestions})

        except Exception as e:
            logger.error(f"Failed to stream live podcast discussion: {e}")
            yield _sse("error", {"detail": f"Failed to stream live discussion: {str(e)}"})

    return StreamingResponse(_gen(), media_type="text/event-stream")
