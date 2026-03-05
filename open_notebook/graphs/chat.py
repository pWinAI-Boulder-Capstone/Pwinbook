import asyncio
import concurrent.futures
import sqlite3
from typing import Annotated, Any, Dict, Optional

from ai_prompter import Prompter
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from loguru import logger
from typing_extensions import TypedDict

from open_notebook.config import LANGGRAPH_CHECKPOINT_FILE
from open_notebook.domain.notebook import Notebook
from open_notebook.graphs.utils import provision_langchain_model
from open_notebook.utils.openrouter_image import edit_image, generate_image

# Intent classification (text vs image vs image edit) for notebook chat
CLASSIFY_INTENT_SYSTEM = """You classify the user's request into one of three categories.
Reply with exactly one word: TEXT, IMAGE, or IMAGE_EDIT.
- TEXT: the user is asking a question, wants an explanation, summary, or general conversation about the documents.
- IMAGE: the user wants to generate a new image, chart, graph, diagram, illustration, or picture (e.g. "draw a bar chart", "generate an image of...", "create a graph showing...").
- IMAGE_EDIT: the user wants to modify, add to, or change the previously generated image (e.g. "add the sun", "add a sun in the sky", "remove the lion", "make the sky darker", "put a bird in the tree"). They are referring to the last image that was created in this chat.
Reply with only TEXT, IMAGE, or IMAGE_EDIT, nothing else."""

NO_RELEVANT_CONTENT_MARKER = "[NO_RELEVANT_CONTENT]"

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



class ThreadState(TypedDict):
    messages: Annotated[list, add_messages]
    notebook: Optional[Notebook]
    context: Optional[Any]  
    context_config: Optional[dict]
    model_override: Optional[str]
    intent: Optional[str]
    last_image_prompt: Optional[str]  


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


def _format_notebook_context(context_data: Dict[str, Any]) -> str:
    """Format notebook context dict (sources + notes) into a single string for the refiner LLM."""
    if not context_data:
        return ""
    parts = []
    for source in context_data.get("sources") or []:
        if isinstance(source, dict):
            parts.append("## SOURCE")
            parts.append(f"**ID:** {source.get('id', '')}")
            parts.append(f"**Title:** {source.get('title', '')}")
            if source.get("insights"):
                parts.append("**Insights:**")
                for ins in (source["insights"] if isinstance(source["insights"], list) else []):
                    if isinstance(ins, dict):
                        parts.append(f"  - {ins.get('content', ins)}")
                    else:
                        parts.append(f"  - {ins}")
            if source.get("full_text"):
                text = source["full_text"]
                if len(text) > 5000:
                    text = text[:5000] + "\n...[truncated]"
                parts.append(f"**Content:**\n{text}")
            parts.append("")
    for note in context_data.get("notes") or []:
        if isinstance(note, dict):
            parts.append("## NOTE")
            parts.append(f"**ID:** {note.get('id', '')}")
            parts.append(f"**Title:** {note.get('title', '')}")
            if note.get("content"):
                parts.append(f"**Content:**\n{note['content']}")
            parts.append("")
    return "\n".join(parts).strip()


def classify_intent_notebook(state: ThreadState, config: RunnableConfig) -> dict:
    """Classify the user's last message as TEXT or IMAGE for notebook chat."""
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
        logger.info(f"[Notebook image flow] Intent classification: {intent!r}")
    except Exception as e:
        logger.warning(f"Notebook intent classification failed, defaulting to text: {e}")
        intent = "text"
    return {"intent": intent}


def call_notebook_image_agent(state: ThreadState, config: RunnableConfig) -> dict:
    """
    Build image prompt from notebook context + user request via refiner LLM,
    then generate image (or return no-relevant-content message).
    """
    context_raw = state.get("context")
    if not context_raw or not isinstance(context_raw, dict):
        msg = "There is no relevant content in your source for this request."
        return {"messages": AIMessage(content=msg)}

    formatted_context = _format_notebook_context(context_raw)
    if not formatted_context.strip():
        msg = "There is no relevant content in your source for this request."
        return {"messages": AIMessage(content=msg)}

    user_content = ""
    for m in reversed(state.get("messages") or []):
        if hasattr(m, "type") and getattr(m, "type", None) == "human":
            user_content = getattr(m, "content", "") or str(m)
            break

    def get_refined_prompt():
        async def _run():
            model = await provision_langchain_model(
                formatted_context[:1000] + user_content[:500],
                config.get("configurable", {}).get("model_id") or state.get("model_override"),
                "chat",
                max_tokens=1024,
            )
            user_msg = f"Context:\n{formatted_context[:15000]}\n\nUser request: {user_content}"
            response = model.invoke([
                SystemMessage(content=IMAGE_PROMPT_REFINER_SYSTEM),
                HumanMessage(content=user_msg),
            ])
            return (getattr(response, "content", None) or str(response)).strip()
        return _run()

    try:
        refined_prompt = _run_async_in_sync(get_refined_prompt)
        logger.info(f"[Notebook image flow] Refined prompt length: {len(refined_prompt)}")
    except Exception as e:
        logger.warning(f"Notebook image refiner failed: {e}")
        refined_prompt = user_content or "Generate an image based on the context."

    if refined_prompt.strip().upper().startswith(NO_RELEVANT_CONTENT_MARKER.upper()):
        message_part = refined_prompt[len(NO_RELEVANT_CONTENT_MARKER):].strip()
        no_content_msg = message_part or "There is no relevant content in your source for this request."
        logger.info(f"[Notebook image flow] No relevant content, returning message")
        return {"messages": AIMessage(content=no_content_msg)}

    def do_generate():
        async def _run():
            return await generate_image(refined_prompt)
        return _run()

    result = _run_async_in_sync(do_generate)
    if result.startswith("data:image/"):
        logger.info(f"[Notebook image flow] Image generated, data URL length {len(result)}")
        return {"messages": AIMessage(content=result), "last_image_prompt": refined_prompt}
    else:
        logger.warning(f"[Notebook image flow] Image generation returned: {result[:150]!r}")
    return {"messages": AIMessage(content=result)}


def _get_last_image_data_url(messages: list) -> Optional[str]:
    """Return the content of the most recent AI message that is an image (data URL)."""
    for m in reversed(messages or []):
        if getattr(m, "type", None) != "ai":
            continue
        content = getattr(m, "content", None) or ""
        if isinstance(content, str) and content.strip().startswith("data:image/"):
            return content
    return None


def call_notebook_image_edit_agent(state: ThreadState, config: RunnableConfig) -> dict:
    """
    Edit the last generated image. Tries pixel-based edit first (send image + instruction
    to the model); if that fails or no image in thread, falls back to re-prompt (refiner
    + generate from new text prompt).
    """
    messages = state.get("messages") or []
    user_content = ""
    for m in reversed(messages):
        if hasattr(m, "type") and getattr(m, "type", None) == "human":
            user_content = getattr(m, "content", "") or str(m)
            break
    if not (user_content and user_content.strip()):
        return {"messages": AIMessage(content="What would you like to change in the previous image?")}

    last_image_url = _get_last_image_data_url(messages)
    pixel_edit_error: Optional[str] = None

    # 1) Try pixel-based edit when we have the last image in the thread
    if last_image_url:
        def do_edit():
            async def _run():
                return await edit_image(last_image_url, user_content)
            return _run()

        result = _run_async_in_sync(do_edit)
        if result.startswith("data:image/"):
            logger.info(f"[Notebook image edit] Pixel edit succeeded, data URL length {len(result)}")
            return {"messages": AIMessage(content=result)}
        pixel_edit_error = result

    # 2) Fallback: edit by re-prompt (refiner + generate)
    last_prompt = state.get("last_image_prompt") or ""
    if not last_prompt.strip():
        msg = (
            "I don't have a previous image to edit. Generate an image first (e.g. "
            "'draw a lion in a forest'), then ask to modify it (e.g. 'add the sun')."
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
        logger.info(f"[Notebook image edit] New prompt length: {len(new_prompt)}")
    except Exception as e:
        logger.warning(f"Notebook image edit refiner failed: {e}")
        new_prompt = f"{last_prompt}. {user_content}"

    def do_generate():
        async def _run():
            return await generate_image(new_prompt)
        return _run()

    result = _run_async_in_sync(do_generate)
    if result.startswith("data:image/"):
        logger.info(f"[Notebook image edit] Image generated, data URL length {len(result)}")
        return {"messages": AIMessage(content=result), "last_image_prompt": new_prompt}
    logger.warning(f"[Notebook image edit] Generation returned: {result[:150]!r}")
    return {"messages": AIMessage(content=result)}


def _route_by_intent(state: ThreadState, config: RunnableConfig) -> str:
    return state.get("intent") or "text"


def call_model_with_messages(state: ThreadState, config: RunnableConfig) -> dict:
    system_prompt = Prompter(prompt_template="chat").render(data=state)  # type: ignore[arg-type]
    payload = [SystemMessage(content=system_prompt)] + state.get("messages", [])
    model_id = config.get("configurable", {}).get("model_id") or state.get(
        "model_override"
    )

    # Handle async model provisioning from sync context
    def run_in_new_loop():
        """Run the async function in a new event loop"""
        new_loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(new_loop)
            return new_loop.run_until_complete(
                provision_langchain_model(
                    str(payload), model_id, "chat", max_tokens=4096
                )
            )
        finally:
            new_loop.close()
            asyncio.set_event_loop(None)

    try:
        # Try to get the current event loop
        asyncio.get_running_loop()
        # If we're in an event loop, run in a thread with a new loop
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(run_in_new_loop)
            model = future.result()
    except RuntimeError:
        # No event loop running, safe to use asyncio.run()
        model = asyncio.run(
            provision_langchain_model(
                str(payload),
                model_id,
                "chat",
                max_tokens=4096,
            )
        )

    ai_message = model.invoke(payload)
    return {"messages": ai_message}


conn = sqlite3.connect(
    LANGGRAPH_CHECKPOINT_FILE,
    check_same_thread=False,
)
memory = SqliteSaver(conn)

agent_state = StateGraph(ThreadState)
agent_state.add_node("router", classify_intent_notebook)
agent_state.add_node("notebook_image_agent", call_notebook_image_agent)
agent_state.add_node("notebook_image_edit_agent", call_notebook_image_edit_agent)
agent_state.add_node("agent", call_model_with_messages)
agent_state.add_edge(START, "router")
agent_state.add_conditional_edges(
    "router",
    _route_by_intent,
    {
        "text": "agent",
        "image": "notebook_image_agent",
        "image_edit": "notebook_image_edit_agent",
    },
)
agent_state.add_edge("agent", END)
agent_state.add_edge("notebook_image_agent", END)
agent_state.add_edge("notebook_image_edit_agent", END)
graph = agent_state.compile(checkpointer=memory)
