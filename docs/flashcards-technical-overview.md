# Flashcards System - Technical Overview

## 1. High-Level Architecture

```mermaid
graph TB
    subgraph Frontend ["Frontend (Next.js)"]
        UI[Flashcard Pages]
        Hooks[React Query Hooks]
        API_Client[API Client]
    end

    subgraph Backend ["Backend (FastAPI)"]
        Router[Flashcard Router]
        Service[FlashcardService]
        Models[Domain Models]
    end

    subgraph AI_Pipeline ["AI Generation Pipeline (LangGraph)"]
        Extract[Extract Concepts]
        Generate[Generate Flashcards]
        QA[Quality Check]
        Revise[Revise Flagged Cards]
    end

    subgraph Data ["Data Layer (SurrealDB)"]
        DeckTable[(flashcard_deck)]
        CardTable[(flashcard)]
        SessionTable[(flashcard_session)]
    end

    subgraph Content ["Content Sources"]
        Notebook[Notebook]
        Sources[Sources]
        Notes[Notes]
    end

    UI --> Hooks --> API_Client --> Router
    Router --> Service
    Router --> Models
    Service --> AI_Pipeline
    Extract --> Generate --> QA --> Revise
    Models --> Data
    AI_Pipeline --> Content
    AI_Pipeline --> Data
```

---

## 2. Data Model

```mermaid
erDiagram
    NOTEBOOK ||--o{ FLASHCARD_DECK : "generates"
    NOTEBOOK ||--o{ SOURCE : "contains"
    NOTEBOOK ||--o{ NOTE : "contains"
    FLASHCARD_DECK ||--o{ FLASHCARD : "contains"
    FLASHCARD_DECK ||--o{ FLASHCARD_SESSION : "studied in"

    FLASHCARD_DECK {
        string id PK
        string name
        string description
        string notebook_id FK
        boolean auto_generated
        int total_cards
        int cards_due
        int cards_new
        int cards_learned
        int daily_new_limit
        int daily_review_limit
        string job_status_override
        string job_error
    }

    FLASHCARD {
        string id PK
        string deck_id FK
        string card_type "basic | cloze | reverse | multiple_choice"
        string question
        string answer
        string cloze_text
        list hints
        string explanation
        string difficulty "easy | medium | hard"
        list tags
        string srs_stage "new | learning | review | relearning"
        int srs_repetitions
        int srs_interval
        float srs_ease_factor
        string srs_due_date
        float mastery
        int times_correct
        int times_incorrect
    }

    FLASHCARD_SESSION {
        string id PK
        string deck_id FK
        string session_type "study | review | custom"
        list card_queue
        list user_answers
        float score
        string started_at
        string completed_at
        int total_cards
        int correct_count
    }
```

---

## 3. Flashcard Generation Flow (End-to-End)

This is the main sequence: a user creates a deck and triggers AI generation from notebook content.

```mermaid
sequenceDiagram
    actor User
    participant FE as Frontend
    participant API as FastAPI Router
    participant Svc as FlashcardService
    participant DB as SurrealDB
    participant Graph as LangGraph Pipeline
    participant LLM as AI Model (LLM)

    User->>FE: Click "Create Deck" with notebook
    FE->>API: POST /flashcards/decks
    API->>DB: Save new FlashcardDeck
    DB-->>API: deck_id
    API-->>FE: deck created (deck_id)

    User->>FE: Click "Generate Cards"
    FE->>API: POST /flashcards/decks/{deck_id}/generate
    API->>API: Verify deck & notebook exist
    API->>API: Check notebook has sources/notes
    API->>Svc: submit_generation_job(deck_id, notebook_id, num_cards)
    Svc->>DB: Set deck.job_status = "running"
    Svc->>Svc: asyncio.create_task(background generation)
    Svc-->>API: job_id (= deck_id)
    API-->>FE: {job_id, status: "running"}

    Note over FE: Frontend begins polling

    loop Poll every 2-3 seconds
        FE->>API: GET /flashcards/jobs/{job_id}
        API->>Svc: get_job_status(deck_id)
        Svc->>DB: Check deck status + card count
        Svc-->>API: {status, card_count}
        API-->>FE: job status response
    end

    Note over Svc,LLM: Background Generation (see next diagram)

    Svc->>Graph: run_flashcard_generation()
    Graph->>DB: Fetch notebook sources & notes (max 50KB)
    Graph->>LLM: Step 1 - Extract Concepts
    LLM-->>Graph: JSON array of concepts
    Graph->>LLM: Step 2 - Generate Flashcards (Q&A)
    LLM-->>Graph: JSON array of flashcards
    Graph->>LLM: Step 3 - Quality Check
    LLM-->>Graph: PASS/REVISION per card

    opt Cards flagged for revision
        Graph->>LLM: Step 4 - Revise flagged cards
        LLM-->>Graph: Revised cards
    end

    Graph->>DB: Save each flashcard to deck
    Graph-->>Svc: {deck_id, flashcards, errors}
    Svc->>DB: Set deck.job_status = "completed"

    FE->>API: GET /flashcards/jobs/{job_id}
    API-->>FE: {status: "completed", card_count: N}
    FE->>API: GET /flashcards/decks/{deck_id}/cards
    API->>DB: Fetch all cards
    DB-->>API: Card list
    API-->>FE: Flashcard cards
    FE-->>User: Display generated flashcards
```

---

## 4. AI Generation Pipeline (LangGraph Detail)

The 4-step AI pipeline that transforms raw notebook content into quality-checked flashcards.

```mermaid
sequenceDiagram
    participant Runner as run_flashcard_generation()
    participant S1 as Node 1: Extract Concepts
    participant S2 as Node 2: Generate Flashcards
    participant S3 as Node 3: Quality Check
    participant S4 as Revise Flagged Cards
    participant LLM as AI Model

    Runner->>Runner: Fetch notebook content<br/>(sources + notes, max 50KB)

    Runner->>S1: Pass content + num_cards
    S1->>LLM: "Analyze content, identify key concepts"<br/>Classify as: fact / concept / procedure / principle
    LLM-->>S1: [{name, definition, type, importance, relationships}, ...]
    S1->>S1: Validate & clean concepts<br/>(max 200 char name, 500 char definition)

    S1->>S2: Pass concepts + difficulty_mix
    S2->>LLM: "Create flashcards from concepts"<br/>Types: basic, cloze, conceptual, applied<br/>Difficulty distribution: 30% easy, 50% medium, 20% hard
    LLM-->>S2: [{card_type, question, answer, hints, explanation, difficulty}, ...]
    S2->>S2: Normalize cards, strip cloze syntax from questions

    opt include_cloze && cards < target
        S2->>LLM: "Generate additional cloze deletion cards"
        LLM-->>S2: [{card_type: "cloze", cloze_text, question, answer}, ...]
    end

    S2->>S3: Pass all flashcards
    S3->>LLM: "Review each card against quality criteria"<br/>Check: single concept, unambiguous, accurate,<br/>appropriate difficulty, complete answer, no leakage
    LLM-->>S3: [{question, status: PASS|REVISION, suggestions}, ...]

    alt Some cards flagged as REVISION
        S3->>S3: Split into passed_cards + cards_to_fix
        S3->>S4: Pass flagged cards with suggestions
        S4->>LLM: "Revise flagged cards, fix identified issues"
        LLM-->>S4: [{original_question, revised question/answer/hints}, ...]
        S4->>S4: Match revised to originals, fallback to original if no match
        S4-->>S3: Revised cards
        S3->>S3: Merge: passed_cards + revised_cards
    else All cards PASS
        S3->>S3: Return all cards as-is
    end

    S3-->>Runner: Final flashcards list
    Runner->>Runner: Save each card to DB with SRS initialization<br/>(stage=new, ease_factor=2.5, interval=0)
```

---

## 5. Study Session Flow

How a user studies flashcards and how the system tracks progress.

```mermaid
sequenceDiagram
    actor User
    participant FE as Frontend
    participant API as FastAPI Router
    participant DB as SurrealDB

    User->>FE: Click "Study" on a deck
    FE->>API: POST /flashcards/sessions {deck_id}
    API->>DB: Create FlashcardSession<br/>(started_at = now)
    DB-->>API: session_id
    API-->>FE: Session created

    FE->>API: GET /flashcards/decks/{deck_id}/cards
    API->>DB: Fetch all cards (due cards first)
    DB-->>API: Card list (sorted by SRS priority)
    API-->>FE: Cards for study

    loop For each card in session
        FE-->>User: Show question + hints
        User->>FE: Reveal answer
        FE-->>User: Show answer + explanation
        User->>FE: Self-grade: Correct / Incorrect
        FE->>API: POST /sessions/{session_id}/answer<br/>{card_id, user_answer, correct: true/false}
        API->>DB: Append answer to session.user_answers<br/>Update session score
        API-->>FE: Updated session state
    end

    User->>FE: Click "Finish Session"
    FE->>API: POST /sessions/{session_id}/complete

    API->>DB: Set session.completed_at = now<br/>Calculate final score

    loop For each answer in session
        API->>DB: Load flashcard by card_id
        API->>API: Calculate SRS quality<br/>(correct = 4, incorrect = 1)
        API->>API: Run SM-2 algorithm<br/>(update interval, ease, stage, due_date)
        API->>DB: Save updated flashcard SRS data
    end

    API->>DB: Update deck stats<br/>(cards_new, cards_due, cards_learned)
    API-->>FE: Completed session with final score
    FE-->>User: Show session results<br/>(score, cards correct, time spent)
```

---

## 6. Spaced Repetition System (SM-2 Algorithm)

The SM-2 algorithm determines when each card should be reviewed next. This is the industry-standard algorithm used by tools like Anki.

```mermaid
sequenceDiagram
    participant Card as Flashcard
    participant SM2 as SM-2 Algorithm

    Note over Card: Initial state:<br/>stage=new, interval=0,<br/>ease=2.5, repetitions=0

    Card->>SM2: User answers (quality rating)

    alt Quality >= 3 (Correct)
        SM2->>SM2: Check repetition count
        alt First correct answer (rep=0)
            SM2-->>Card: interval = 1 day
        else Second correct answer (rep=1)
            SM2-->>Card: interval = 6 days
        else Subsequent correct (rep>=2)
            SM2-->>Card: interval = interval x ease_factor
        end
        SM2->>Card: repetitions += 1
        SM2->>Card: stage = "review"
        SM2->>Card: times_correct += 1
    else Quality < 3 (Incorrect)
        SM2->>Card: interval = 1 day (reset)
        SM2->>Card: repetitions = 0 (reset)
        SM2->>Card: stage = "relearning"
        SM2->>Card: times_incorrect += 1
    end

    SM2->>SM2: Update ease factor:<br/>EF' = EF + (0.1 - (5-q) * (0.08 + (5-q) * 0.02))<br/>Minimum: 1.3
    SM2->>Card: due_date = now + interval
    SM2->>Card: mastery = (correct / total) * 100
```

### SM-2 in Practice: Example Card Lifecycle

| Review # | Answer  | Quality | Interval | Next Due     | Ease Factor | Stage      |
|----------|---------|---------|----------|--------------|-------------|------------|
| 1        | Correct | 4       | 1 day    | Tomorrow     | 2.50        | review     |
| 2        | Correct | 4       | 6 days   | Next week    | 2.50        | review     |
| 3        | Wrong   | 1       | 1 day    | Tomorrow     | 2.18        | relearning |
| 4        | Correct | 4       | 1 day    | Tomorrow     | 2.18        | review     |
| 5        | Correct | 4       | 6 days   | Next week    | 2.18        | review     |
| 6        | Correct | 4       | 13 days  | ~2 weeks     | 2.18        | review     |
| 7        | Correct | 4       | 28 days  | ~1 month     | 2.18        | review     |

Cards that are consistently answered correctly get shown less frequently (intervals grow). Wrong answers reset the cycle.

---

## 7. Card Types

The system generates four types of flashcards to engage different cognitive levels:

```mermaid
graph LR
    subgraph Basic ["Basic (Standard Q&A)"]
        BQ[Q: What is photosynthesis?]
        BA[A: The process by which plants<br/>convert light energy into<br/>chemical energy]
    end

    subgraph Cloze ["Cloze (Fill-in-the-blank)"]
        CQ[Q: The mitochondria is the<br/>_____ of the cell]
        CA[A: powerhouse]
    end

    subgraph Conceptual ["Conceptual (Why/How)"]
        DQ[Q: Why do leaves change<br/>color in autumn?]
        DA[A: As daylight decreases,<br/>chlorophyll breaks down revealing<br/>other pigments...]
    end

    subgraph Applied ["Applied (Scenario-based)"]
        AQ[Q: A patient presents with<br/>fatigue and pale skin.<br/>What deficiency might this indicate?]
        AA[A: Iron deficiency anemia...]
    end
```

Each card also includes:
- **Hints** - Progressive clues (vague to specific) to help before revealing the answer
- **Explanation** - Why the answer is correct (shown after reveal)
- **Difficulty** - easy / medium / hard (distributed: 30% / 50% / 20%)
- **Tags** - For categorization and filtering

---

## 8. Quality Assurance Pipeline

Every generated card goes through automated quality review before being saved.

```mermaid
flowchart TD
    A[Generated Cards] --> B{Quality Review<br/>by AI}

    B -->|PASS| C[Card meets all criteria]
    B -->|REVISION| D[Card has issues]

    C --> G[Final Card Set]

    D --> E{AI Revision}
    E -->|Revised successfully| F[Improved Card]
    E -->|Revision failed| H[Keep Original]

    F --> G
    H --> G

    subgraph Quality Criteria
        Q1[Single concept per card]
        Q2[Unambiguous wording]
        Q3[Factually accurate]
        Q4[Appropriate difficulty]
        Q5[Complete answer - 3 to 50 words]
        Q6[No answer leakage in question]
        Q7[Good hint progression]
    end
```

---

## 9. API Endpoints Reference

### Deck Management
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/flashcards/notebook/{notebook_id}/check` | Check if notebook has content for generation |
| `GET` | `/flashcards/decks` | List all decks (optional notebook filter) |
| `GET` | `/flashcards/decks/{deck_id}` | Get deck with statistics |
| `POST` | `/flashcards/decks` | Create new deck |
| `PUT` | `/flashcards/decks/{deck_id}` | Update deck metadata |
| `DELETE` | `/flashcards/decks/{deck_id}` | Delete deck and all cards |

### Card Generation & Management
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/flashcards/decks/{deck_id}/generate` | Submit async AI generation job |
| `GET` | `/flashcards/jobs/{job_id}` | Poll generation job status |
| `GET` | `/flashcards/decks/{deck_id}/cards` | Get all cards in deck |
| `POST` | `/flashcards/decks/{deck_id}/cards` | Add manual card |

### Study Sessions
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/flashcards/sessions` | Start new study session |
| `GET` | `/flashcards/sessions/{session_id}` | Get session details |
| `POST` | `/flashcards/sessions/{session_id}/answer` | Submit answer for a card |
| `POST` | `/flashcards/sessions/{session_id}/complete` | Complete session (triggers SRS updates) |
| `GET` | `/flashcards/sessions/deck/{deck_id}` | Get recent sessions |
| `GET` | `/flashcards/decks/{deck_id}/stats` | Get aggregate statistics |

---

## 10. Key Technical Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| **SRS Algorithm** | SM-2 (SuperMemo 2) | Industry standard, proven effective, same as Anki |
| **AI Pipeline** | LangGraph state machine | Supports multi-step workflows with checkpointing |
| **Job Execution** | asyncio background tasks | Lightweight, no external queue needed |
| **Card Generation** | Concept extraction first | Better quality than direct Q&A generation from raw text |
| **Quality Gate** | AI-powered review + revision | Catches bad cards before they reach the user |
| **Content Limit** | 50KB max from notebook | Balances quality with LLM context window |
| **Frontend Polling** | GET /jobs/{id} polling | Simple, reliable for async generation status |
| **Database** | SurrealDB | Consistent with rest of application |

---

## 11. File Map

| File | Purpose |
|------|---------|
| `open_notebook/domain/flashcard.py` | Domain models: FlashcardDeck, Flashcard, FlashcardSession |
| `open_notebook/graphs/flashcards.py` | AI generation pipeline (LangGraph): concept extraction, card generation, QA |
| `api/flashcard_service.py` | Background job management for async generation |
| `api/routers/flashcards.py` | REST API endpoints |
| `frontend/src/lib/types/flashcards.ts` | TypeScript type definitions |
| `frontend/src/lib/api/flashcards.ts` | Frontend API client |
| `frontend/src/lib/hooks/use-flashcards.ts` | React Query hooks for data fetching |
| `frontend/src/app/(dashboard)/flashcards/` | UI pages (deck list, deck detail, study) |
| `prompts/flashcard/` | Jinja templates for AI prompts |
