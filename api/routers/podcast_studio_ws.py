"""
WebSocket endpoint for the live podcast studio.

Protocol (JSON messages):
  Client -> Server:
    {"type": "start", "speakers": [...], "notebook_id": "...", "briefing": "...",
     "fact_check_mode": "both", "model_override": null}
    {"type": "interrupt", "message": "..."}
    {"type": "stop"}

  Server -> Client:
    {"type": "connected", "session_id": "..."}
    {"type": "turn_start", "speaker": "Alex"}
    {"type": "token", "speaker": "Alex", "token": "the"}
    {"type": "turn_end", "speaker": "Alex"}
    {"type": "turn_cancel", "speaker": "Alex"}
    {"type": "user_message", "text": "..."}
    {"type": "fact_check", "status": "searching", "query": "..."}
    {"type": "fact_check", "status": "done", "query": "...", "results": [...]}
    {"type": "consensus_check"}
    {"type": "consensus_reached", "summary": "..."}
    {"type": "error", "message": "..."}

Authentication:
  When OPEN_NOTEBOOK_PASSWORD is set, clients must pass ``?token=<password>``
  as a query parameter on the WebSocket URL.  Starlette's BaseHTTPMiddleware
  does not intercept WebSocket upgrades, so we validate here explicitly.

Architecture:
  - receiver_task: reads WS messages, puts user interrupts into a queue
  - runner_task: calls run_podcast_session() which puts events into a queue
  - drain_task: forwards events from the queue to the WebSocket
  - On session end the transcript is persisted to SurrealDB (StudioSession).
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from loguru import logger

from open_notebook.domain.notebook import Note, Notebook, Source
from open_notebook.domain.podcast import StudioSession
from open_notebook.graphs.podcast_studio import run_podcast_session

router = APIRouter()

MAX_CHARS_TOTAL = 40_000
MAX_CHARS_PER_ITEM = 4_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _build_notebook_content(notebook_id: str) -> str:
    """Fetch text content from a notebook's sources and notes."""
    if not notebook_id:
        return ""
    try:
        notebook = await Notebook.get(notebook_id)
        if not notebook:
            return ""

        parts: List[str] = [
            f"Notebook: {notebook.name}\nDescription: {notebook.description}\n"
        ]
        total = len(parts[0])

        try:
            source_stubs = await notebook.get_sources()
        except Exception as exc:
            logger.warning(f"[podcast_studio_ws] failed to load sources: {exc}")
            source_stubs = []

        for stub in source_stubs[:20]:
            if total >= MAX_CHARS_TOTAL:
                break
            try:
                src = await Source.get(str(stub.id))
                if not src:
                    continue
                title = getattr(src, "title", None) or "(untitled source)"
                text = (getattr(src, "full_text", None) or "")[:MAX_CHARS_PER_ITEM]
                block = f"\n=== SOURCE: {title} ===\n{text}\n"
                parts.append(block)
                total += len(block)
            except Exception as exc:
                logger.warning(
                    f"[podcast_studio_ws] failed to load source {stub.id}: {exc}"
                )

        try:
            note_stubs = await notebook.get_notes()
        except Exception as exc:
            logger.warning(f"[podcast_studio_ws] failed to load notes: {exc}")
            note_stubs = []

        for stub in note_stubs[:20]:
            if total >= MAX_CHARS_TOTAL:
                break
            try:
                note = await Note.get(str(stub.id))
                if not note:
                    continue
                text = (getattr(note, "content", None) or "")[:MAX_CHARS_PER_ITEM]
                block = f"\n=== NOTE ===\n{text}\n"
                parts.append(block)
                total += len(block)
            except Exception as exc:
                logger.warning(
                    f"[podcast_studio_ws] failed to load note {stub.id}: {exc}"
                )

        return "".join(parts).strip()
    except Exception as exc:
        logger.warning(
            f"[podcast_studio_ws] failed to load notebook {notebook_id}: {exc}"
        )
        return ""


async def _safe_send(ws: WebSocket, payload: Dict[str, Any]) -> bool:
    """Send a JSON message; return False if the connection is closed."""
    try:
        await ws.send_json(payload)
        return True
    except Exception as e:
        logger.debug(f"[podcast_studio_ws] send failed: {e}")
        return False


async def _persist_session(
    session_id: str,
    briefing: str,
    notebook_id: str,
    speakers: List[Dict[str, Any]],
    transcript: List[Dict[str, Any]],
    fact_check_mode: str,
    end_status: str,
) -> None:
    """Save a completed studio session to the database."""
    try:
        session = StudioSession(
            session_id=session_id,
            briefing=briefing,
            notebook_id=notebook_id or None,
            speakers=speakers,
            transcript=transcript,
            fact_check_mode=fact_check_mode,
            turn_count=len(transcript),
            status=end_status,
        )
        await session.save()
        logger.info(
            f"[podcast_studio_ws] persisted session {session_id} "
            f"({len(transcript)} turns, status={end_status})"
        )
    except Exception as exc:
        logger.warning(f"[podcast_studio_ws] failed to persist session: {exc}")


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@router.websocket("/ws/podcast-studio")
async def podcast_studio_ws(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    trace: Optional[str] = Query(None),
):
    trace_id = trace or "none"
    host = websocket.headers.get("host", "unknown")
    origin = websocket.headers.get("origin", "unknown")
    forwarded_for = websocket.headers.get("x-forwarded-for", "unknown")
    user_agent = websocket.headers.get("user-agent", "unknown")
    client_ip = websocket.client.host if websocket.client else "unknown"

    logger.info(
        "[podcast_studio_ws] connect trace_id={} client_ip={} host={} origin={} xff={} ua={}",
        trace_id,
        client_ip,
        host,
        origin,
        forwarded_for,
        user_agent,
    )

    # --- Fix 5: WebSocket authentication ---
    # BaseHTTPMiddleware does not intercept WebSocket upgrades, so we
    # validate the password here before accepting the connection.
    required_password = os.environ.get("OPEN_NOTEBOOK_PASSWORD")
    if required_password:
        if token != required_password:
            logger.warning(
                "[podcast_studio_ws] auth rejected trace_id={} reason=missing_or_invalid_token",
                trace_id,
            )
            # Reject before accepting — sends HTTP 403 to the upgrade request
            await websocket.close(code=4003, reason="Authentication required")
            return

    await websocket.accept()

    session_id = str(uuid4())
    logger.info(
        "[podcast_studio_ws] accepted trace_id={} session_id={}",
        trace_id,
        session_id,
    )
    await _safe_send(websocket, {"type": "connected", "session_id": session_id})

    # Read the "start" message before spawning tasks
    try:
        start_msg = await asyncio.wait_for(websocket.receive_json(), timeout=30)
    except asyncio.TimeoutError:
        logger.warning(
            "[podcast_studio_ws] timeout waiting start message trace_id={} session_id={}",
            trace_id,
            session_id,
        )
        await _safe_send(
            websocket,
            {"type": "error", "message": "Timed out waiting for start message."},
        )
        await websocket.close()
        return
    except Exception as exc:
        logger.warning(
            "[podcast_studio_ws] failed before start trace_id={} session_id={} error={}",
            trace_id,
            session_id,
            exc,
        )
        await _safe_send(websocket, {"type": "error", "message": str(exc)})
        await websocket.close()
        return

    if start_msg.get("type") != "start":
        logger.warning(
            "[podcast_studio_ws] invalid first message trace_id={} session_id={} type={}",
            trace_id,
            session_id,
            start_msg.get("type"),
        )
        await _safe_send(
            websocket,
            {"type": "error", "message": "Expected a 'start' message."},
        )
        await websocket.close()
        return

    # Coordination primitives
    interrupt_queue: asyncio.Queue[str] = asyncio.Queue()
    stop_event = asyncio.Event()

    # -------------------------------------------------------------------
    # Receiver: reads WS messages from the client
    # -------------------------------------------------------------------
    async def receiver_task() -> None:
        try:
            while not stop_event.is_set():
                data = await websocket.receive_json()
                msg_type = data.get("type", "")
                if msg_type == "interrupt":
                    text = (data.get("message") or "").strip()
                    if text:
                        await interrupt_queue.put(text)
                elif msg_type == "stop":
                    stop_event.set()
                    break
        except WebSocketDisconnect:
            stop_event.set()
        except Exception as exc:
            logger.debug(f"[podcast_studio_ws] receiver ended: {exc}")
            stop_event.set()

    # -------------------------------------------------------------------
    # Runner: drives the podcast session and drains the event queue
    # -------------------------------------------------------------------
    async def runner_task() -> None:
        # Parse start message
        speakers: List[Dict[str, Any]] = start_msg.get("speakers") or []
        notebook_id: str = start_msg.get("notebook_id") or ""
        briefing: str = (
            start_msg.get("briefing")
            or start_msg.get("episode_name")
            or "Open discussion"
        ).strip()
        fact_check_mode: str = start_msg.get("fact_check_mode") or "both"

        if len(speakers) < 1:
            await _safe_send(
                websocket,
                {"type": "error", "message": "At least 1 speaker required."},
            )
            stop_event.set()
            return

        # Normalise speakers
        for i, s in enumerate(speakers):
            s.setdefault("name", f"Speaker {i + 1}")
            s.setdefault("role", "panelist")
            s.setdefault("personality", "thoughtful")
            s.setdefault("backstory", s.get("role", ""))

        content = await _build_notebook_content(notebook_id)

        # Event queue: session puts events here, drain forwards to WebSocket
        event_queue: asyncio.Queue = asyncio.Queue()
        session_done = asyncio.Event()
        # Mutable container for the transcript returned by run_podcast_session
        session_transcript: List[Dict[str, Any]] = []
        session_status = "completed"

        async def _run_session() -> None:
            nonlocal session_status
            try:
                transcript = await run_podcast_session(
                    queue=event_queue,
                    stop_event=stop_event,
                    interrupt_queue=interrupt_queue,
                    speakers=speakers,
                    content=content,
                    briefing=briefing,
                    fact_check_mode=fact_check_mode,
                )
                session_transcript.extend(transcript or [])
                # Determine how the session ended
                if stop_event.is_set():
                    session_status = "stopped"
            except Exception as exc:
                session_status = "error"
                logger.error(f"[podcast_studio_ws] session error: {exc}")
                try:
                    await event_queue.put(
                        {"type": "error", "message": str(exc)}
                    )
                except Exception as send_err:
                    logger.debug(f"[podcast_studio_ws] failed to send error to queue: {send_err}")
            finally:
                session_done.set()

        async def _drain_queue() -> None:
            while not (session_done.is_set() and event_queue.empty()):
                try:
                    item = await asyncio.wait_for(
                        event_queue.get(), timeout=0.05
                    )
                except asyncio.TimeoutError:
                    continue

                itype = item.get("type")

                if itype == "turn_start":
                    await _safe_send(
                        websocket,
                        {"type": "turn_start", "speaker": item["speaker"]},
                    )
                elif itype == "token":
                    await _safe_send(
                        websocket,
                        {
                            "type": "token",
                            "speaker": item["speaker"],
                            "token": item["token"],
                        },
                    )
                elif itype == "turn_end":
                    await _safe_send(
                        websocket,
                        {"type": "turn_end", "speaker": item["speaker"]},
                    )
                elif itype == "turn_cancel":
                    await _safe_send(
                        websocket,
                        {"type": "turn_cancel", "speaker": item["speaker"]},
                    )
                elif itype == "user_message":
                    await _safe_send(
                        websocket,
                        {"type": "user_message", "text": item["text"]},
                    )
                elif itype == "fact_check":
                    payload: Dict[str, Any] = {
                        "type": "fact_check",
                        "status": item["status"],
                    }
                    for key in ("query", "results", "source"):
                        if item.get(key):
                            payload[key] = item[key]
                    await _safe_send(websocket, payload)
                elif itype == "consensus_check":
                    await _safe_send(websocket, {"type": "consensus_check"})
                elif itype == "consensus_reached":
                    await _safe_send(
                        websocket,
                        {
                            "type": "consensus_reached",
                            "summary": item.get("summary", ""),
                        },
                    )
                elif itype == "error":
                    await _safe_send(
                        websocket,
                        {
                            "type": "error",
                            "message": item.get("message", "Unknown error"),
                        },
                    )

        await asyncio.gather(_run_session(), _drain_queue())

        # --- Persist the session transcript ---
        # Always persist, even if session had errors (partial data is better than none)
        try:
            await _persist_session(
                session_id=session_id,
                briefing=briefing,
                notebook_id=notebook_id,
                speakers=speakers,
                transcript=session_transcript,
                fact_check_mode=fact_check_mode,
                end_status=session_status,
            )
        except Exception as persist_err:
            logger.error(f"[podcast_studio_ws] failed to persist session {session_id}: {persist_err}")
            # Don't re-raise - session already completed, just log the failure

        stop_event.set()

    # -------------------------------------------------------------------
    # Run receiver and runner concurrently
    # -------------------------------------------------------------------
    # Fix 2: Instead of asyncio.wait(FIRST_COMPLETED) which cancels the
    # runner mid-turn when the receiver stops, we let the runner drive
    # lifecycle.  The receiver sets stop_event when the user sends "stop"
    # or disconnects; the runner's main loop checks stop_event between
    # turns and exits cleanly.
    recv = asyncio.create_task(receiver_task())
    run = asyncio.create_task(runner_task())

    try:
        # Wait for the runner to finish — it will exit once stop_event is
        # set (by receiver) or the session concludes naturally.
        await run
    except Exception as exc:
        logger.error(f"[podcast_studio_ws] runner error: {exc}")
    finally:
        logger.info(
            "[podcast_studio_ws] closing trace_id={} session_id={} stop_event={} recv_done={} run_done={}",
            trace_id,
            session_id,
            stop_event.is_set(),
            recv.done(),
            run.done(),
        )
        stop_event.set()

        # Cancel the receiver if it is still waiting for WS messages
        if not recv.done():
            recv.cancel()
            try:
                await recv
            except (asyncio.CancelledError, Exception):
                pass

        # If the runner had an unhandled exception, log it
        if not run.done():
            run.cancel()
            try:
                await run
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.debug(f"[podcast_studio_ws] runner cleanup error: {e}")

        try:
            await websocket.close()
        except Exception as e:
            logger.debug(f"[podcast_studio_ws] websocket close error: {e}")
