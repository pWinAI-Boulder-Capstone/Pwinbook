import asyncio
import concurrent.futures
import json
import sqlite3
from typing import Annotated, Dict, List, Optional

from ai_prompter import Prompter
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from loguru import logger
from typing_extensions import TypedDict

from open_notebook.config import LANGGRAPH_CHECKPOINT_FILE
from open_notebook.domain.notebook import Source, SourceInsight
from open_notebook.graphs.utils import provision_langchain_model
from open_notebook.utils.context_builder import ContextBuilder
from open_notebook.utils.openrouter_api import edit_image, generate_image, generate_images

IMAGE_GALLERY_PREFIX = "__IMAGE_GALLERY__:"


# System prompt for classifying user intent (text vs image vs image edit)
CLASSIFY_INTENT_SYSTEM = """You classify the user's request into one of three categories.
Reply with exactly one word: TEXT, IMAGE, or IMAGE_EDIT.
- TEXT: the user is asking a question, wants an explanation, summary, or general conversation about the document.
- IMAGE: the user wants to generate a new image, chart, graph, diagram, illustration, or picture (e.g. "draw a bar chart of my revenue", "generate an image of...", "create a graph showing...").
- IMAGE_EDIT: the user wants to modify, add to, or change the previously generated image (e.g. "add the sun", "remove the chart title", "make the background blue"). They are referring to the last image created in this chat.
Reply with only TEXT, IMAGE, or IMAGE_EDIT, nothing else."""

# Marker when the document does not contain data needed for the requested chart/graph
NO_RELEVANT_CONTENT_MARKER = "[NO_RELEVANT_CONTENT]"

# System prompt for building an image-generation prompt from source content + user request
IMAGE_PROMPT_REFINER_SYSTEM = """You are a prompt writer for an image generation model.

Given the document content below and the user's image request, write a single, detailed prompt that an image model can use to generate the image.
- Include specific data, numbers, or facts from the document when the user asks for images, charts, graphs, or data visualizations.
- Be concrete and visual (style, layout, labels) so the image model produces a good result.
- Output only the image prompt, no explanation or preamble.
- If the document does not contain relevant information to fulfill the user's request, reply with "[NO_RELEVANT_CONTENT]" followed by a brief explanation (e.g. "the document does not contain any data about revenue, so I cannot create a revenue chart"). Do not attempt to generate an image in this case."""

IMAGE_EDIT_REFINER_SYSTEM = """You are a prompt writer for an image generation model.

You are given the prompt that was used to generate the PREVIOUS image, and the user's request to CHANGE that image (add something, remove something, alter style, etc.).

Your task: write a single, detailed prompt that describes the NEW image—i.e. the previous scene with the user's requested change applied.
- Preserve the rest of the scene (subject, style, setting) from the original prompt.
- Apply only the change the user asked for (e.g. "add the sun" → include a sun in the scene; "remove the lion" → describe the same scene without the lion).
- Be concrete and visual so the image model produces a good result.
- Output only the new image prompt, no explanation or preamble."""


class SourceChatState(TypedDict):
    messages: Annotated[list, add_messages]
    source_id: str
    source: Optional[Source]
    insights: Optional[List[SourceInsight]]
    context: Optional[str]
    model_override: Optional[str]
    context_indicators: Optional[Dict[str, List[str]]]
    intent: Optional[str]
    last_image_prompt: Optional[str]  
    max_images: Optional[int]
    last_image_data_url: Optional[str]


def _run_async_in_sync(coro_fn):
    """Run an async function from sync context (graph nodes) using a new event loop."""
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


def classify_intent(state: SourceChatState, config: RunnableConfig) -> dict:
    """
    Classify the user's last message as TEXT (question/explanation) or IMAGE (generate image/chart).
    Sets state["intent"] to "text" or "image" for conditional routing.
    """
    messages = state.get("messages") or []
    user_content = ""
    for m in reversed(messages):
        if hasattr(m, "type") and getattr(m, "type", None) == "human":
            user_content = getattr(m, "content", "") or str(m)
            break
    if not (user_content and user_content.strip()):
        return {"intent": "text"}

    def _classify():
        async def _run():
            model = await provision_langchain_model(
                user_content[:500],
                config.get("configurable", {}).get("model_id") or state.get("model_override"),
                "chat",
                max_tokens=20,
            )
            response = model.invoke([
                SystemMessage(content=CLASSIFY_INTENT_SYSTEM),
                HumanMessage(content=user_content[:2000]),
            ])
            raw = (getattr(response, "content", None) or str(response)).strip().upper()
            if "IMAGE_EDIT" in raw:
                return "image_edit"
            if "IMAGE" in raw:
                return "image"
            return "text"

        return _run()

    try:
        intent = _run_async_in_sync(_classify)
        logger.info(f"[Image flow] Step 1 – Intent classification: user message → LLM → intent = {intent!r}")
    except Exception as e:
        logger.warning(f"Intent classification failed, defaulting to text: {e}")
        intent = "text"
    return {"intent": intent}


def call_source_image_agent(state: SourceChatState, config: RunnableConfig) -> dict:
    """
    Build source context, use an LLM to create an image prompt from document + user request,
    call the image generation API, and return the image (data URL) as the AI message.
    """
    source_id = state.get("source_id")
    if not source_id:
        raise ValueError("source_id is required in state")

    # Build source context (same as text agent)
    def build_context():
        new_loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(new_loop)
            context_builder = ContextBuilder(
                source_id=source_id,
                include_insights=True,
                include_notes=False,
                max_tokens=50000,
            )
            return new_loop.run_until_complete(context_builder.build())
        finally:
            new_loop.close()
            asyncio.set_event_loop(None)

    try:
        asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(build_context)
            context_data = future.result()
    except RuntimeError:
        context_data = build_context()

    source = None
    insights = []
    context_indicators: dict[str, list[str | None]] = {
        "sources": [],
        "insights": [],
        "notes": [],
    }
    if context_data.get("sources"):
        source_info = context_data["sources"][0]
        source = Source(**source_info) if isinstance(source_info, dict) else source_info
        context_indicators["sources"].append(source.id)
    if context_data.get("insights"):
        for insight_data in context_data["insights"]:
            insight = (
                SourceInsight(**insight_data)
                if isinstance(insight_data, dict)
                else insight_data
            )
            insights.append(insight)
            context_indicators["insights"].append(insight.id)

    formatted_context = _format_source_context(context_data)
    logger.info(f"[Image flow] Step 2 – Source context built: {len(formatted_context)} chars of document/insights")

    user_content = ""
    for m in reversed(state.get("messages") or []):
        if hasattr(m, "type") and getattr(m, "type", None) == "human":
            user_content = getattr(m, "content", "") or str(m)
            break

    # Refine prompt using LLM: document + user request -> single image prompt
    def get_refined_prompt():
        async def _run():
            model = await provision_langchain_model(
                formatted_context[:1000] + user_content[:500],
                config.get("configurable", {}).get("model_id") or state.get("model_override"),
                "chat",
                max_tokens=1024,
            )
            user_msg = f"Document content:\n{formatted_context[:15000]}\n\nUser request: {user_content}"
            response = model.invoke([
                SystemMessage(content=IMAGE_PROMPT_REFINER_SYSTEM),
                HumanMessage(content=user_msg),
            ])
            return (getattr(response, "content", None) or str(response)).strip()

        return _run()

    try:
        refined_prompt = _run_async_in_sync(get_refined_prompt)
        logger.info(
            "[Image flow] Step 3 – Refiner LLM: document + user request → single image prompt. "
            f"Refined prompt ({len(refined_prompt)} chars): {refined_prompt[:300]!r}{'...' if len(refined_prompt) > 300 else ''}"
        )
    except Exception as e:
        logger.warning(f"Image prompt refiner failed, using user message: {e}")
        refined_prompt = user_content or "Generate an image based on the document."
        logger.info(f"[Image flow] Step 3 (fallback) – Using user message as prompt: {refined_prompt[:200]!r}...")

    # If document doesn't contain the requested data, return text message instead of generating image
    if refined_prompt.strip().upper().startswith(NO_RELEVANT_CONTENT_MARKER.upper()):
        message_part = refined_prompt[len(NO_RELEVANT_CONTENT_MARKER):].strip()
        no_content_msg = (
            message_part
            if message_part
            else "There is no relevant content in your source for this request."
        )
        logger.info(f"[Image flow] Step 3 – No relevant content in document; returning message instead of image: {no_content_msg[:150]!r}")
        ai_message = AIMessage(content=no_content_msg)
        return {
            "messages": ai_message,
            "source": source,
            "insights": insights,
            "context": formatted_context,
            "context_indicators": context_indicators,
        }

    # Generate image via OpenRouter
    def do_generate():
        async def _run():
            max_images = state.get("max_images") or 1
            return await generate_images(refined_prompt, max_images=max_images)

        return _run()

    result = _run_async_in_sync(do_generate)
    # result is either list[data_url] or an error string
    if isinstance(result, list) and result:
        if len(result) == 1:
            single = result[0]
            logger.info(f"[Image flow] Step 4 – Image generated successfully (data URL length {len(single)})")
            return {
                "messages": AIMessage(content=single),
                "source": source,
                "insights": insights,
                "context": formatted_context,
                "context_indicators": context_indicators,
                "last_image_prompt": refined_prompt,
                "last_image_data_url": single,
            }
        payload = {
            "type": "image_gallery",
            "images": result,
            "selected_index": 0,
        }
        logger.info(f"[Image flow] Step 4 – Generated image gallery with {len(result)} images")
        return {
            "messages": AIMessage(content=f"{IMAGE_GALLERY_PREFIX}{json.dumps(payload)}"),
            "source": source,
            "insights": insights,
            "context": formatted_context,
            "context_indicators": context_indicators,
            "last_image_prompt": refined_prompt,
            "last_image_data_url": result[0],
        }
    elif isinstance(result, str):
        logger.warning(f"[Image flow] Step 4 – Image generation returned error: {result[:200]!r}")
        ai_message = AIMessage(content=result)
    else:
        ai_message = AIMessage(content="Image generation failed unexpectedly.")
    return {
        "messages": ai_message,
        "source": source,
        "insights": insights,
        "context": formatted_context,
        "context_indicators": context_indicators,
    }


def _get_last_image_data_url(messages: list) -> Optional[str]:
    """Return the content of the most recent AI message that is an image (data URL)."""
    for m in reversed(messages or []):
        if getattr(m, "type", None) != "ai":
            continue
        content = getattr(m, "content", None) or ""
        if isinstance(content, str) and content.strip().startswith("data:image/"):
            return content
    return None


def call_source_image_edit_agent(state: SourceChatState, config: RunnableConfig) -> dict:
    """
    Edit the last generated image. Tries pixel-based edit first (send image + instruction);
    if that fails or no image in thread, falls back to re-prompt (refiner + generate).
    """
    messages = state.get("messages") or []
    user_content = ""
    for m in reversed(messages):
        if hasattr(m, "type") and getattr(m, "type", None) == "human":
            user_content = getattr(m, "content", "") or str(m)
            break
    if not (user_content and user_content.strip()):
        return {"messages": AIMessage(content="What would you like to change in the previous image?")}

    last_image_url = state.get("last_image_data_url") or _get_last_image_data_url(messages)
    pixel_edit_error: Optional[str] = None

    if last_image_url:
        def do_edit():
            async def _run():
                return await edit_image(last_image_url, user_content)
            return _run()

        result = _run_async_in_sync(do_edit)
        if result.startswith("data:image/"):
            logger.info(f"[Image edit] Pixel edit succeeded, data URL length {len(result)}")
            return {"messages": AIMessage(content=result), "last_image_data_url": result}
        pixel_edit_error = result

    last_prompt = state.get("last_image_prompt") or ""
    if not last_prompt.strip():
        msg = (
            "I don't have a previous image to edit. Generate an image first, then ask to modify it (e.g. 'add the sun')."
        )
        if pixel_edit_error:
            msg += f" (Pixel edit was not supported: {pixel_edit_error[:200]})"
        return {"messages": AIMessage(content=msg)}

    def get_edit_prompt():
        async def _run():
            model = await provision_langchain_model(
                last_prompt[:500] + user_content[:500],
                config.get("configurable", {}).get("model_id") or state.get("model_override"),
                "chat",
                max_tokens=1024,
            )
            user_msg = (
                f"Previous image prompt:\n{last_prompt}\n\n"
                f"User wants to change the image: {user_content}"
            )
            response = model.invoke([
                SystemMessage(content=IMAGE_EDIT_REFINER_SYSTEM),
                HumanMessage(content=user_msg),
            ])
            return (getattr(response, "content", None) or str(response)).strip()
        return _run()

    try:
        new_prompt = _run_async_in_sync(get_edit_prompt)
        logger.info(f"[Image edit] New prompt length: {len(new_prompt)}")
    except Exception as e:
        logger.warning(f"Image edit refiner failed: {e}")
        new_prompt = f"{last_prompt}. {user_content}"

    def do_generate():
        async def _run():
            return await generate_image(new_prompt)
        return _run()

    result = _run_async_in_sync(do_generate)
    if result.startswith("data:image/"):
        logger.info(f"[Image edit] Image generated, data URL length {len(result)}")
        return {
            "messages": AIMessage(content=result),
            "last_image_prompt": new_prompt,
            "last_image_data_url": result,
        }
    logger.warning(f"[Image edit] Generation returned: {result[:150]!r}")
    return {"messages": AIMessage(content=result)}


def call_model_with_source_context(
    state: SourceChatState, config: RunnableConfig
) -> dict:
    """
    Main function that builds source context and calls the model.

    This function:
    1. Uses ContextBuilder to build source-specific context
    2. Applies the source_chat Jinja2 prompt template
    3. Handles model provisioning with override support
    4. Tracks context indicators for referenced insights/content
    """
    source_id = state.get("source_id")
    if not source_id:
        raise ValueError("source_id is required in state")

    # Build source context using ContextBuilder (run async code in new loop)
    def build_context():
        """Build context in a new event loop"""
        new_loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(new_loop)
            context_builder = ContextBuilder(
                source_id=source_id,
                include_insights=True,
                include_notes=False,  
                max_tokens=50000, 
            )
            return new_loop.run_until_complete(context_builder.build())
        finally:
            new_loop.close()
            asyncio.set_event_loop(None)

    # Get the built context
    try:
      
        asyncio.get_running_loop()
        
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(build_context)
            context_data = future.result()
    except RuntimeError:
      
        context_data = build_context()

    # Extract source and insights from context
    source = None
    insights = []
    context_indicators: dict[str, list[str | None]] = {
        "sources": [],
        "insights": [],
        "notes": [],
    }

    if context_data.get("sources"):
        source_info = context_data["sources"][0] 
        source = Source(**source_info) if isinstance(source_info, dict) else source_info
        context_indicators["sources"].append(source.id)

    if context_data.get("insights"):
        for insight_data in context_data["insights"]:
            insight = (
                SourceInsight(**insight_data)
                if isinstance(insight_data, dict)
                else insight_data
            )
            insights.append(insight)
            context_indicators["insights"].append(insight.id)

    # Format context for the prompt
    formatted_context = _format_source_context(context_data)

    # Build prompt data for the template
    prompt_data = {
        "source": source.model_dump() if source else None,
        "insights": [insight.model_dump() for insight in insights] if insights else [],
        "context": formatted_context,
        "context_indicators": context_indicators,
    }

    # Apply the source_chat prompt template
    system_prompt = Prompter(prompt_template="source_chat").render(data=prompt_data)
    payload = [SystemMessage(content=system_prompt)] + state.get("messages", [])

    # Handle async model provisioning from sync context
    def run_in_new_loop():
        """Run the async function in a new event loop"""
        new_loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(new_loop)
            return new_loop.run_until_complete(
                provision_langchain_model(
                    str(payload),
                    config.get("configurable", {}).get("model_id")
                    or state.get("model_override"),
                    "chat",
                    max_tokens=4096,
                )
            )
        finally:
            new_loop.close()
            asyncio.set_event_loop(None)

    try:
        # Try to get the current event loop
        asyncio.get_running_loop()
        # If we're in an event loop, run in a thread with a new loop
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(run_in_new_loop)
            model = future.result()
    except RuntimeError:
        # No event loop running, safe to use asyncio.run()
        model = asyncio.run(
            provision_langchain_model(
                str(payload),
                config.get("configurable", {}).get("model_id")
                or state.get("model_override"),
                "chat",
                max_tokens=4096,
            )
        )

    ai_message = model.invoke(payload)

    # Update state with context information
    return {
        "messages": ai_message,
        "source": source,
        "insights": insights,
        "context": formatted_context,
        "context_indicators": context_indicators,
    }


def _format_source_context(context_data: Dict) -> str:
    """
    Format the context data into a readable string for the prompt.

    Args:
        context_data: Context data from ContextBuilder

    Returns:
        Formatted context string
    """
    context_parts = []

    # Add source information
    if context_data.get("sources"):
        context_parts.append("## SOURCE CONTENT")
        for source in context_data["sources"]:
            if isinstance(source, dict):
                context_parts.append(f"**Source ID:** {source.get('id', 'Unknown')}")
                context_parts.append(f"**Title:** {source.get('title', 'No title')}")
                if source.get("full_text"):
                    # Truncate full text if too long
                    full_text = source["full_text"]
                    if len(full_text) > 5000:
                        full_text = full_text[:5000] + "...\n[Content truncated]"
                    context_parts.append(f"**Content:**\n{full_text}")
                context_parts.append("")  # Empty line for separation

    # Add insights
    if context_data.get("insights"):
        context_parts.append("## SOURCE INSIGHTS")
        for insight in context_data["insights"]:
            if isinstance(insight, dict):
                context_parts.append(f"**Insight ID:** {insight.get('id', 'Unknown')}")
                context_parts.append(
                    f"**Type:** {insight.get('insight_type', 'Unknown')}"
                )
                context_parts.append(
                    f"**Content:** {insight.get('content', 'No content')}"
                )
                context_parts.append("")  

    # Add metadata
    if context_data.get("metadata"):
        metadata = context_data["metadata"]
        context_parts.append("## CONTEXT METADATA")
        context_parts.append(f"- Source count: {metadata.get('source_count', 0)}")
        context_parts.append(f"- Insight count: {metadata.get('insight_count', 0)}")
        context_parts.append(f"- Total tokens: {context_data.get('total_tokens', 0)}")
        context_parts.append("")

    return "\n".join(context_parts)


# Create SQLite checkpointer
conn = sqlite3.connect(
    LANGGRAPH_CHECKPOINT_FILE,
    check_same_thread=False,
)
memory = SqliteSaver(conn)

def _route_by_intent(state: SourceChatState, config: RunnableConfig) -> str:
    """Return the next node name from router state."""
    return state.get("intent") or "text"


# Create the StateGraph
source_chat_state = StateGraph(SourceChatState)
source_chat_state.add_node("router", classify_intent)
source_chat_state.add_node("source_chat_agent", call_model_with_source_context)
source_chat_state.add_node("source_image_agent", call_source_image_agent)
source_chat_state.add_node("source_image_edit_agent", call_source_image_edit_agent)
source_chat_state.add_edge(START, "router")
source_chat_state.add_conditional_edges(
    "router",
    _route_by_intent,
    {
        "text": "source_chat_agent",
        "image": "source_image_agent",
        "image_edit": "source_image_edit_agent",
    },
)
source_chat_state.add_edge("source_chat_agent", END)
source_chat_state.add_edge("source_image_agent", END)
source_chat_state.add_edge("source_image_edit_agent", END)
source_chat_graph = source_chat_state.compile(checkpointer=memory)
