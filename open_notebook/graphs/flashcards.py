"""
Flashcard generation graph - Industrial-strength AI flashcard creation.

This graph transforms notebook content into high-quality study flashcards using
evidence-based learning principles and Bloom's Taxonomy for question variety.

Features:
- Multiple question types (basic, cloze, conceptual, applied)
- Progressive difficulty scaling
- Automatic hint generation
- Quality validation against common flashcard anti-patterns
- Source reference tracking

Usage:
    from open_notebook.graphs.flashcards import run_flashcard_generation

    result = await run_flashcard_generation(
        notebook_id="notebook:abc123",
        num_cards=20,
        include_cloze=True,
        difficulty_mix={"basic": 0.4, "conceptual": 0.3, "applied": 0.3}
    )
"""

import asyncio
import concurrent.futures
import json
import re
import sqlite3
import uuid
from typing import Any, Dict, List, Optional, TypedDict, Literal
from datetime import datetime

from ai_prompter import Prompter
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from loguru import logger

from open_notebook.config import LANGGRAPH_CHECKPOINT_FILE
from open_notebook.domain.flashcard import Flashcard, FlashcardDeck
from open_notebook.domain.notebook import Notebook, Note, Source
from open_notebook.graphs.utils import provision_langchain_model


# ---------------------------------------------------------------------------
# State definition
# ---------------------------------------------------------------------------


class FlashcardGraphState(TypedDict):
    """State for the flashcard generation graph."""

    notebook_id: Optional[str]
    content: str
    num_cards: int
    include_cloze: bool
    difficulty_mix: Dict[str, float]
    concepts: List[Dict[str, Any]]
    flashcards: List[Dict[str, Any]]
    errors: List[str]
    deck_id: Optional[str]


# ---------------------------------------------------------------------------
# Enhanced Prompt Templates
# ---------------------------------------------------------------------------


EXTRACT_CONCEPTS_PROMPT = """You are an expert instructional designer analyzing content for flashcard creation.

Your task is to identify the most important, testable concepts from the provided content.
Focus on information that learners should retain long-term.

For each concept, extract:
- name: The term, concept, or principle name
- definition: A precise, self-contained definition (1-2 sentences)
- type: Classify as "fact", "concept", "procedure", or "principle"
- importance: Why this matters for understanding the topic
- relationships: Related concepts or prerequisites

Content to analyze:
{{ content }}

Return your response as a JSON array:
[
  {
    "name": "Concept Name",
    "definition": "Clear, precise definition",
    "type": "concept",
    "importance": "Why this matters",
    "relationships": ["Related concept 1", "Related concept 2"]
  },
  ...
]

Extract {{ num_concepts }} key concepts. Prioritize:
1. Foundational concepts that other ideas build on
2. Common points of confusion or misunderstanding
3. High-value information frequently tested or applied
4. Concepts with clear right/wrong understanding"""


GENERATE_FLASHCARDS_PROMPT = """You are an expert flashcard writer creating study materials following evidence-based learning principles.

Your task is to create high-quality flashcards from the provided concepts.

## Question Quality Guidelines (based on learning science):
- **Atomic**: One concept per card (no compound questions)
- **Clear**: Unambiguous wording, no trick questions
- **Context-rich**: Include necessary context in the question
- **Self-contained**: Answer should be definitive, not "see above"
- **Varied cognitive levels**: Mix recall, comprehension, application

## Card Types:
1. **basic**: Standard Q&A format
2. **cloze**: Fill-in-the-blank with {% raw %}{{c1::deletion}}{% endraw %} syntax
3. **conceptual**: "Why" or "How" questions testing understanding
4. **applied**: Scenario-based questions applying knowledge

## Answer Quality Guidelines:
- Complete but concise (2-4 sentences max)
- Include key terms in context
- Add mnemonic devices when helpful
- Provide 1-2 progressive hints (from vague to specific)
- Include an explanation for why the answer is correct

Concepts to convert:
{{ concepts }}

Create {{ num_cards }} flashcards with this difficulty distribution:
{{ difficulty_info }}

Return your response as a JSON array:
[
  {
    "card_type": "basic",
    "question": "Clear, specific question",
    "answer": "Complete answer with context",
    "hints": ["Vague hint", "More specific hint"],
    "explanation": "Why this answer is correct",
    "difficulty": "easy",
    "tags": ["tag1", "tag2"],
    "source_concept": "Original concept name"
  },
  ...
]

Ensure variety in question types and difficulties. Each card should test a distinct aspect of understanding."""


GENERATE_CLOZE_CARDS_PROMPT = """You are an expert at creating cloze deletion flashcards (fill-in-the-blank).

Cloze cards are powerful for memorizing specific terms, formulas, or key phrases.

Given the concepts below, create cloze deletion cards by taking key sentences and replacing
the most important term with {% raw %}{{c1::answer}}{% endraw %} syntax.

Guidelines:
- Only cloze the MOST important term in each sentence
- Keep surrounding context intact
- Ensure the answer is uniquely determined by the context
- Create 1-2 cloze cards per concept

Concepts:
{{ concepts }}

Return your response as a JSON array:
[
  {
    "card_type": "cloze",
    "cloze_text": "A sentence with the key term replaced like this: {% raw %}{{c1::the answer}}{% endraw %}",
    "answer": "The clozed term",
    "question": "What term completes this: A sentence with [...] replaced?",
    "hints": ["First letter hint"],
    "difficulty": "medium",
    "source_concept": "Concept name"
  },
  ...
]

Create approximately {{ num_cloze_cards }} cloze cards."""


QUALITY_CHECK_PROMPT = """You are a quality assurance reviewer for educational flashcards.

Review each flashcard against these criteria:

## PASS criteria (all must be met):
1. **Single concept**: Tests only one piece of knowledge
2. **Unambiguous**: Clear what is being asked, one correct answer
3. **Accurate**: Factually correct information
4. **Appropriate level**: Matches stated difficulty
5. **Complete answer**: Answer fully addresses the question
6. **No leakage**: Answer isn't hinted in the question

## REVISION triggers (flag if any apply):
- [ ] Question is vague or has multiple interpretations
- [ ] Answer could be disputed or has multiple valid forms
- [ ] Tests trivia without educational value
- [ ] Uses negation confusingly ("Which is NOT...")
- [ ] Has absolute terms that make it guessable ("always", "never")
- [ ] Answer is too long (>50 words) or too short (<3 words)
- [ ] Cloze card has multiple terms that could fit the blank
- [ ] Hints give away the answer immediately

Flashcards to review:
{{ flashcards }}

Return your response as a JSON array:
[
  {
    "question": "...",
    "status": "PASS",
    "strengths": ["Clear wording", "Good hint progression"],
    "suggestions": []
  },
  {
    "question": "...",
    "status": "REVISION",
    "strengths": [],
    "suggestions": ["Split into two cards", "Add context to question"]
  },
  ...
]

Be constructive but rigorous. Flag cards that don't meet professional educational standards."""


# ---------------------------------------------------------------------------
# Graph Nodes
# ---------------------------------------------------------------------------


def _run_async_in_sync(coro_fn):
    """Run an async function from sync context using a new event loop."""

    def run():
        new_loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(new_loop)
            return new_loop.run_until_complete(coro_fn())
        finally:
            new_loop.close()
            asyncio.set_event_loop(None)

    try:
        asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(run)
            return future.result()
    except RuntimeError:
        return run()


def _parse_json_response(text: str, expected_type: str = "list") -> Any:
    """Parse JSON from LLM response, handling common formatting issues."""
    try:
        # Try to extract JSON array/object from response
        json_match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())

        # Try parsing entire response
        return json.loads(text.strip())
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse JSON response: {e}")
        return None


def extract_concepts_node(state: FlashcardGraphState) -> dict:
    """Extract key concepts from the content using instructional design principles."""
    content = state.get("content", "")
    num_cards = state.get("num_cards", 10)

    if not content.strip():
        logger.warning("[flashcard_graph] No content provided for concept extraction")
        return {
            "concepts": [],
            "errors": state.get("errors", []) + ["No content to analyze"],
        }

    # Estimate concepts to extract (slightly more than needed for filtering later)
    num_concepts = min(num_cards * 2, max(10, len(content) // 400))

    logger.info("[flashcard_graph] Rendering extract_concepts prompt...")
    try:
        prompt = Prompter(
            prompt_template="flashcard/extract_concepts",
            default_content=EXTRACT_CONCEPTS_PROMPT,
        ).render(
            data={
                "content": content[:20000],  # Limit content
                "num_concepts": num_concepts,
            }
        )
    except Exception as render_err:
        logger.error(f"[flashcard_graph] extract_concepts prompt render FAILED: {render_err}")
        logger.exception(render_err)
        raise

    def run_extraction():
        async def _run():
            model = await provision_langchain_model(
                prompt[:1000], None, "chat", max_tokens=4096
            )
            response = model.invoke(
                [
                    SystemMessage(
                        content="You are an instructional designer. Return only valid JSON."
                    ),
                    HumanMessage(content=prompt),
                ]
            )
            return getattr(response, "content", str(response))

        return _run()

    try:
        result_text = _run_async_in_sync(run_extraction)
        concepts = _parse_json_response(result_text)

        if not concepts or not isinstance(concepts, list):
            logger.warning(
                f"[flashcard_graph] Concept extraction returned invalid format"
            )
            return {
                "concepts": [],
                "errors": state.get("errors", []) + ["Failed to parse concepts"],
            }

        # Validate and clean concepts
        valid_concepts = []
        for c in concepts:
            if isinstance(c, dict) and c.get("name") and c.get("definition"):
                valid_concepts.append(
                    {
                        "name": str(c.get("name", ""))[:200],
                        "definition": str(c.get("definition", ""))[:500],
                        "type": c.get("type", "concept"),
                        "importance": c.get("importance", ""),
                        "relationships": c.get("relationships", [])[:5],
                    }
                )

        logger.info(f"[flashcard_graph] Extracted {len(valid_concepts)} valid concepts")
        return {"concepts": valid_concepts, "errors": state.get("errors", [])}

    except Exception as e:
        logger.error(f"[flashcard_graph] Concept extraction failed: {e}")
        return {
            "concepts": [],
            "errors": state.get("errors", [])
            + [f"Concept extraction failed: {str(e)}"],
        }


def generate_flashcards_node(state: FlashcardGraphState) -> dict:
    """Generate diverse flashcards from concepts using Bloom's Taxonomy."""
    concepts = state.get("concepts", [])
    num_cards = state.get("num_cards", 10)
    include_cloze = state.get("include_cloze", True)
    difficulty_mix = state.get(
        "difficulty_mix", {"easy": 0.3, "medium": 0.5, "hard": 0.2}
    )

    if not concepts:
        logger.warning("[flashcard_graph] No concepts to generate flashcards from")
        return {"flashcards": state.get("flashcards", [])}

    # Format concepts for prompt
    concepts_text = "\n\n".join(
        [
            f"**{c.get('name')}** (Type: {c.get('type', 'concept')})\n"
            f"Definition: {c.get('definition')}\n"
            f"Importance: {c.get('importance', 'N/A')}\n"
            f"Related: {', '.join(c.get('relationships', [])) or 'None'}"
            for c in concepts
        ]
    )

    # Format difficulty distribution
    difficulty_info = ", ".join(
        f"{int(p * num_cards)} {level}" for level, p in difficulty_mix.items()
    )

    logger.info("[flashcard_graph] Rendering generate_qa prompt...")
    try:
        prompt = Prompter(
            prompt_template="flashcard/generate_qa",
            default_content=GENERATE_FLASHCARDS_PROMPT,
        ).render(
            data={
                "concepts": concepts_text,
                "num_cards": num_cards,
                "difficulty_info": difficulty_info,
            }
        )
    except Exception as render_err:
        logger.error(f"[flashcard_graph] generate_qa prompt render FAILED: {render_err}")
        logger.exception(render_err)
        raise

    def run_generation():
        async def _run():
            model = await provision_langchain_model(
                prompt[:1000], None, "chat", max_tokens=8192
            )
            response = model.invoke(
                [
                    SystemMessage(
                        content="You are a flashcard expert. Return only valid JSON."
                    ),
                    HumanMessage(content=prompt),
                ]
            )
            return getattr(response, "content", str(response))

        return _run()

    try:
        result_text = _run_async_in_sync(run_generation)
        flashcards = _parse_json_response(result_text)

        if not flashcards or not isinstance(flashcards, list):
            logger.warning(
                f"[flashcard_graph] Flashcard generation returned invalid format"
            )
            return {
                "flashcards": state.get("flashcards", []),
                "errors": state.get("errors", []),
            }

        # Normalize flashcard format
        normalized = []
        for fc in flashcards:
            if (
                not isinstance(fc, dict)
                or not fc.get("question")
                or not fc.get("answer")
            ):
                continue

            normalized.append(
                {
                    "card_type": fc.get("card_type", "basic"),
                    "question": str(fc.get("question", ""))[:500],
                    "answer": str(fc.get("answer", ""))[:1000],
                    "hints": list(fc.get("hints", []))[:3],
                    "explanation": fc.get("explanation", ""),
                    "difficulty": fc.get("difficulty", "medium"),
                    "tags": list(fc.get("tags", []))[:5],
                    "source_concept": fc.get("source_concept", ""),
                    "cloze_text": fc.get("cloze_text"),
                }
            )

        logger.info(f"[flashcard_graph] Generated {len(normalized)} flashcards")

        # Generate cloze cards if requested
        if include_cloze and len(normalized) < num_cards:
            cloze_result = _generate_cloze_cards(concepts, num_cards - len(normalized))
            normalized.extend(cloze_result)

        return {"flashcards": normalized, "errors": state.get("errors", [])}

    except Exception as e:
        logger.error(f"[flashcard_graph] Flashcard generation failed: {e}")
        return {
            "flashcards": state.get("flashcards", []),
            "errors": state.get("errors", [])
            + [f"Flashcard generation failed: {str(e)}"],
        }


def _generate_cloze_cards(concepts: List[Dict], num_cloze: int) -> List[Dict]:
    """Generate cloze deletion cards from concepts."""
    if not concepts or num_cloze <= 0:
        return []

    concepts_text = "\n\n".join(
        [
            f"**{c.get('name')}**: {c.get('definition')}"
            for c in concepts[:15]  # Limit for context
        ]
    )

    prompt = Prompter(
        prompt_template="flashcard/generate_qa",
        default_content=GENERATE_CLOZE_CARDS_PROMPT,
    ).render(data={"concepts": concepts_text, "num_cloze_cards": num_cloze})

    def run_generation():
        async def _run():
            model = await provision_langchain_model(
                prompt[:1000], None, "chat", max_tokens=4096
            )
            response = model.invoke(
                [
                    SystemMessage(
                        content="You are a cloze card expert. Return only valid JSON."
                    ),
                    HumanMessage(content=prompt),
                ]
            )
            return getattr(response, "content", str(response))

        return _run()

    try:
        result_text = _run_async_in_sync(run_generation)
        cloze_cards = _parse_json_response(result_text)

        if not cloze_cards or not isinstance(cloze_cards, list):
            return []

        normalized = []
        for card in cloze_cards:
            if not card.get("cloze_text"):
                continue
            normalized.append(
                {
                    "card_type": "cloze",
                    "question": card.get("question", "Complete this statement"),
                    "answer": card.get("answer", ""),
                    "cloze_text": card.get("cloze_text", ""),
                    "hints": card.get("hints", []),
                    "difficulty": card.get("difficulty", "medium"),
                    "tags": [],
                    "source_concept": card.get("source_concept", ""),
                }
            )

        return normalized[:num_cloze]

    except Exception as e:
        logger.error(f"[flashcard_graph] Cloze generation failed: {e}")
        return []


def quality_check_node(state: FlashcardGraphState) -> dict:
    """Quality check flashcards against educational standards."""
    flashcards = state.get("flashcards", [])

    if not flashcards:
        logger.warning("[flashcard_graph] No flashcards to quality check")
        return {"flashcards": flashcards, "errors": state.get("errors", [])}

    # Format flashcards for review
    flashcards_text = "\n\n".join(
        [
            f"**Card {idx + 1}** (Type: {f.get('card_type', 'basic')}, Difficulty: {f.get('difficulty', 'medium')})\n"
            f"Q: {f.get('question', '')}\n"
            f"A: {f.get('answer', '')}\n"
            f"Hints: {f.get('hints', [])}\n"
            f"Explanation: {f.get('explanation', 'N/A')}"
            for idx, f in enumerate(flashcards[:20])  # Limit for context
        ]
    )

    prompt = Prompter(
        prompt_template="flashcard/review_quality", default_content=QUALITY_CHECK_PROMPT
    ).render(data={"flashcards": flashcards_text})

    def run_check():
        async def _run():
            model = await provision_langchain_model(
                prompt[:1000], None, "chat", max_tokens=4096
            )
            response = model.invoke(
                [
                    SystemMessage(
                        content="You are a QA reviewer. Return only valid JSON."
                    ),
                    HumanMessage(content=prompt),
                ]
            )
            return getattr(response, "content", str(response))

        return _run()

    try:
        result_text = _run_async_in_sync(run_check)
        reviews = _parse_json_response(result_text)

        if not reviews or not isinstance(reviews, list):
            logger.warning(f"[flashcard_graph] Quality check returned invalid format")
            return {"flashcards": flashcards, "errors": state.get("errors", [])}

        # Build set of cards needing revision
        revision_questions = set()
        for r in reviews:
            if r.get("status") == "REVISION":
                revision_questions.add(r.get("question", ""))

        # Filter out problematic cards
        filtered = [
            f for f in flashcards if f.get("question") not in revision_questions
        ]

        if len(revision_questions) > 0:
            logger.info(
                f"[flashcard_graph] Quality check removed {len(revision_questions)} cards"
            )

        return {"flashcards": filtered, "errors": state.get("errors", [])}

    except Exception as e:
        logger.error(f"[flashcard_graph] Quality check failed: {e}")
        return {
            "flashcards": flashcards,
            "errors": state.get("errors", []) + [f"Quality check failed: {str(e)}"],
        }


# ---------------------------------------------------------------------------
# Graph compilation
# ---------------------------------------------------------------------------


def _build_flashcard_graph() -> StateGraph:
    """Build and compile the flashcard generation graph."""
    graph_builder = StateGraph(FlashcardGraphState)

    graph_builder.add_node("extract_concepts", extract_concepts_node)
    graph_builder.add_node("generate_flashcards", generate_flashcards_node)
    graph_builder.add_node("quality_check", quality_check_node)

    graph_builder.add_edge(START, "extract_concepts")
    graph_builder.add_edge("extract_concepts", "generate_flashcards")
    graph_builder.add_edge("generate_flashcards", "quality_check")
    graph_builder.add_edge("quality_check", END)

    conn = sqlite3.connect(LANGGRAPH_CHECKPOINT_FILE, check_same_thread=False)
    memory = SqliteSaver(conn)

    return graph_builder.compile(checkpointer=memory)


graph = _build_flashcard_graph()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def check_notebook_content(notebook_id: str) -> Dict[str, Any]:
    """Quick check if notebook has content for flashcard generation.

    Returns dict with:
    - has_content: bool
    - source_count: int
    - note_count: int
    - total_chars: int (estimated)
    """
    if not notebook_id:
        return {
            "has_content": False,
            "source_count": 0,
            "note_count": 0,
            "total_chars": 0,
        }

    try:
        notebook = await Notebook.get(notebook_id)
        if not notebook:
            return {
                "has_content": False,
                "source_count": 0,
                "note_count": 0,
                "total_chars": 0,
            }

        source_count = 0
        note_count = 0
        total_chars = 0

        try:
            sources = await notebook.get_sources()
            source_count = len(sources) if sources else 0
        except Exception as exc:
            logger.warning(f"[flashcard_graph] failed to get sources: {exc}")

        try:
            notes = await notebook.get_notes()
            note_count = len(notes) if notes else 0
        except Exception as exc:
            logger.warning(f"[flashcard_graph] failed to get notes: {exc}")

        # Estimate total chars (quick estimate without loading full content)
        total_chars = source_count * 3000 + note_count * 1000  # Rough estimates

        has_content = source_count > 0 or note_count > 0

        return {
            "has_content": has_content,
            "source_count": source_count,
            "note_count": note_count,
            "total_chars": total_chars,
        }
    except Exception as exc:
        logger.error(f"[flashcard_graph] failed to check notebook content: {exc}")
        return {
            "has_content": False,
            "source_count": 0,
            "note_count": 0,
            "total_chars": 0,
        }


async def _build_notebook_content(notebook_id: str) -> str:
    """Fetch text content from a notebook's sources and notes."""
    if not notebook_id:
        return ""

    MAX_CHARS_TOTAL = 50_000
    MAX_CHARS_PER_ITEM = 5_000

    try:
        notebook = await Notebook.get(notebook_id)
        if not notebook:
            return ""

        parts: List[str] = [
            f"Notebook: {notebook.name}\nDescription: {notebook.description}\n"
        ]
        total = len(parts[0])

        # Fetch sources
        try:
            source_stubs = await notebook.get_sources()
        except Exception as exc:
            logger.warning(f"[flashcard_graph] failed to load sources: {exc}")
            source_stubs = []

        for stub in source_stubs[:25]:
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
                    f"[flashcard_graph] failed to load source {stub.id}: {exc}"
                )

        # Fetch notes
        try:
            note_stubs = await notebook.get_notes()
        except Exception as exc:
            logger.warning(f"[flashcard_graph] failed to load notes: {exc}")
            note_stubs = []

        for stub in note_stubs[:25]:
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
                    f"[flashcard_graph] failed to load note {stub.id}: {exc}"
                )

        return "".join(parts).strip()
    except Exception as exc:
        logger.warning(
            f"[flashcard_graph] failed to load notebook {notebook_id}: {exc}"
        )
        return ""


async def run_flashcard_generation(
    notebook_id: Optional[str] = None,
    content: Optional[str] = None,
    num_cards: int = 20,
    include_cloze: bool = True,
    difficulty_mix: Optional[Dict[str, float]] = None,
    deck_id: Optional[str] = None,  # Optional existing deck ID to add cards to
    deck_name: Optional[str] = None,
    deck_description: Optional[str] = None,
    save_to_db: bool = True,
) -> Dict[str, Any]:
    """
    Generate industrial-quality flashcards from notebook content.

    Args:
        notebook_id: ID of notebook to extract content from
        content: Direct content to use (if provided, overrides notebook)
        num_cards: Target number of flashcards to generate
        include_cloze: Whether to include cloze deletion cards
        difficulty_mix: Distribution of difficulties {"easy": 0.3, "medium": 0.5, "hard": 0.2}
        deck_name: Name for the new deck (auto-generated if not provided)
        deck_description: Description for the new deck
        save_to_db: Whether to save generated cards to database

    Returns:
        Dict with:
        - deck_id: ID of created deck
        - flashcards: List of generated flashcard dicts
        - errors: List of any errors encountered
    """
    logger.info(
        f"[flashcard_graph] Starting flashcard generation: notebook={notebook_id}, num_cards={num_cards}"
    )

    # Fetch content from notebook if not provided
    if not content:
        if not notebook_id:
            return {
                "deck_id": None,
                "flashcards": [],
                "errors": ["Either notebook_id or content must be provided"],
            }
        logger.info(f"[flashcard_graph] Fetching content from notebook {notebook_id}")
        try:
            content = await _build_notebook_content(notebook_id)
        except Exception as content_err:
            logger.error(f"[flashcard_graph] Content loading FAILED: {content_err}")
            logger.exception(content_err)
            raise
        if not content.strip():
            return {
                "deck_id": None,
                "flashcards": [],
                "errors": ["No content found in notebook"],
            }

    # Use default difficulty mix if not provided
    if difficulty_mix is None:
        difficulty_mix = {"easy": 0.3, "medium": 0.5, "hard": 0.2}

    # Initialize state
    initial_state: FlashcardGraphState = {
        "notebook_id": notebook_id,
        "content": content,
        "num_cards": num_cards,
        "include_cloze": include_cloze,
        "difficulty_mix": difficulty_mix,
        "concepts": [],
        "flashcards": [],
        "errors": [],
        "deck_id": None,
    }

    # Run the graph
    logger.info("[flashcard_graph] Running generation graph...")
    thread_id = f"flashcard-gen-{deck_id or uuid.uuid4().hex}"
    try:
        result = await asyncio.to_thread(
            graph.invoke,
            initial_state,
            config=RunnableConfig(configurable={"thread_id": thread_id}),
        )
    except Exception as graph_err:
        logger.error(f"[flashcard_graph] graph.invoke FAILED: {graph_err}")
        logger.exception(graph_err)
        raise

    flashcards = result.get("flashcards", [])
    errors = result.get("errors", [])
    logger.info(f"[flashcard_graph] Graph returned {len(flashcards)} cards, {len(errors)} errors: {errors}")

    logger.info(
        f"[flashcard_graph] Generated {len(flashcards)} flashcards, {len(errors)} errors"
    )

    # Save to database if requested
    if save_to_db and flashcards:
        try:
            # Use existing deck_id or create new deck
            if deck_id:
                # Load existing deck
                existing_deck = await FlashcardDeck.get(deck_id)
                if not existing_deck:
                    errors.append(f"Deck {deck_id} not found")
                    return {"deck_id": None, "flashcards": flashcards, "errors": errors}
                deck = existing_deck
                logger.info(f"[flashcard_graph] Using existing deck: {deck_id}")
            else:
                # Create new deck
                deck = FlashcardDeck(
                    name=deck_name
                    or f"Auto-generated {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    description=deck_description
                    or f"Generated from notebook content ({len(flashcards)} cards)",
                    notebook_id=notebook_id,
                    auto_generated=True,
                )
                await deck.save()
                deck_id = deck.id
                logger.info(f"[flashcard_graph] Created deck: {deck_id}")

            # Create flashcards with SRS initialization
            valid_card_types = {"basic", "cloze", "reverse", "multiple_choice"}
            for i, card_data in enumerate(flashcards):
                logger.info(f"[flashcard_graph] Saving card {i+1}/{len(flashcards)} to deck {deck_id}")
                try:
                    raw_type = card_data.get("card_type", "basic")
                    card_type = raw_type if raw_type in valid_card_types else "basic"
                    card = Flashcard(
                        deck_id=deck_id,
                        card_type=card_type,
                        question=card_data.get("question", ""),
                        answer=card_data.get("answer", ""),
                        cloze_text=card_data.get("cloze_text"),
                        hints=card_data.get("hints", []),
                        explanation=card_data.get("explanation", ""),
                        difficulty=card_data.get("difficulty", "medium") if card_data.get("difficulty") in {"easy", "medium", "hard"} else "medium",
                        tags=card_data.get("tags", []),
                        source_references=[],
                    )
                    await card.save()
                    logger.info(f"[flashcard_graph] Card {i+1} saved successfully")
                except Exception as card_err:
                    logger.error(f"[flashcard_graph] Card {i+1} save FAILED: {card_err}")
                    logger.exception(card_err)
                    errors.append(f"Card {i+1} save failed: {str(card_err)}")

            logger.info(
                f"[flashcard_graph] Saved {len(flashcards)} cards to deck {deck_id}"
            )

        except Exception as e:
            logger.error(f"[flashcard_graph] Failed to save to database: {e}")
            logger.exception(e)
            errors.append(f"Database save failed: {str(e)}")

    return {
        "deck_id": deck_id,
        "flashcards": flashcards,
        "errors": errors,
    }
