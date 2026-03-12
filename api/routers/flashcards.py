import asyncio
from typing import Any, Dict, List, Optional
from datetime import datetime
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

from open_notebook.database.repository import ensure_record_id
from open_notebook.domain.flashcard import Flashcard, FlashcardDeck, FlashcardSession
from open_notebook.domain.notebook import Notebook
from open_notebook.exceptions import NotFoundError
from open_notebook.graphs.flashcards import (
    check_notebook_content,
)
from api.flashcard_service import FlashcardService

router = APIRouter()

# ---------------------------------------------------------------------------
# Request/Response Models
# ---------------------------------------------------------------------------


class FlashcardDeckCreate(BaseModel):
    name: str = Field(..., description="Deck name")
    description: Optional[str] = Field(None, description="Deck description")
    notebook_id: Optional[str] = Field(None, description="Source notebook ID")


class FlashcardDeckUpdate(BaseModel):
    name: Optional[str] = Field(None, description="Deck name")
    description: Optional[str] = Field(None, description="Deck description")


class FlashcardGenerateRequest(BaseModel):
    notebook_id: str = Field(..., description="Notebook ID to generate from")
    num_cards: int = Field(
        default=10, ge=1, le=100, description="Number of cards to generate"
    )
    deck_name: Optional[str] = Field(None, description="Custom deck name")
    deck_description: Optional[str] = Field(None, description="Custom deck description")


class FlashcardCreate(BaseModel):
    deck_id: str = Field(..., description="Parent deck ID")
    question: str = Field(..., description="Question text")
    answer: str = Field(..., description="Answer text")
    hints: Optional[List[str]] = Field(
        default_factory=list, description="Optional hints"
    )
    difficulty: Optional[str] = Field(None, description="Difficulty level")
    tags: Optional[List[str]] = Field(default_factory=list, description="User tags")


class FlashcardUpdate(BaseModel):
    question: Optional[str] = Field(None, description="Question text")
    answer: Optional[str] = Field(None, description="Answer text")
    hints: Optional[List[str]] = Field(default_factory=list, description="Hints")
    difficulty: Optional[str] = Field(None, description="Difficulty level")
    tags: Optional[List[str]] = Field(default_factory=list, description="Tags")


class FlashcardSessionCreate(BaseModel):
    deck_id: str = Field(..., description="Deck ID to study")


class FlashcardAnswerSubmit(BaseModel):
    card_id: str = Field(..., description="Flashcard ID")
    user_answer: str = Field(..., description="User's answer")
    correct: bool = Field(..., description="Whether answer was correct")


class FlashcardCardResponse(BaseModel):
    id: str
    deck_id: str
    question: str
    answer: str
    hints: Optional[List[str]] = None
    difficulty: Optional[str] = None
    tags: Optional[List[str]] = None


class FlashcardDeckResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    notebook_id: Optional[str] = None
    auto_generated: bool
    card_count: Optional[int] = None
    cards_learned: Optional[int] = None
    cards_due: Optional[int] = None
    cards_new: Optional[int] = None
    job_status_override: Optional[str] = None
    created: Optional[str] = None
    updated: Optional[str] = None


class FlashcardSessionResponse(BaseModel):
    id: str
    deck_id: str
    user_answers: List[Dict[str, Any]]
    score: float
    started_at: str
    completed_at: Optional[str] = None
    total_cards: int
    correct_count: int


class SuccessResponse(BaseModel):
    success: bool
    message: str


class NotebookContentCheck(BaseModel):
    has_content: bool
    source_count: int
    note_count: int
    total_chars: int


# ---------------------------------------------------------------------------
# Deck Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/flashcards/notebook/{notebook_id}/check", response_model=NotebookContentCheck
)
async def check_notebook_for_generation(notebook_id: str):
    """Check if a notebook has content suitable for flashcard generation."""
    try:
        notebook_id = unquote(notebook_id)
        notebook = await Notebook.get(notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")

        result = await check_notebook_content(notebook_id)
        return NotebookContentCheck(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking notebook content: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error checking notebook: {str(e)}"
        )


@router.get("/flashcards/decks", response_model=List[FlashcardDeckResponse])
async def list_decks(notebook_id: Optional[str] = Query(None)):
    """List all flashcard decks, optionally filtered by notebook."""
    try:
        if notebook_id:
            # Verify notebook exists
            notebook = await Notebook.get(notebook_id)
            if not notebook:
                raise HTTPException(status_code=404, detail="Notebook not found")

            decks = await FlashcardDeck.get_by_notebook_id(notebook_id)
        else:
            decks = await FlashcardDeck.get_all()

        # Enrich with card counts
        result = []
        for deck in decks:
            card_count = await deck.get_card_count()
            result.append(
                FlashcardDeckResponse(
                    id=deck.id or "",
                    name=deck.name,
                    description=deck.description,
                    notebook_id=deck.notebook_id,
                    auto_generated=deck.auto_generated,
                    card_count=card_count,
                    cards_learned=deck.cards_learned,
                    cards_due=deck.cards_due,
                    cards_new=deck.cards_new,
                    job_status_override=deck.job_status_override,
                    created=str(deck.created) if deck.created else None,
                    updated=str(deck.updated) if deck.updated else None,
                )
            )
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing flashcard decks: {e}")
        raise HTTPException(status_code=500, detail=f"Error listing decks: {str(e)}")


@router.get("/flashcards/decks/{deck_id}", response_model=FlashcardDeckResponse)
async def get_deck(deck_id: str):
    """Get a specific deck with its cards."""
    try:
        # Decode URL-encoded deck_id (handle %3A -> :)
        deck_id = unquote(deck_id)
        result = await FlashcardDeck.get_with_stats(deck_id)
        if not result:
            raise HTTPException(status_code=404, detail="Deck not found")

        return FlashcardDeckResponse(
            id=result.get("id", ""),
            name=result.get("name", ""),
            description=result.get("description"),
            notebook_id=result.get("notebook_id"),
            auto_generated=result.get("auto_generated", False),
            card_count=result.get("total_cards", 0),
            cards_learned=result.get("cards_learned", 0),
            cards_due=result.get("cards_due", 0),
            cards_new=result.get("cards_new", 0),
            job_status_override=result.get("job_status_override"),
            created=str(result.get("created")) if result.get("created") else None,
            updated=str(result.get("updated")) if result.get("updated") else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting flashcard deck: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting deck: {str(e)}")


@router.post("/flashcards/decks", response_model=FlashcardDeckResponse)
async def create_deck(request: FlashcardDeckCreate):
    """Create a new flashcard deck."""
    try:
        # Verify notebook exists if provided
        if request.notebook_id:
            notebook = await Notebook.get(request.notebook_id)
            if not notebook:
                raise HTTPException(status_code=404, detail="Notebook not found")

        deck = FlashcardDeck(
            name=request.name,
            description=request.description,
            notebook_id=request.notebook_id,
            auto_generated=False,
        )
        await deck.save()

        # Auto-generate flashcards if notebook has content
        if request.notebook_id and deck.id:
            try:
                sources = await notebook.get_sources()
                notes = await notebook.get_notes()
                if sources or notes:
                    await FlashcardService.submit_generation_job(
                        deck_id=deck.id,
                        notebook_id=request.notebook_id,
                        num_cards=4,
                    )
                    logger.info(
                        f"Auto-submitted generation job for new deck {deck.id}"
                    )
            except Exception as gen_err:
                logger.warning(f"Auto-generation failed for deck {deck.id}: {gen_err}")

        card_count = await deck.get_card_count()

        return FlashcardDeckResponse(
            id=deck.id or "",
            name=deck.name,
            description=deck.description,
            notebook_id=deck.notebook_id,
            auto_generated=deck.auto_generated,
            card_count=card_count,
            cards_learned=deck.cards_learned,
            cards_due=deck.cards_due,
            cards_new=deck.cards_new,
            job_status_override=deck.job_status_override,
            created=str(deck.created) if deck.created else None,
            updated=str(deck.updated) if deck.updated else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating flashcard deck: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating deck: {str(e)}")


@router.put("/flashcards/decks/{deck_id}", response_model=FlashcardDeckResponse)
async def update_deck(deck_id: str, request: FlashcardDeckUpdate):
    """Update a flashcard deck."""
    try:
        # Decode URL-encoded deck_id (handle %3A -> :)
        deck_id = unquote(deck_id)
        deck = await FlashcardDeck.get(deck_id)
        if not deck:
            raise HTTPException(status_code=404, detail="Deck not found")

        update_data = request.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(deck, key, value)

        await deck.save()

        card_count = await deck.get_card_count()

        return FlashcardDeckResponse(
            id=deck.id or "",
            name=deck.name,
            description=deck.description,
            notebook_id=deck.notebook_id,
            auto_generated=deck.auto_generated,
            card_count=card_count,
            cards_learned=deck.cards_learned,
            cards_due=deck.cards_due,
            cards_new=deck.cards_new,
            job_status_override=deck.job_status_override,
            created=str(deck.created) if deck.created else None,
            updated=str(deck.updated) if deck.updated else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating flashcard deck: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating deck: {str(e)}")


@router.delete("/flashcards/decks/{deck_id}", response_model=SuccessResponse)
async def delete_deck(deck_id: str):
    """Delete a flashcard deck and all its cards."""
    try:
        # Decode URL-encoded deck_id (handle %3A -> :)
        deck_id = unquote(deck_id)
        deck = await FlashcardDeck.get(deck_id)
        if not deck:
            raise HTTPException(status_code=404, detail="Deck not found")

        # Delete all cards first
        await deck.delete_cards()

        # Then delete the deck
        await deck.delete()

        return SuccessResponse(success=True, message="Deck deleted successfully")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting flashcard deck: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting deck: {str(e)}")


@router.post("/flashcards/decks/{deck_id}/generate")
async def generate_flashcards(deck_id: str, request: FlashcardGenerateRequest):
    """AI-generate flashcards from notebook content for an existing deck.

    Returns immediately with job status - frontend should poll /jobs/{deck_id} for completion.
    """
    try:
        # Decode URL-encoded deck_id (handle %3A -> :)
        deck_id = unquote(deck_id)

        # Verify deck exists
        deck = await FlashcardDeck.get(deck_id)
        if not deck:
            raise HTTPException(status_code=404, detail="Deck not found")

        # Verify notebook exists
        notebook = await Notebook.get(request.notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")

        # Check notebook has content (sources or notes)
        try:
            sources = await notebook.get_sources()
            notes = await notebook.get_notes()
            has_content = sources or notes
        except Exception:
            has_content = False

        if not has_content:
            raise HTTPException(
                status_code=400,
                detail="Notebook is empty. Add sources or notes to generate flashcards.",
            )

        # Submit background job
        job_id = await FlashcardService.submit_generation_job(
            deck_id=deck_id,
            notebook_id=request.notebook_id,
            num_cards=request.num_cards,
        )

        return {
            "job_id": job_id,
            "status": "running",
            "message": "Flashcard generation started in background",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting flashcard generation job: {e}")
        raise HTTPException(status_code=500, detail=f"Error submitting job: {str(e)}")


@router.get("/flashcards/jobs/{job_id}")
async def get_generation_job_status(job_id: str):
    """Get the status of a flashcard generation job."""
    try:
        job_id = unquote(job_id)
        status = await FlashcardService.get_job_status(job_id)
        return status
    except Exception as e:
        logger.error(f"Error getting job status: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error getting job status: {str(e)}"
        )


@router.get(
    "/flashcards/decks/{deck_id}/cards", response_model=List[FlashcardCardResponse]
)
async def get_deck_cards(deck_id: str):
    """Get all cards in a deck."""
    try:
        # Decode URL-encoded deck_id (handle %3A -> :)
        deck_id = unquote(deck_id)
        deck = await FlashcardDeck.get(deck_id)
        if not deck:
            raise HTTPException(status_code=404, detail="Deck not found")

        cards = await deck.get_cards()

        return [
            FlashcardCardResponse(
                id=card.id or "",
                deck_id=card.deck_id,
                question=card.question,
                answer=card.answer,
                hints=card.hints,
                difficulty=card.difficulty,
                tags=card.tags,
            )
            for card in cards
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting deck cards: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting cards: {str(e)}")


@router.post("/flashcards/decks/{deck_id}/cards", response_model=FlashcardCardResponse)
async def create_card(deck_id: str, request: FlashcardCreate):
    """Add a new card to a deck."""
    try:
        # Decode URL-encoded deck_id (handle %3A -> :)
        deck_id = unquote(deck_id)
        deck = await FlashcardDeck.get(deck_id)
        if not deck:
            raise HTTPException(status_code=404, detail="Deck not found")

        card = Flashcard(
            deck_id=deck_id,
            question=request.question,
            answer=request.answer,
            hints=request.hints,
            difficulty=request.difficulty,
            tags=request.tags,
        )
        await card.save()

        return FlashcardCardResponse(
            id=card.id or "",
            deck_id=card.deck_id,
            question=card.question,
            answer=card.answer,
            hints=card.hints,
            difficulty=card.difficulty,
            tags=card.tags,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating flashcard: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating card: {str(e)}")


# ---------------------------------------------------------------------------
# Session Endpoints
# ---------------------------------------------------------------------------


@router.post("/flashcards/sessions", response_model=FlashcardSessionResponse)
async def create_session(request: FlashcardSessionCreate):
    """Start a new flashcard study session."""
    try:
        # Decode URL-encoded deck_id (handle %3A -> :)
        deck_id = unquote(request.deck_id)

        # Verify deck exists
        deck = await FlashcardDeck.get(deck_id)
        if not deck:
            raise HTTPException(status_code=404, detail="Deck not found")

        session = FlashcardSession(
            deck_id=deck_id,
            user_answers=[],
            score=0.0,
            started_at=datetime.now().isoformat(),
            completed_at=None,
            total_cards=0,
            correct_count=0,
        )
        await session.save()

        return FlashcardSessionResponse(
            id=session.id or "",
            deck_id=session.deck_id,
            user_answers=session.user_answers,
            score=session.score,
            started_at=session.started_at,
            completed_at=session.completed_at,
            total_cards=session.total_cards,
            correct_count=session.correct_count,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating flashcard session: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating session: {str(e)}")


@router.get(
    "/flashcards/sessions/{session_id}", response_model=FlashcardSessionResponse
)
async def get_session(session_id: str):
    """Get a specific session."""
    try:
        session = await FlashcardSession.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        return FlashcardSessionResponse(
            id=session.id or "",
            deck_id=session.deck_id,
            user_answers=session.user_answers,
            score=session.score,
            started_at=session.started_at,
            completed_at=session.completed_at,
            total_cards=session.total_cards,
            correct_count=session.correct_count,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting flashcard session: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting session: {str(e)}")


@router.post(
    "/flashcards/sessions/{session_id}/answer", response_model=FlashcardSessionResponse
)
async def submit_answer(session_id: str, request: FlashcardAnswerSubmit):
    """Submit an answer for a card in the session."""
    try:
        session = await FlashcardSession.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Add the answer
        session.add_answer(
            card_id=request.card_id,
            user_answer=request.user_answer,
            correct=request.correct,
        )
        await session.save()

        return FlashcardSessionResponse(
            id=session.id or "",
            deck_id=session.deck_id,
            user_answers=session.user_answers,
            score=session.score,
            started_at=session.started_at,
            completed_at=session.completed_at,
            total_cards=session.total_cards,
            correct_count=session.correct_count,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting answer: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error submitting answer: {str(e)}"
        )


@router.post(
    "/flashcards/sessions/{session_id}/complete",
    response_model=FlashcardSessionResponse,
)
async def complete_session(session_id: str):
    """Mark a session as completed and update card SRS + deck stats."""
    try:
        session = await FlashcardSession.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        session.complete()
        await session.save()

        # Update SRS for each card answered in the session
        for answer in session.user_answers:
            card_id = answer.get("card_id")
            correct = answer.get("correct", False)
            if not card_id:
                continue
            try:
                card = await Flashcard.get(card_id)
                if card:
                    quality = 4 if correct else 1
                    await card.save_with_srs_update(quality)
            except Exception as card_err:
                logger.warning(f"Failed to update SRS for card {card_id}: {card_err}")

        # Update deck stats
        try:
            deck = await FlashcardDeck.get(session.deck_id)
            if deck:
                await deck.update_stats()
        except Exception as stats_err:
            logger.warning(f"Failed to update deck stats: {stats_err}")

        return FlashcardSessionResponse(
            id=session.id or "",
            deck_id=session.deck_id,
            user_answers=session.user_answers,
            score=session.score,
            started_at=session.started_at,
            completed_at=session.completed_at,
            total_cards=session.total_cards,
            correct_count=session.correct_count,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error completing session: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error completing session: {str(e)}"
        )


@router.get(
    "/flashcards/sessions/deck/{deck_id}", response_model=List[FlashcardSessionResponse]
)
async def get_deck_sessions(deck_id: str, limit: int = Query(default=5, ge=1, le=20)):
    """Get recent sessions for a deck."""
    try:
        # Decode URL-encoded deck_id (handle %3A -> :)
        deck_id = unquote(deck_id)
        deck = await FlashcardDeck.get(deck_id)
        if not deck:
            raise HTTPException(status_code=404, detail="Deck not found")

        sessions = await FlashcardSession.get_recent_sessions(deck_id, limit)

        return [
            FlashcardSessionResponse(
                id=session.id or "",
                deck_id=session.deck_id,
                user_answers=session.user_answers,
                score=session.score,
                started_at=session.started_at,
                completed_at=session.completed_at,
                total_cards=session.total_cards,
                correct_count=session.correct_count,
            )
            for session in sessions
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting deck sessions: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting sessions: {str(e)}")


@router.get("/flashcards/decks/{deck_id}/stats")
async def get_deck_stats(deck_id: str):
    """Get aggregate statistics for a deck's sessions."""
    try:
        # Decode URL-encoded deck_id (handle %3A -> :)
        deck_id = unquote(deck_id)
        deck = await FlashcardDeck.get(deck_id)
        if not deck:
            raise HTTPException(status_code=404, detail="Deck not found")

        stats = await FlashcardSession.get_stats_for_deck(deck_id)

        return stats or {
            "total_sessions": 0,
            "avg_score": 0,
            "best_score": 0,
            "worst_score": 0,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting deck stats: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting stats: {str(e)}")
