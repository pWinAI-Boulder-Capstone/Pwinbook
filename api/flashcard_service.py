import asyncio
from typing import Any, Dict, Optional

from loguru import logger

from open_notebook.domain.flashcard import FlashcardDeck
from open_notebook.graphs.flashcards import run_flashcard_generation


_running_jobs: Dict[str, asyncio.Task] = {}


async def _run_generation_background(
    deck_id: str,
    notebook_id: str,
    num_cards: int,
) -> None:
    """Run flashcard generation in background and update deck when done."""
    try:
        logger.info(
            f"[flashcard_job] Starting background generation for deck {deck_id}"
        )

        result = await run_flashcard_generation(
            notebook_id=notebook_id,
            num_cards=num_cards,
            save_to_db=True,
            deck_id=deck_id,
        )

        # Update deck with completion status
        try:
            deck = await FlashcardDeck.get(deck_id)
            if deck:
                errors = result.get("errors", [])
                if errors:
                    deck.job_status_override = "failed"
                    deck.job_error = "; ".join(errors)
                else:
                    deck.job_status_override = "completed"
                await deck.save()
                logger.info(f"[flashcard_job] Completed generation for deck {deck_id}")
        except Exception as save_err:
            logger.error(f"[flashcard_job] Failed to update deck status: {save_err}")

    except Exception as e:
        logger.error(f"[flashcard_job] Generation failed for deck {deck_id}: {e}")
        logger.exception(e)  # Full traceback
        try:
            deck = await FlashcardDeck.get(deck_id)
            if deck:
                deck.job_status_override = "failed"
                deck.job_error = str(e)
                await deck.save()
        except Exception as save_err:
            logger.error(f"[flashcard_job] Failed to mark deck as failed: {save_err}")
            logger.exception(save_err)
    finally:
        _running_jobs.pop(deck_id, None)


class FlashcardService:
    """Service layer for flashcard operations with background job support"""

    @staticmethod
    async def submit_generation_job(
        deck_id: str,
        notebook_id: str,
        num_cards: int = 20,
    ) -> str:
        """Submit a flashcard generation job to run in background.

        Returns the deck_id as the job_id so frontend can poll for status.
        """
        # Update deck to mark job as running
        deck = await FlashcardDeck.get(deck_id)
        if not deck:
            raise ValueError(f"Deck {deck_id} not found")

        deck.job_status_override = "running"
        deck.job_error = None
        await deck.save()

        # Start background task
        task = asyncio.create_task(
            _run_generation_background(deck_id, notebook_id, num_cards)
        )
        _running_jobs[deck_id] = task
        logger.info(f"[flashcard_job] Submitted generation job for deck {deck_id}")

        return deck_id

    @staticmethod
    async def get_job_status(deck_id: str) -> Dict[str, Any]:
        """Get the status of a flashcard generation job."""
        try:
            deck = await FlashcardDeck.get(deck_id)
            if not deck:
                return {
                    "job_id": deck_id,
                    "status": "not_found",
                    "message": "Deck not found",
                }

            # Check if job is still running in memory
            is_running = deck_id in _running_jobs

            # Determine status
            db_status = deck.job_status_override

            # Handle server restart: if DB shows "running" but job is not in memory,
            # the server likely restarted and the job was lost
            if db_status == "running" and not is_running:
                # Check if there are cards - if so, job completed before restart
                card_count = await deck.get_card_count()
                if card_count > 0:
                    # Job completed before restart - update status
                    deck.job_status_override = "completed"
                    await deck.save()
                    status = "completed"
                else:
                    # Job was interrupted - mark as failed
                    deck.job_status_override = "failed"
                    deck.job_error = "Job was interrupted due to server restart"
                    await deck.save()
                    status = "failed"
            elif is_running and db_status != "failed":
                status = "running"
            elif db_status:
                status = db_status
            else:
                status = "pending" if deck.total_cards == 0 else "completed"

            card_count = await deck.get_card_count()

            return {
                "job_id": deck_id,
                "status": status,
                "error": deck.job_error,
                "card_count": card_count,
                "deck_name": deck.name,
                "notebook_id": deck.notebook_id,
                "is_running": is_running,
            }
        except Exception as e:
            logger.error(f"[flashcard_job] Failed to get job status: {e}")
            return {
                "job_id": deck_id,
                "status": "error",
                "message": str(e),
            }
