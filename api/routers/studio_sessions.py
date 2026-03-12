"""
Studio Sessions API - List, view, delete, and export podcast studio sessions.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from loguru import logger

from open_notebook.domain.podcast import StudioSession

router = APIRouter()


@router.get("/studio-sessions", response_model=List[Dict[str, Any]])
async def list_studio_sessions(
    notebook_id: Optional[str] = Query(None, description="Filter by notebook ID"),
    limit: int = Query(50, ge=1, le=200, description="Max sessions to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    search: Optional[str] = Query(None, description="Search in briefing"),
):
    """List all studio sessions with optional filtering."""
    try:
        # Build query based on filters
        query_parts = ["SELECT * FROM studio_session"]
        where_clauses = []
        params: Dict[str, Any] = {"limit": limit, "offset": offset}

        if notebook_id:
            where_clauses.append("notebook_id = $notebook_id")
            params["notebook_id"] = notebook_id

        if search:
            where_clauses.append("briefing CONTAINS $search")
            params["search"] = search

        if where_clauses:
            query_parts.append("WHERE " + " AND ".join(where_clauses))

        query_parts.append("ORDER BY created_at DESC")
        query_parts.append("LIMIT $limit START $offset")

        query = " ".join(query_parts)

        from open_notebook.database.repository import repo_query
        results = await repo_query(query, params)

        # Return simplified session info (no full transcript)
        return [
            {
                "session_id": r.get("session_id"),
                "briefing": r.get("briefing"),
                "notebook_id": r.get("notebook_id"),
                "speakers": r.get("speakers", []),
                "turn_count": r.get("turn_count", 0),
                "status": r.get("status", "completed"),
                "created_at": r.get("created_at"),
                "fact_check_mode": r.get("fact_check_mode", "none"),
            }
            for r in results
        ]

    except Exception as e:
        logger.error(f"Failed to list studio sessions: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list sessions: {str(e)}")


@router.get("/studio-sessions/{session_id}")
async def get_studio_session(session_id: str):
    """Get full details of a specific studio session including transcript."""
    try:
        session = await StudioSession.get_by_session_id(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        return {
            "session_id": session.session_id,
            "briefing": session.briefing,
            "notebook_id": session.notebook_id,
            "speakers": session.speakers,
            "transcript": session.transcript,
            "turn_count": session.turn_count,
            "status": session.status,
            "created_at": session.created_at,
            "fact_check_mode": session.fact_check_mode,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get studio session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get session: {str(e)}")


@router.delete("/studio-sessions/{session_id}")
async def delete_studio_session(session_id: str):
    """Delete a studio session."""
    try:
        session = await StudioSession.get_by_session_id(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        await session.delete()
        return {"message": "Session deleted", "session_id": session_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete studio session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete session: {str(e)}")


@router.get("/studio-sessions/{session_id}/export")
async def export_studio_session(
    session_id: str,
    format: str = Query("txt", regex="^(txt|md|json)$", description="Export format"),
):
    """Export a studio session transcript in the specified format."""
    try:
        session = await StudioSession.get_by_session_id(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        if format == "json":
            # JSON export - full data
            import json
            data = {
                "session_id": session.session_id,
                "briefing": session.briefing,
                "speakers": session.speakers,
                "transcript": session.transcript,
                "turn_count": session.turn_count,
                "status": session.status,
                "created_at": session.created_at,
            }
            json_str = json.dumps(data, indent=2)
            return StreamingResponse(
                iter([json_str]),
                media_type="application/json",
                headers={"Content-Disposition": f'attachment; filename="session_{session_id}.json"'},
            )

        elif format == "md":
            # Markdown export - formatted
            md_lines = [
                f"# Podcast Studio Session\n\n",
                f"**Briefing:** {session.briefing}\n\n",
                f"**Speakers:** {', '.join(s['name'] for s in session.speakers)}\n\n",
                f"**Turns:** {session.turn_count} | **Status:** {session.status}\n\n",
                f"**Date:** {session.created_at}\n\n",
                "---\n\n",
                "## Transcript\n\n",
            ]

            # Group by speaker
            current_speaker = None
            for turn in session.transcript:
                speaker = turn.get("speaker", "Unknown")
                text = turn.get("text", "")
                if speaker != current_speaker:
                    md_lines.append(f"\n### {speaker}\n\n")
                    current_speaker = speaker
                md_lines.append(f"{text}\n\n")

            md_str = "".join(md_lines)
            return StreamingResponse(
                iter([md_str]),
                media_type="text/markdown",
                headers={"Content-Disposition": f'attachment; filename="session_{session_id}.md"'},
            )

        else:  # txt format
            # Plain text export - simple format
            txt_lines = [
                f"Podcast Studio Session\n",
                f"Briefing: {session.briefing}\n",
                f"Speakers: {', '.join(s['name'] for s in session.speakers)}\n",
                f"Turns: {session.turn_count}\n",
                f"Date: {session.created_at}\n",
                f"{'=' * 50}\n\n",
            ]

            for turn in session.transcript:
                speaker = turn.get("speaker", "Unknown")
                text = turn.get("text", "")
                txt_lines.append(f"{speaker}: {text}\n")

            txt_str = "".join(txt_lines)
            return StreamingResponse(
                iter([txt_str]),
                media_type="text/plain",
                headers={"Content-Disposition": f'attachment; filename="session_{session_id}.txt"'},
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to export studio session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to export session: {str(e)}")
