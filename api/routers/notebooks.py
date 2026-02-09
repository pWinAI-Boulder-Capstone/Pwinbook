from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from ai_prompter import Prompter

from api.models import (
    NotebookCreate,
    NotebookQuickSummaryRequest,
    NotebookQuickSummaryResponse,
    NotebookResponse,
    NotebookUpdate,
    NoteResponse,
)
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.notebook import Note, Notebook, Source
from open_notebook.exceptions import InvalidInputError
from open_notebook.graphs.utils import provision_langchain_model
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.context_builder import ContextConfig, build_notebook_context

router = APIRouter()


@router.get("/notebooks", response_model=List[NotebookResponse])
async def get_notebooks(
    archived: Optional[bool] = Query(None, description="Filter by archived status"),
    order_by: str = Query("updated desc", description="Order by field and direction"),
):
    """Get all notebooks with optional filtering and ordering."""
    try:
        # Build the query with counts
        query = f"""
            SELECT *,
            count(<-reference.in) as source_count,
            count(<-artifact.in) as note_count
            FROM notebook
            ORDER BY {order_by}
        """

        result = await repo_query(query)

        # Filter by archived status if specified
        if archived is not None:
            result = [nb for nb in result if nb.get("archived") == archived]

        return [
            NotebookResponse(
                id=str(nb.get("id", "")),
                name=nb.get("name", ""),
                description=nb.get("description", ""),
                archived=nb.get("archived", False),
                created=str(nb.get("created", "")),
                updated=str(nb.get("updated", "")),
                source_count=nb.get("source_count", 0),
                note_count=nb.get("note_count", 0),
            )
            for nb in result
        ]
    except Exception as e:
        logger.error(f"Error fetching notebooks: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error fetching notebooks: {str(e)}"
        )


@router.post("/notebooks", response_model=NotebookResponse)
async def create_notebook(notebook: NotebookCreate):
    """Create a new notebook."""
    try:
        new_notebook = Notebook(
            name=notebook.name,
            description=notebook.description,
        )
        await new_notebook.save()

        return NotebookResponse(
            id=new_notebook.id or "",
            name=new_notebook.name,
            description=new_notebook.description,
            archived=new_notebook.archived or False,
            created=str(new_notebook.created),
            updated=str(new_notebook.updated),
            source_count=0,  # New notebook has no sources
            note_count=0,  # New notebook has no notes
        )
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating notebook: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error creating notebook: {str(e)}"
        )


@router.get("/notebooks/{notebook_id}", response_model=NotebookResponse)
async def get_notebook(notebook_id: str):
    """Get a specific notebook by ID."""
    try:
        # Query with counts for single notebook
        query = """
            SELECT *,
            count(<-reference.in) as source_count,
            count(<-artifact.in) as note_count
            FROM $notebook_id
        """
        result = await repo_query(query, {"notebook_id": ensure_record_id(notebook_id)})

        if not result:
            raise HTTPException(status_code=404, detail="Notebook not found")

        nb = result[0]
        return NotebookResponse(
            id=str(nb.get("id", "")),
            name=nb.get("name", ""),
            description=nb.get("description", ""),
            archived=nb.get("archived", False),
            created=str(nb.get("created", "")),
            updated=str(nb.get("updated", "")),
            source_count=nb.get("source_count", 0),
            note_count=nb.get("note_count", 0),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching notebook {notebook_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error fetching notebook: {str(e)}"
        )


@router.post(
    "/notebooks/{notebook_id}/quick-summary",
    response_model=NotebookQuickSummaryResponse,
)
async def quick_summary(notebook_id: str, request: NotebookQuickSummaryRequest):
    """Generate a quick summary for a notebook and save it as an AI note."""
    try:
        full_notebook_id = (
            notebook_id if notebook_id.startswith("notebook:") else f"notebook:{notebook_id}"
        )
        notebook = await Notebook.get(full_notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")

        sources = await notebook.get_sources()
        source_count = len(sources)
        if source_count <= 4:
            summary_max_tokens = 1200
            summary_mode = "standard length"
        elif source_count <= 10:
            summary_max_tokens = 2400
            summary_mode = "longer summary (more sources)"
        else:
            summary_max_tokens = 3600
            summary_mode = "detailed summary (many sources)"

        # If max_tokens is not provided, do not truncate context so all sources are included.
        context_max_tokens = request.max_tokens
        context_config = ContextConfig(
            include_notes=bool(request.include_notes),
            include_insights=bool(request.include_insights),
            max_tokens=context_max_tokens,
        )
        # Prefer full source content for summaries to avoid "metadata-only" outputs.
        if sources:
            context_config.sources = {
                source.id: "full content"
                for source in sources
                if source.id
            }
        # Avoid self-referential summaries by default: only include human notes.
        if request.include_notes:
            notes = await notebook.get_notes()
            context_config.notes = {
                note.id: "full content"
                for note in notes
                if note.id and note.note_type != "ai"
            }
        else:
            context_config.notes = {}

        context = await build_notebook_context(
            notebook_id=full_notebook_id,
            context_config=context_config,
            max_tokens=context_max_tokens,
        )

        prompt_data: Dict[str, Any] = {
            "notebook": {
                "id": notebook.id,
                "name": notebook.name,
                "description": notebook.description,
            },
            "context": context,
            "summary_mode": summary_mode,
        }
        system_prompt = Prompter(prompt_template="notebook_summary").render(
            data=prompt_data
        )

        model = await provision_langchain_model(
            system_prompt,
            request.model_override,
            "transformation",
            max_tokens=summary_max_tokens,
        )
        ai_message = await model.ainvoke(system_prompt)
        raw_content = (
            ai_message.content
            if isinstance(ai_message.content, str)
            else str(ai_message.content)
        )
        summary_content = clean_thinking_content(raw_content)
        if not summary_content or not summary_content.strip():
            raise HTTPException(
                status_code=400,
                detail="Summary model returned empty content. Check your model configuration.",
            )

        note_title = request.title or f"Quick Summary - {notebook.name}"
        note = Note(title=note_title, content=summary_content, note_type="ai")
        await note.save()
        await note.add_to_notebook(full_notebook_id)

        context_meta = context.get("metadata", {})
        context_meta["total_tokens"] = context.get("total_tokens", 0)
        context_meta["total_items"] = context.get("total_items", 0)
        context_meta["source_count"] = source_count
        context_meta["summary_mode"] = summary_mode
        context_meta["summary_max_tokens"] = summary_max_tokens
        context_meta["context_max_tokens"] = context_max_tokens

        return NotebookQuickSummaryResponse(
            note=NoteResponse(
                id=note.id or "",
                title=note.title,
                content=note.content,
                note_type=note.note_type,
                created=str(note.created),
                updated=str(note.updated),
            ),
            summary=summary_content,
            context_meta=context_meta,
        )
    except HTTPException:
        raise
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error generating quick summary for notebook {notebook_id}: {e}")
        logger.exception(e)
        raise HTTPException(
            status_code=500, detail=f"Failed to generate summary: {str(e)}"
        )


@router.put("/notebooks/{notebook_id}", response_model=NotebookResponse)
async def update_notebook(notebook_id: str, notebook_update: NotebookUpdate):
    """Update a notebook."""
    try:
        notebook = await Notebook.get(notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")

        # Update only provided fields
        if notebook_update.name is not None:
            notebook.name = notebook_update.name
        if notebook_update.description is not None:
            notebook.description = notebook_update.description
        if notebook_update.archived is not None:
            notebook.archived = notebook_update.archived

        await notebook.save()

        # Query with counts after update
        query = """
            SELECT *,
            count(<-reference.in) as source_count,
            count(<-artifact.in) as note_count
            FROM $notebook_id
        """
        result = await repo_query(query, {"notebook_id": ensure_record_id(notebook_id)})

        if result:
            nb = result[0]
            return NotebookResponse(
                id=str(nb.get("id", "")),
                name=nb.get("name", ""),
                description=nb.get("description", ""),
                archived=nb.get("archived", False),
                created=str(nb.get("created", "")),
                updated=str(nb.get("updated", "")),
                source_count=nb.get("source_count", 0),
                note_count=nb.get("note_count", 0),
            )

        # Fallback if query fails
        return NotebookResponse(
            id=notebook.id or "",
            name=notebook.name,
            description=notebook.description,
            archived=notebook.archived or False,
            created=str(notebook.created),
            updated=str(notebook.updated),
            source_count=0,
            note_count=0,
        )
    except HTTPException:
        raise
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating notebook {notebook_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error updating notebook: {str(e)}"
        )


@router.post("/notebooks/{notebook_id}/sources/{source_id}")
async def add_source_to_notebook(notebook_id: str, source_id: str):
    """Add an existing source to a notebook (create the reference)."""
    try:
        # Check if notebook exists
        notebook = await Notebook.get(notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")

        # Check if source exists
        source = await Source.get(source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")

        # Check if reference already exists (idempotency)
        existing_ref = await repo_query(
            "SELECT * FROM reference WHERE out = $source_id AND in = $notebook_id",
            {
                "notebook_id": ensure_record_id(notebook_id),
                "source_id": ensure_record_id(source_id),
            },
        )

        # If reference doesn't exist, create it
        if not existing_ref:
            await repo_query(
                "RELATE $source_id->reference->$notebook_id",
                {
                    "notebook_id": ensure_record_id(notebook_id),
                    "source_id": ensure_record_id(source_id),
                },
            )

        return {"message": "Source linked to notebook successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error linking source {source_id} to notebook {notebook_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=500, detail=f"Error linking source to notebook: {str(e)}"
        )


@router.delete("/notebooks/{notebook_id}/sources/{source_id}")
async def remove_source_from_notebook(notebook_id: str, source_id: str):
    """Remove a source from a notebook (delete the reference)."""
    try:
        # Check if notebook exists
        notebook = await Notebook.get(notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")

        # Delete the reference record linking source to notebook
        await repo_query(
            "DELETE FROM reference WHERE out = $notebook_id AND in = $source_id",
            {
                "notebook_id": ensure_record_id(notebook_id),
                "source_id": ensure_record_id(source_id),
            },
        )

        return {"message": "Source removed from notebook successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error removing source {source_id} from notebook {notebook_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=500, detail=f"Error removing source from notebook: {str(e)}"
        )


@router.delete("/notebooks/{notebook_id}")
async def delete_notebook(notebook_id: str):
    """Delete a notebook."""
    try:
        notebook = await Notebook.get(notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")

        await notebook.delete()

        return {"message": "Notebook deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting notebook {notebook_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error deleting notebook: {str(e)}"
        )
