"""
Podcast studio: pure-async multi-agent discussion engine.

Each speaker is an autonomous agent that:
  - Has its own LLM model (optionally different per speaker)
  - Autonomously decides when to use tools (web search, notebook search)
  - Addresses other panelists by name for natural conversational flow
  - Keeps internal tool reasoning private; only spoken words go to shared transcript

Turn order is NOT rigid round-robin:
  - If a speaker mentions another by name → that speaker goes next
  - Otherwise → whoever hasn't spoken in the longest time

Token streaming via asyncio.Queue — no LangGraph, no checkpointing.
"""
from __future__ import annotations

import asyncio
import os
import re
import traceback
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool
from loguru import logger

from open_notebook.domain.notebook import vector_search
from open_notebook.graphs.utils import provision_langchain_model
from open_notebook.utils.web_search import WebSearchError, tavily_search

# Podcast Studio configuration constants
# These can be overridden via environment variables for customization
CONSENSUS_INTERVAL = int(os.environ.get("PODCAST_STUDIO_CONSENSUS_INTERVAL", 15))  # speaker turns between consensus checks (increased for longer discussions)
MAX_TURNS = int(os.environ.get("PODCAST_STUDIO_MAX_TURNS", 80))  # hard safety cap to prevent infinite loops (increased)
MAX_TOOL_ITERATIONS = int(os.environ.get("PODCAST_STUDIO_MAX_TOOL_ITERATIONS", 3))  # max tool-call rounds per agent turn
MAX_TRANSCRIPT_LINES = int(os.environ.get("PODCAST_STUDIO_MAX_TRANSCRIPT_LINES", 14))  # recent lines fed into each speaker's prompt (context window management)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_questions(text: str) -> List[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in sentences if s.strip().endswith("?")]


def _extract_token(content: Any) -> str:
    """Pull a string token from LangChain chunk content (str or list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        )
    return ""


def _pick_next_speaker(
    response_text: str,
    speakers: List[Dict[str, Any]],
    current_idx: int,
    transcript: List[Dict[str, Any]],
) -> int:
    """Decide who speaks next based on conversation flow.

    1. If the current speaker mentioned another speaker by name → that speaker.
    2. Fallback: whoever hasn't spoken in the longest time.
    """
    text_lower = response_text.lower()

    # Check for name mentions (other speakers only)
    for i, s in enumerate(speakers):
        if i != current_idx and s["name"].lower() in text_lower:
            return i

    # Fallback: least-recently-spoken speaker
    last_spoke: Dict[str, int] = {}
    for turn_idx, entry in enumerate(transcript):
        last_spoke[entry["speaker"]] = turn_idx

    candidates = [
        (last_spoke.get(s["name"], -1), i)
        for i, s in enumerate(speakers)
        if i != current_idx
    ]
    candidates.sort()  # lowest (oldest) first
    return candidates[0][1] if candidates else (current_idx + 1) % len(speakers)


# ---------------------------------------------------------------------------
# Tool factories (closures that capture the queue for event emission)
# ---------------------------------------------------------------------------


def _make_tools(
    fact_check_mode: str, queue: asyncio.Queue
) -> Tuple[List[Any], Dict[str, Any]]:
    """Create the tool instances and a name→callable map."""
    tools: List[Any] = []
    tools_map: Dict[str, Any] = {}

    if fact_check_mode in ("internet", "both"):

        @tool
        async def web_search(query: str) -> str:
            """Search the internet for current facts, news, or data to verify a claim."""
            await queue.put(
                {"type": "fact_check", "status": "searching", "query": query}
            )
            try:
                results = await tavily_search(query, max_results=3)
                snippets = [
                    {
                        "url": r.get("url", ""),
                        "snippet": r.get("content", "")[:300],
                    }
                    for r in results[:3]
                    if isinstance(r, dict)
                ]
                output = "\n\n".join(
                    f"[{s['url']}]\n{s['snippet']}" for s in snippets
                )
                await queue.put(
                    {
                        "type": "fact_check",
                        "status": "done",
                        "query": query,
                        "results": snippets,
                        "source": "web",
                    }
                )
                return output or "No results found."
            except (WebSearchError, Exception) as exc:
                await queue.put(
                    {"type": "fact_check", "status": "done", "query": query}
                )
                return f"Search unavailable: {exc}"

        tools.append(web_search)
        tools_map["web_search"] = web_search

    if fact_check_mode in ("notebook", "both"):

        @tool
        async def notebook_search(query: str) -> str:
            """Search the research notebook for relevant content, sources, or notes."""
            await queue.put(
                {"type": "fact_check", "status": "searching", "query": query}
            )
            try:
                results = await vector_search(query, 5, True, True)
                output = "\n\n".join(
                    r.get("content", "")[:400]
                    for r in results[:5]
                    if isinstance(r, dict) and r.get("content")
                )
                await queue.put(
                    {
                        "type": "fact_check",
                        "status": "done",
                        "query": query,
                        "source": "notebook",
                    }
                )
                return output or "Nothing found in notebook."
            except Exception as exc:
                await queue.put(
                    {"type": "fact_check", "status": "done", "query": query}
                )
                return f"Notebook search failed: {exc}"

        tools.append(notebook_search)
        tools_map["notebook_search"] = notebook_search

    return tools, tools_map


# ---------------------------------------------------------------------------
# Evidence gathering (called before a turn when user sends an interrupt)
# ---------------------------------------------------------------------------


async def _gather_evidence(
    user_msg: str, fact_check_mode: str, queue: asyncio.Queue
) -> str:
    """Silently search web/notebook for evidence related to a user challenge."""
    parts: List[str] = []

    if fact_check_mode in ("internet", "both"):
        query = user_msg[:200]
        await queue.put({"type": "fact_check", "status": "searching", "query": query})
        try:
            results = await tavily_search(query, max_results=3)
            snippets = [
                {"url": r.get("url", ""), "snippet": r.get("content", "")[:300]}
                for r in results[:3]
                if isinstance(r, dict)
            ]
            text = "\n\n".join(f"[{s['url']}]\n{s['snippet']}" for s in snippets)
            await queue.put({
                "type": "fact_check", "status": "done", "query": query,
                "results": snippets, "source": "web",
            })
            if text:
                parts.append(f"[Web]\n{text}")
        except Exception as exc:
            logger.warning(f"[podcast_studio] web search failed: {exc}")
            await queue.put({"type": "fact_check", "status": "done", "query": query})

    if fact_check_mode in ("notebook", "both"):
        query = user_msg[:200]
        await queue.put({"type": "fact_check", "status": "searching", "query": query})
        try:
            results = await vector_search(query, 5, True, True)
            text = "\n\n".join(
                r.get("content", "")[:400]
                for r in results[:5]
                if isinstance(r, dict) and r.get("content")
            )
            await queue.put({
                "type": "fact_check", "status": "done", "query": query,
                "source": "notebook",
            })
            if text:
                parts.append(f"[Notebook]\n{text}")
        except Exception as exc:
            logger.warning(f"[podcast_studio] notebook search failed: {exc}")
            await queue.put({"type": "fact_check", "status": "done", "query": query})

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def _build_memory_context(
    transcript: List[Dict[str, Any]],
    current_speaker: str,
) -> Optional[str]:
    """Build context about earlier claims and potential contradictions.

    Analyzes the transcript to find:
    - Key claims made by each speaker
    - Potential contradictions to call out
    - Earlier points worth referencing
    """
    if len(transcript) < 4:  # Not enough history yet
        return None

    # Track claims per speaker (last 20 turns only)
    recent_turns = transcript[-20:]
    speaker_claims: Dict[str, List[str]] = {}

    for turn in recent_turns:
        speaker = turn.get("speaker", "")
        text = turn.get("text", "")
        if speaker != current_speaker and text:
            if speaker not in speaker_claims:
                speaker_claims[speaker] = []
            # Extract claim-like statements (assertions, opinions)
            if any(kw in text.lower() for kw in ["i think", "i believe", "should", "must", "wrong", "agree", "disagree", "the fact is", "clearly"]):
                speaker_claims[speaker].append(text[:150])

    # Build memory context
    context_parts = []

    # Add contradictions section if we find conflicting claims
    for speaker, claims in speaker_claims.items():
        if len(claims) >= 2:
            # Check for contradictory language
            contradictions = []
            for i, claim in enumerate(claims[:-1]):
                for later_claim in claims[i+1:]:
                    # Simple heuristic: look for contrasting language
                    if any(kw in later_claim.lower() for kw in ["but", "however", "actually", "wait", "no,", "that's wrong"]):
                        contradictions.append(f"  - {speaker} claimed '{claim[:100]}...' but later said '{later_claim[:100]}...'")

            if contradictions:
                context_parts.append("CONTRADICTIONS TO CALL OUT:\n" + "\n".join(contradictions[:3]))

    # Add "earlier points worth referencing" section
    if len(recent_turns) > 8:
        notable_points = []
        for turn in recent_turns[-8:-1]:  # Skip the very last turn
            text = turn.get("text", "")
            speaker = turn.get("speaker", "")
            if any(kw in text.lower() for kw in ["important", "key point", "critical", "essential", "remember this"]):
                notable_points.append(f"  - {speaker} said: '{text[:100]}...'")

        if notable_points:
            context_parts.append("EARLIER POINTS WORTH REFERENCING:\n" + "\n".join(notable_points[:3]))

    if context_parts:
        return "\n\n".join(context_parts)
    return None


def _build_system_prompt(
    speaker: Dict[str, Any],
    all_speakers: List[Dict[str, Any]],
    briefing: str,
    content: str,
    asked_questions: List[str],
    memory_context: Optional[str] = None,
) -> str:
    other_names = [s["name"] for s in all_speakers if s["name"] != speaker["name"]]
    panel_str = ", ".join(other_names) if other_names else "the other panelists"

    asked_block = ""
    if asked_questions:
        unique = list(dict.fromkeys(asked_questions))[-12:]
        asked_block = (
            "\nNever ask any of these (already covered):\n"
            + "\n".join(f"  - {q}" for q in unique)
            + "\n"
        )

    memory_block = ""
    if memory_context:
        memory_block = f"\n{memory_context}\n"

    return (
        f"You are {speaker['name']}, live on a podcast panel with {panel_str}.\n"
        f"Role: {speaker.get('role', 'panelist')}\n"
        f"Personality: {speaker.get('personality', 'thoughtful and direct')}\n"
        f"Background: {speaker.get('backstory', '')}\n\n"
        f"Topic: {briefing}\n\n"
        f"Reference material:\n{content[:1500]}\n"
        f"{asked_block}"
        f"{memory_block}"
        "HOW TO SPEAK (follow strictly):\n"
        f"- 1-3 sentences MAX. You are on a live mic.\n"
        f"- Address {panel_str} BY NAME when you disagree or want their take.\n"
        "- React to what was JUST said — quote or reference a specific phrase.\n"
        "- Show personality: be witty, skeptical, enthusiastic, or provocative based on your character.\n"
        "- Reference earlier points: 'Earlier you said X, now you're saying Y' or 'But 10 minutes ago you claimed...'\n"
        "- Show emotion: surprise ('Wait, what?'), doubt ('I'm not so sure...'), excitement, frustration.\n"
        "- Challenge directly: 'That doesn't add up' or 'But what about...?' or 'Hold on—'\n"
        "- Use natural speech patterns: 'Look,' 'Here's the thing,' 'Honestly,' 'Let's be real'\n"
        "- Change your mind if convinced: 'Okay, you've got a point there' or 'Fair enough, I'll concede that'\n"
        "- Call out contradictions: 'Wait, you just said the opposite!' or 'That contradicts what you said earlier'\n"
        "- Build on others' points: 'Adding to what X said...' or 'Exactly! And another thing...'\n"
        "- You can search the web or notebook if you need to verify a fact. Use tools sparingly.\n"
        "- Assert your view. Hedging is boring. Take a stance.\n"
        "- If you ask a question, name who you're asking.\n"
        "- NEVER summarize, recap, or use filler like 'great point.'\n"
        "- Output ONLY your spoken words. No labels, quotes, or (laughs)."
    )


def _build_human_prompt(
    transcript: List[Dict[str, Any]],
    speaker_name: str,
    user_msg: Optional[str],
    evidence: Optional[str] = None,
) -> str:
    recent = transcript[-MAX_TRANSCRIPT_LINES:]
    lines = [f"{t['speaker']}: {t['text']}" for t in recent]
    transcript_text = "\n".join(lines) if lines else "(opening of the show — introduce the topic)"

    extra = ""
    if user_msg:
        extra += f'\n\n[A listener just said: "{user_msg}" — address this directly.]'
    if evidence:
        extra += (
            f"\n\n[Research context — use to ground your answer, "
            f"no need to cite URLs]:\n{evidence}"
        )

    return f"Transcript:\n{transcript_text}{extra}\n\nYour turn, {speaker_name}:"


# ---------------------------------------------------------------------------
# Core agent turn — streams tokens + handles tool calls
# ---------------------------------------------------------------------------


async def _agent_turn(
    speaker: Dict[str, Any],
    model: Any,
    tools: List[Any],
    tools_map: Dict[str, Any],
    messages: List[Any],
    queue: asyncio.Queue,
) -> str:
    """Run one speaker's turn as an autonomous agent.

    Strategy:
      1. If tools are available, try streaming with tool support first.
         The agent can autonomously decide to search the web or notebook.
      2. If bind_tools fails (model doesn't support it) or the tool-augmented
         stream errors out, fall back to plain streaming.
    """
    speaker_name = speaker["name"]
    logger.debug(f"[podcast_studio] {speaker_name} starting turn, {len(messages)} messages")

    if tools:
        streamed_text = await _stream_with_tools(
            speaker_name, model, tools, tools_map, messages, queue
        )
        # _stream_with_tools returns "" on error — fall back to plain stream
        if streamed_text:
            return streamed_text
        logger.info(
            f"[podcast_studio] {speaker_name} tool stream returned empty, "
            f"retrying with plain stream"
        )

    return await _plain_stream(speaker_name, model, messages, queue)


async def _stream_with_tools(
    speaker_name: str,
    model: Any,
    tools: List[Any],
    tools_map: Dict[str, Any],
    messages: List[Any],
    queue: asyncio.Queue,
) -> str:
    """Stream a response, handling tool calls if the agent decides to use them."""
    try:
        model_with_tools = model.bind_tools(tools) if tools else model
    except Exception as exc:
        logger.warning(
            f"[podcast_studio] {speaker_name} bind_tools failed: {exc}, "
            f"falling back to plain stream"
        )
        return await _plain_stream(speaker_name, model, messages, queue)

    current_messages = list(messages)

    for iteration in range(MAX_TOOL_ITERATIONS):
        chunks: List[AIMessageChunk] = []
        streamed_text = ""

        try:
            async for chunk in model_with_tools.astream(current_messages):
                chunks.append(chunk)
                token = _extract_token(chunk.content)
                if token:
                    streamed_text += token
                    await queue.put(
                        {"type": "token", "speaker": speaker_name, "token": token}
                    )
        except Exception as exc:
            logger.error(
                f"[podcast_studio] {speaker_name} stream error (iter {iteration}): "
                f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            )
            return ""  # signal caller to retry without tools

        if not chunks:
            logger.warning(f"[podcast_studio] {speaker_name} got 0 chunks (iter {iteration})")
            return ""

        # Merge all chunks into one full AIMessage
        full_msg = chunks[0]
        for c in chunks[1:]:
            full_msg = full_msg + c  # type: ignore[operator]

        # Check for tool calls
        tool_calls = getattr(full_msg, "tool_calls", None) or []
        if not tool_calls:
            # No tools — we already streamed the spoken text
            logger.debug(
                f"[podcast_studio] {speaker_name} produced {len(streamed_text)} chars "
                f"(no tools, iter {iteration})"
            )
            return streamed_text.strip()

        # Agent wants to use tools — execute them
        logger.info(
            f"[podcast_studio] {speaker_name} invoking "
            f"{[tc.get('name') for tc in tool_calls]} (iter {iteration})"
        )
        current_messages.append(full_msg)

        for tc in tool_calls:
            tool_name = tc.get("name", "")
            tool_args = tc.get("args", {})
            tool_id = tc.get("id", "")

            tool_fn = tools_map.get(tool_name)
            if tool_fn:
                try:
                    result = await tool_fn.ainvoke(tool_args)
                except Exception as exc:
                    result = f"Tool error: {exc}"
            else:
                result = f"Unknown tool: {tool_name}"

            current_messages.append(
                ToolMessage(content=str(result), tool_call_id=tool_id)
            )

        # Reset — next iteration will produce the real response
        streamed_text = ""

    # Exhausted tool iterations — final plain stream
    logger.warning(f"[podcast_studio] {speaker_name} exhausted {MAX_TOOL_ITERATIONS} tool iterations")
    return await _plain_stream(speaker_name, model, current_messages, queue)


async def _plain_stream(
    speaker_name: str,
    model: Any,
    messages: List[Any],
    queue: asyncio.Queue,
) -> str:
    """Simple streaming call without tools. Last-resort fallback."""
    streamed_text = ""
    try:
        async for chunk in model.astream(messages):
            token = _extract_token(chunk.content)
            if token:
                streamed_text += token
                await queue.put(
                    {"type": "token", "speaker": speaker_name, "token": token}
                )
    except Exception as exc:
        logger.error(
            f"[podcast_studio] {speaker_name} plain stream failed: "
            f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        )
    if not streamed_text:
        logger.error(f"[podcast_studio] {speaker_name} produced ZERO text even without tools")
    return streamed_text.strip()


# ---------------------------------------------------------------------------
# Consensus check
# ---------------------------------------------------------------------------


async def _check_consensus(
    speakers: List[Dict[str, Any]],
    transcript: List[Dict[str, Any]],
    models: Dict[str, Any],
    queue: asyncio.Queue,
) -> bool:
    """Check if all speakers agree the topic is covered. Returns True if consensus."""
    await queue.put({"type": "consensus_check"})

    if len(transcript) < 4:
        # Not enough conversation yet - skip consensus check
        return False

    recent_text = "\n".join(
        f"{t['speaker']}: {t['text']}" for t in transcript[-20:]
    )

    # Use each speaker's own model for consensus voting
    votes: Dict[str, bool] = {}
    for speaker in speakers:
        speaker_model = models[speaker["name"]]
        msgs = [
            SystemMessage(
                content=f"You are {speaker['name']}. {speaker.get('personality', '')}"
            ),
            HumanMessage(
                content=(
                    f"Discussion:\n{recent_text}\n\n"
                    "Has this topic been thoroughly explored? "
                    "Reply ONLY: YES - [why] OR NO - [what's missing]"
                )
            ),
        ]
        try:
            resp = await speaker_model.ainvoke(msgs)
            text = _extract_token(resp.content).strip()
            votes[speaker["name"]] = text.upper().startswith("YES")
            logger.debug(f"[podcast_studio] {speaker['name']} consensus vote: {'YES' if votes[speaker['name']] else 'NO'}")
        except Exception as exc:
            logger.warning(
                f"[podcast_studio] consensus vote failed ({speaker['name']}): {exc}"
            )
            # Don't fail the whole check on one speaker's error - vote YES to continue
            votes[speaker["name"]] = True

    # Require majority consensus, not unanimous (more forgiving)
    yes_votes = sum(1 for v in votes.values() if v)
    majority_threshold = len(speakers) // 2 + 1

    if yes_votes >= majority_threshold:
        logger.info(f"[podcast_studio] consensus reached: {yes_votes}/{len(speakers)} speakers agree")
        # Generate closing summary
        summary_lines: List[str] = []
        for speaker in speakers:
            m = models[speaker["name"]]
            msgs = [
                SystemMessage(content=f"You are {speaker['name']}."),
                HumanMessage(
                    content=f"One sentence — your key takeaway:\n{recent_text}"
                ),
            ]
            try:
                resp = await m.ainvoke(msgs)
                summary_lines.append(f"{speaker['name']}: {_extract_token(resp.content).strip()}")
            except Exception:
                pass

        summary = " | ".join(summary_lines)
        await queue.put(
            {
                "type": "consensus_reached",
                "summary": summary,
            }
        )
        return True

    logger.info(f"[podcast_studio] no consensus yet: {yes_votes}/{len(speakers)} speakers agree, continuing discussion")
    return False
        ]
        try:
            resp = await m.ainvoke(msgs)
            summary_lines.append(
                f"{speaker['name']}: {_extract_token(resp.content).strip()}"
            )
        except Exception as exc:
            logger.warning(
                f"[podcast_studio] summary failed ({speaker['name']}): {exc}"
            )

    await queue.put(
        {"type": "consensus_reached", "summary": "\n".join(summary_lines)}
    )
    return True


# ---------------------------------------------------------------------------
# Main session runner
# ---------------------------------------------------------------------------


async def run_podcast_session(
    *,
    queue: asyncio.Queue,
    stop_event: asyncio.Event,
    interrupt_queue: asyncio.Queue,
    speakers: List[Dict[str, Any]],
    content: str,
    briefing: str,
    fact_check_mode: str,
) -> List[Dict[str, Any]]:
    """Drive a full podcast session.

    Puts event dicts into ``queue`` for the WS handler to forward to the browser.
    Reads user interrupts from ``interrupt_queue`` between turns.
    Returns the full transcript when consensus is reached, stop_event is set,
    or MAX_TURNS exceeded.
    """
    # --- Pre-provision one LLM per speaker at startup ---
    models: Dict[str, Any] = {}
    for s in speakers:
        try:
            m = await provision_langchain_model(
                briefing, s.get("model_id") or None, "chat", max_tokens=200
            )
            models[s["name"]] = m
            logger.info(
                f"[podcast_studio] provisioned model for {s['name']}: "
                f"{type(m).__name__} (model_id={s.get('model_id', 'default')})"
            )
        except Exception as exc:
            logger.error(
                f"[podcast_studio] model provision failed for {s['name']}: {exc}"
            )
            await queue.put(
                {
                    "type": "error",
                    "message": f"Could not load model for {s['name']}: {exc}",
                }
            )
            return []

    # --- Build tools (shared across all speakers, closures capture queue) ---
    tools, tools_map = _make_tools(fact_check_mode, queue)
    logger.info(
        f"[podcast_studio] session ready: {len(speakers)} speakers, "
        f"{len(tools)} tools, fact_check_mode={fact_check_mode}"
    )

    # --- Session state ---
    transcript: List[Dict[str, Any]] = []
    asked_questions: List[str] = []
    turn_count = 0
    last_consensus_at = 0
    current_idx = 0

    while not stop_event.is_set() and turn_count < MAX_TURNS:
        speaker = speakers[current_idx]
        speaker_name = speaker["name"]
        model = models[speaker_name]

        # --- Drain any pending user interrupt ---
        user_msg: Optional[str] = None
        while not interrupt_queue.empty():
            try:
                user_msg = interrupt_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        if user_msg:
            await queue.put({"type": "user_message", "text": user_msg})

        # --- Gather evidence for user interrupt (silently, before speaking) ---
        evidence: Optional[str] = None
        if user_msg and fact_check_mode != "none":
            evidence = await _gather_evidence(user_msg, fact_check_mode, queue)

        # --- Build agent messages ---
        memory_context = _build_memory_context(transcript, speaker_name)
        sys_prompt = _build_system_prompt(
            speaker, speakers, briefing, content, asked_questions, memory_context
        )
        human_prompt = _build_human_prompt(
            transcript, speaker_name, user_msg, evidence
        )
        agent_messages: List[Any] = [
            SystemMessage(content=sys_prompt),
            HumanMessage(content=human_prompt),
        ]

        # --- Signal turn start (typing indicator) ---
        await queue.put({"type": "turn_start", "speaker": speaker_name})

        # --- Run the agent turn ---
        response_text = await _agent_turn(
            speaker=speaker,
            model=model,
            tools=tools,
            tools_map=tools_map,
            messages=agent_messages,
            queue=queue,
        )

        if response_text:
            await queue.put({"type": "turn_end", "speaker": speaker_name})
            transcript.append({"speaker": speaker_name, "text": response_text})
            asked_questions.extend(_extract_questions(response_text))
            turn_count += 1

            # Pick next speaker based on conversation flow
            current_idx = _pick_next_speaker(
                response_text, speakers, current_idx, transcript
            )
        else:
            await queue.put({"type": "turn_cancel", "speaker": speaker_name})
            logger.warning(f"[podcast_studio] {speaker_name} produced empty response")
            # Skip to next speaker to avoid infinite loop
            current_idx = (current_idx + 1) % len(speakers)
            turn_count += 1

        # --- Consensus check every N turns ---
        turns_since_check = turn_count - last_consensus_at
        if turn_count > 0 and turns_since_check >= CONSENSUS_INTERVAL:
            last_consensus_at = turn_count
            reached = await _check_consensus(speakers, transcript, models, queue)
            if reached:
                return transcript

        # Brief pause between turns — avoids API rate limits and feels natural
        await asyncio.sleep(0.5)

    # Hard turn limit
    if turn_count >= MAX_TURNS:
        await queue.put(
            {
                "type": "consensus_reached",
                "summary": "Discussion concluded (turn limit reached).",
            }
        )

    return transcript
