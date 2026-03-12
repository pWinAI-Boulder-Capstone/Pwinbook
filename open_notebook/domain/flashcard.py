from typing import Any, ClassVar, Dict, List, Literal, Optional
from datetime import datetime, timedelta

from loguru import logger
from pydantic import Field, field_validator

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.base import ObjectModel


# Card type definitions for industrial-standard flashcards
CardType = Literal["basic", "cloze", "reverse", "multiple_choice"]

# Spaced Repetition System (SRS) fields
# Based on SM-2 algorithm (SuperMemo 2) - industry standard for spaced repetition
SRSSchedule = Literal["new", "learning", "review", "relearning"]


class FlashcardDeck(ObjectModel):
    """
    Flashcard Deck - Container for a set of flashcards.

    Decks can be created manually or auto-generated from notebook content.
    Each deck belongs to an optional notebook for source tracking.
    """

    table_name: ClassVar[str] = "flashcard_deck"

    name: str = Field(..., description="Deck name")
    description: Optional[str] = Field(None, description="Deck description")
    notebook_id: Optional[str] = Field(None, description="Source notebook ID")
    auto_generated: bool = Field(default=False, description="Whether AI-generated")

    # Study statistics (cached for performance)
    total_cards: int = Field(default=0, description="Total cards in deck")
    cards_due: int = Field(default=0, description="Cards due for review")
    cards_new: int = Field(default=0, description="Unstudied cards")
    cards_learned: int = Field(default=0, description="Mastered cards")

    # SRS settings
    daily_new_limit: int = Field(default=20, description="Max new cards per day")
    daily_review_limit: int = Field(default=200, description="Max reviews per day")

    # Background job tracking (for AI generation)
    job_status_override: Optional[str] = Field(
        default=None, description="Job status: pending, running, completed, failed"
    )
    job_error: Optional[str] = Field(
        default=None, description="Error message if job failed"
    )

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v):
        if not v.strip():
            raise ValueError("Deck name cannot be empty")
        return v

    @field_validator("daily_new_limit", "daily_review_limit")
    @classmethod
    def validate_limits(cls, v):
        if v < 1 or v > 1000:
            raise ValueError("Daily limits must be between 1 and 1000")
        return v

    def _prepare_save_data(self) -> dict:
        data = super()._prepare_save_data()
        if data.get("notebook_id") is not None:
            data["notebook_id"] = ensure_record_id(data["notebook_id"])
        return data

    @classmethod
    async def get_by_notebook_id(cls, notebook_id: str) -> List["FlashcardDeck"]:
        """Get all decks for a specific notebook"""
        result = await repo_query(
            "SELECT * FROM flashcard_deck WHERE notebook_id = $notebook_id ORDER BY updated DESC",
            {"notebook_id": notebook_id},
        )
        return [cls(**deck) for deck in result] if result else []

    @classmethod
    async def get_with_card_count(cls, deck_id: str) -> Optional[Dict[str, Any]]:
        """Get deck with card count"""
        record_id = ensure_record_id(deck_id)
        # First get the deck
        deck_result = await repo_query(
            "SELECT * FROM $deck_id",
            {"deck_id": record_id},
        )
        if not deck_result:
            return None
        deck_data = deck_result[0]
        # Then get the card count
        count_result = await repo_query(
            "SELECT count() as count FROM flashcard WHERE deck_id = $deck_id GROUP ALL",
            {"deck_id": record_id},
        )
        card_count = count_result[0].get("count", 0) if count_result else 0
        deck_data["card_count"] = card_count
        return deck_data

    @classmethod
    async def get_with_stats(cls, deck_id: str) -> Optional[Dict[str, Any]]:
        """Get deck with detailed statistics"""
        record_id = ensure_record_id(deck_id)
        # Get the deck
        deck_result = await repo_query(
            "SELECT * FROM $deck_id",
            {"deck_id": record_id},
        )
        if not deck_result:
            return None
        deck_data = deck_result[0]
        # Get card stats separately
        stats_result = await repo_query(
            """
            SELECT
                count() as total_cards,
                count(IF srs_stage = 'new' THEN 1 END) as cards_new,
                count(IF srs_stage = 'learning' THEN 1 END) as cards_learning,
                count(IF srs_stage = 'review' AND srs_due_date != NONE AND type::datetime(srs_due_date) <= time::now() THEN 1 END) as cards_due,
                count(IF srs_repetitions >= 3 THEN 1 END) as cards_learned
            FROM flashcard WHERE deck_id = $deck_id
            GROUP ALL
            """,
            {"deck_id": record_id},
        )
        if stats_result:
            deck_data.update(stats_result[0])
        else:
            deck_data.update({
                "total_cards": 0, "cards_new": 0, "cards_learning": 0,
                "cards_due": 0, "cards_learned": 0,
            })
        return deck_data

    async def get_cards(self) -> List["Flashcard"]:
        """Get all cards in this deck"""
        result = await repo_query(
            "SELECT * FROM flashcard WHERE deck_id = $deck_id ORDER BY created ASC",
            {"deck_id": ensure_record_id(self.id)},
        )
        return [Flashcard(**card) for card in result] if result else []

    async def get_due_cards(self, limit: int = 50) -> List["Flashcard"]:
        """Get cards that are due for review based on SRS schedule"""
        result = await repo_query(
            """
            SELECT * FROM flashcard
            WHERE deck_id = $deck_id
            AND (srs_stage = 'new' OR (srs_stage = 'review' AND srs_due_date <= time::now()))
            ORDER BY
                CASE srs_stage
                    WHEN 'new' THEN 0
                    WHEN 'learning' THEN 1
                    WHEN 'relearning' THEN 2
                    ELSE 3
                END,
                srs_due_date ASC
            LIMIT $limit
            """,
            {"deck_id": ensure_record_id(self.id), "limit": limit},
        )
        return [Flashcard(**card) for card in result] if result else []

    async def get_card_count(self) -> int:
        """Get number of cards in this deck"""
        result = await repo_query(
            "SELECT count() as count FROM flashcard WHERE deck_id = $deck_id GROUP ALL",
            {"deck_id": ensure_record_id(self.id)},
        )
        if result and len(result) > 0:
            return result[0].get("count", 0)
        return 0

    async def delete_cards(self) -> bool:
        """Delete all cards in this deck"""
        cards = await self.get_cards()
        for card in cards:
            await card.delete()
        return True

    async def update_stats(self) -> None:
        """Update cached statistics for the deck"""
        stats = await self.get_with_stats(str(self.id)) if self.id else None
        if stats:
            self.total_cards = stats.get("total_cards", 0)
            self.cards_new = stats.get("cards_new", 0)
            self.cards_due = stats.get("cards_due", 0)
            self.cards_learned = stats.get("cards_learned", 0)
            await self.save()


class Flashcard(ObjectModel):
    """
    Flashcard - Individual study card with enhanced features.

    Supports multiple card types (basic, cloze, reverse, multiple choice)
    and spaced repetition scheduling (SM-2 algorithm).
    """

    table_name: ClassVar[str] = "flashcard"

    # Basic card data
    deck_id: str = Field(..., description="Parent deck reference")
    card_type: CardType = Field(default="basic", description="Type of flashcard")

    # Question/Answer content
    question: str = Field(..., description="Front of card (question/prompt)")
    answer: str = Field(..., description="Back of card (answer)")

    # For cloze deletion cards
    cloze_text: Optional[str] = Field(
        None, description="Text with {{c1::deletions}} for cloze cards"
    )

    # For multiple choice cards
    choices: Optional[List[str]] = Field(
        None, description="Answer choices for multiple choice cards"
    )
    correct_choice_index: Optional[int] = Field(
        None, description="Index of correct answer"
    )

    # Additional help
    hints: Optional[List[str]] = Field(
        default_factory=list, description="Progressive hints"
    )
    explanation: Optional[str] = Field(
        None, description="Detailed explanation after answer"
    )

    # Metadata
    source_references: Optional[List[Dict[str, str]]] = Field(
        default_factory=list, description="Links to Source/Note IDs with type prefix"
    )
    difficulty: Optional[Literal["easy", "medium", "hard"]] = Field(
        default="medium", description="Base difficulty level"
    )
    tags: Optional[List[str]] = Field(default_factory=list, description="User tags")

    # Spaced Repetition (SM-2 Algorithm)
    srs_stage: SRSSchedule = Field(default="new", description="Current SRS stage")
    srs_repetitions: int = Field(
        default=0, description="Successful consecutive recalls"
    )
    srs_interval: int = Field(default=0, description="Days until next review")
    srs_ease_factor: float = Field(
        default=2.5, description="SM-2 ease factor (minimum 1.3)"
    )
    srs_due_date: Optional[str] = Field(None, description="Next review due date (ISO)")
    srs_last_reviewed: Optional[str] = Field(None, description="Last review timestamp")

    # Mastery tracking
    mastery: float = Field(default=0.0, description="Mastery percentage (0-100)")
    times_correct: int = Field(default=0, description="Total correct answers")
    times_incorrect: int = Field(default=0, description="Total incorrect answers")

    def _prepare_save_data(self) -> dict:
        data = super()._prepare_save_data()
        if data.get("deck_id") is not None:
            data["deck_id"] = ensure_record_id(data["deck_id"])
        return data

    @field_validator("question")
    @classmethod
    def question_must_not_be_empty(cls, v):
        if not v.strip():
            raise ValueError("Question cannot be empty")
        return v

    @field_validator("answer")
    @classmethod
    def answer_must_not_be_empty(cls, v):
        if not v.strip():
            raise ValueError("Answer cannot be empty")
        return v

    @field_validator("srs_ease_factor")
    @classmethod
    def validate_ease_factor(cls, v):
        if v < 1.3:
            return 1.3  # SM-2 minimum
        return v

    @classmethod
    async def get_by_deck(cls, deck_id: str) -> List["Flashcard"]:
        """Get all cards for a deck"""
        result = await repo_query(
            "SELECT * FROM flashcard WHERE deck_id = $deck_id ORDER BY created ASC",
            {"deck_id": ensure_record_id(deck_id)},
        )
        return [cls(**card) for card in result] if result else []

    @classmethod
    async def get_due_for_deck(cls, deck_id: str, limit: int = 50) -> List["Flashcard"]:
        """Get cards due for review from a deck"""
        result = await repo_query(
            """
            SELECT * FROM flashcard
            WHERE deck_id = $deck_id
            AND (srs_stage = 'new' OR (srs_stage = 'review' AND srs_due_date <= time::now()))
            ORDER BY srs_due_date ASC
            LIMIT $limit
            """,
            {"deck_id": ensure_record_id(deck_id), "limit": limit},
        )
        return [cls(**card) for card in result] if result else []

    def update_srs(self, quality: int) -> None:
        """
        Update SRS parameters using SM-2 algorithm.

        Args:
            quality: Recall quality 0-5 where:
                5 = perfect response
                4 = correct response after hesitation
                3 = correct response with difficulty
                2 = incorrect response but recognized correct answer
                1 = incorrect response but remembered after seeing answer
                0 = completely incorrect, no recognition
        """
        now = datetime.now()

        # SM-2 Algorithm implementation
        if quality >= 3:
            # Correct response
            if self.srs_repetitions == 0:
                self.srs_interval = 1
            elif self.srs_repetitions == 1:
                self.srs_interval = 6
            else:
                self.srs_interval = int(self.srs_interval * self.srs_ease_factor)

            self.srs_repetitions += 1
            self.srs_stage = "review"
            self.times_correct += 1

        else:
            # Incorrect response - reset
            self.srs_repetitions = 0
            self.srs_interval = 1
            self.srs_stage = "relearning"
            self.times_incorrect += 1

        # Update ease factor (SM-2 formula)
        self.srs_ease_factor = max(
            1.3,
            self.srs_ease_factor
            + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)),
        )

        # Set due date
        self.srs_due_date = (now + timedelta(days=self.srs_interval)).isoformat()
        self.srs_last_reviewed = now.isoformat()

        # Update mastery (simple percentage based on correct/total)
        total = self.times_correct + self.times_incorrect
        if total > 0:
            self.mastery = round((self.times_correct / total) * 100, 1)

    async def save_with_srs_update(self, quality: int) -> None:
        """Update SRS and save the card"""
        self.update_srs(quality)
        await self.save()


class FlashcardSession(ObjectModel):
    """
    Flashcard Session - Tracks a user's quiz/study session with SRS data.

    Stores user answers, timing, and spaced repetition updates.
    Sessions can be reviewed later for progress tracking.
    """

    table_name: ClassVar[str] = "flashcard_session"

    deck_id: str = Field(..., description="Deck being studied")
    session_type: Literal["study", "review", "custom"] = Field(default="study")

    # Card queue for this session
    card_queue: List[str] = Field(
        default_factory=list, description="Card IDs in study order"
    )
    current_card_index: int = Field(default=0, description="Current position in queue")

    # Results
    user_answers: List[Dict[str, Any]] = Field(
        default_factory=list, description="Detailed answer history with SRS updates"
    )

    # Statistics
    score: float = Field(default=0.0, description="Score percentage (0-100)")
    started_at: str = Field(..., description="ISO timestamp of session start")
    completed_at: Optional[str] = Field(None, description="ISO timestamp of completion")
    total_cards: int = Field(default=0, description="Total cards in session")
    correct_count: int = Field(default=0, description="Number of correct answers")

    # Timing
    total_time_seconds: int = Field(default=0, description="Total session duration")
    average_time_per_card: float = Field(
        default=0.0, description="Avg seconds per card"
    )

    def _prepare_save_data(self) -> dict:
        data = super()._prepare_save_data()
        if data.get("deck_id") is not None:
            data["deck_id"] = ensure_record_id(data["deck_id"])
        return data

    @field_validator("deck_id")
    @classmethod
    def deck_id_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Deck ID must be provided")
        return v

    @classmethod
    async def get_by_deck(cls, deck_id: str) -> List["FlashcardSession"]:
        """Get all sessions for a deck"""
        result = await repo_query(
            "SELECT * FROM flashcard_session WHERE deck_id = $deck_id ORDER BY started_at DESC",
            {"deck_id": ensure_record_id(deck_id)},
        )
        return [cls(**session) for session in result] if result else []

    @classmethod
    async def get_recent_sessions(
        cls, deck_id: str, limit: int = 5
    ) -> List["FlashcardSession"]:
        """Get most recent sessions for a deck"""
        result = await repo_query(
            "SELECT * FROM flashcard_session WHERE deck_id = $deck_id ORDER BY started_at DESC LIMIT $limit",
            {"deck_id": ensure_record_id(deck_id), "limit": limit},
        )
        return [cls(**session) for session in result] if result else []

    @classmethod
    async def get_stats_for_deck(cls, deck_id: str) -> Optional[Dict[str, Any]]:
        """Get aggregate stats for a deck's sessions"""
        result = await repo_query(
            """
            SELECT
                count() as total_sessions,
                math.mean(score) as avg_score,
                math.max(score) as best_score,
                math.min(score) as worst_score,
                math.mean(total_cards) as avg_cards_per_session,
                math.mean(total_time_seconds) as avg_session_duration
            FROM flashcard_session
            WHERE deck_id = $deck_id
            AND completed_at != null
            GROUP ALL
            """,
            {"deck_id": ensure_record_id(deck_id)},
        )
        if result:
            return result[0]
        return None

    @classmethod
    async def get_study_streak(cls, deck_id: str) -> int:
        """Get current study streak (consecutive days with sessions)"""
        result = await repo_query(
            """
            SELECT DISTINCT date_trunc('day', time::from(started_at)) as study_day
            FROM flashcard_session
            WHERE deck_id = $deck_id
            AND completed_at != null
            ORDER BY study_day DESC
            LIMIT 365
            """,
            {"deck_id": ensure_record_id(deck_id)},
        )

        if not result:
            return 0

        # Calculate streak
        from datetime import date, timedelta

        today = date.today()
        streak = 0

        for row in result:
            study_day = row.get("study_day")
            if not study_day:
                continue

            # Parse the date
            try:
                if isinstance(study_day, str):
                    study_date = datetime.fromisoformat(study_day).date()
                else:
                    study_date = study_day

                expected_date = today - timedelta(days=streak)
                if study_date == expected_date:
                    streak += 1
                elif study_date < expected_date:
                    break
            except Exception:
                continue

        return streak

    def add_answer(
        self,
        card_id: str,
        user_answer: str,
        correct: bool,
        time_spent: float = 0.0,
        quality: int = 3,
    ) -> None:
        """
        Add a user answer to the session with SRS quality rating.

        Args:
            card_id: The flashcard ID
            user_answer: User's answer text
            correct: Whether answer was correct
            time_spent: Time spent on this card in seconds
            quality: SM-2 quality rating (0-5)
        """
        answer = {
            "card_id": card_id,
            "user_answer": user_answer,
            "correct": correct,
            "quality": quality,
            "time_spent": time_spent,
            "timestamp": datetime.now().isoformat(),
        }
        self.user_answers.append(answer)

        if correct:
            self.correct_count += 1

        # Recalculate score
        if len(self.user_answers) > 0:
            self.score = round((self.correct_count / len(self.user_answers)) * 100, 2)
            self.average_time_per_card = sum(
                a["time_spent"] for a in self.user_answers
            ) / len(self.user_answers)

    def complete(self) -> None:
        """Mark session as completed and calculate final stats"""
        self.completed_at = datetime.now().isoformat()
        start = datetime.fromisoformat(self.started_at)
        end = datetime.fromisoformat(self.completed_at)
        self.total_time_seconds = int((end - start).total_seconds())
