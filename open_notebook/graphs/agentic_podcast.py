"""langgraph workflow for agentic podcast generation (phase 1: director + writer)
"""

import operator
from typing import Annotated, Any, Dict, List, Optional

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from loguru import logger
from typing_extensions import TypedDict

from open_notebook.agents.director import director_agent
from open_notebook.agents.writer import writer_agent
from open_notebook.domain.agentic_podcast import (
    AgenticPodcastWorkflow,
    DirectorOutput,
    OutlineSegment,
    WriterOutput,
)


class AgenticPodcastState(TypedDict):
    """state for the agentic podcast workflow graph"""

    # Input configuration
    workflow_id: str
    content: str
    briefing: str
    speakers: List[Dict[str, Any]]
    episode_profile_name: str
    speaker_profile_name: str
    num_segments: int

    # Model configuration
    outline_model: Optional[str]
    transcript_model: Optional[str]

    # Agent outputs
    director_output: Optional[DirectorOutput]
    writer_outputs: Annotated[List[WriterOutput], operator.add]

    # Control flow
    current_stage: str
    errors: Annotated[List[str], operator.add]


class SegmentWriterState(TypedDict):
    """state for individual segment writer (sub-graph)"""

    workflow_id: str
    segment: OutlineSegment
    segment_index: int
    content: str
    briefing: str
    speakers: List[Dict[str, Any]]
    outline_segments: List[OutlineSegment]
    previous_segments: List[WriterOutput]
    transcript_model: Optional[str]


async def run_director(
    state: AgenticPodcastState, config: RunnableConfig
) -> Dict[str, Any]:
    """execute the Director agent to create the podcast outline

    Args:
        state: Current workflow state
        config: Runnable configuration

    Returns:
        updated state with director_output
    """
    logger.info(f"Running Director agent for workflow {state['workflow_id']}")

    try:
        # Get workflow to update stage
        workflow = await AgenticPodcastWorkflow.get(state["workflow_id"])
        await workflow.update_stage("director", "in_progress")

        # Run director agent
        director_output = await director_agent(
            content=state["content"],
            briefing=state["briefing"],
            speakers=state["speakers"],
            num_segments=state["num_segments"],
            model_name=state.get("outline_model"),
        )

        # Save director output to workflow
        workflow.set_director_output(director_output)
        await workflow.save()

        logger.info(
            f"Director completed: {len(director_output.segments)} segments created"
        )

        return {
            "director_output": director_output,
            "current_stage": "writer",
        }

    except Exception as e:
        error_msg = f"Director agent failed: {str(e)}"
        logger.error(error_msg)
        logger.exception(e)

        # Mark workflow as failed
        workflow = await AgenticPodcastWorkflow.get(state["workflow_id"])
        await workflow.mark_failed(error_msg)

        return {
            "errors": [error_msg],
            "current_stage": "failed",
        }


async def trigger_segment_writers(
    state: AgenticPodcastState, config: RunnableConfig
) -> List[Send]:
    """fan out to multiple segment writer nodes

    thhis creates a separate writer task for each segment in the outline,
    allowing parallel transcript generation.

    Args:
        state: Current workflow state
        config: Runnable configuration

    Returns:
        List of Send objects, one per segment
    """
    if not state.get("director_output"):
        logger.error("No director output available for writer fan-out")
        return []

    director_output = state["director_output"]
    segments = director_output.segments

    logger.info(f"Triggering {len(segments)} segment writers")

    # Create a Send for each segment
    sends = []
    for i, segment in enumerate(segments):
        sends.append(
            Send(
                "write_segment",
                {
                    "workflow_id": state["workflow_id"],
                    "segment": segment,
                    "segment_index": i,
                    "content": state["content"],
                    "briefing": state["briefing"],
                    "speakers": state["speakers"],
                    "outline_segments": segments,
                    "previous_segments": [],  # Will be populated in sequential mode
                    "transcript_model": state.get("transcript_model"),
                },
            )
        )

    return sends


async def write_segment(
    state: SegmentWriterState, config: RunnableConfig
) -> Dict[str, Any]:
    """execute the Writer agent for a single segment

    Args:
        state: Segment writer state
        config: Runnable configuration

    Returns:
        updated state with writer_output
    """
    segment_index = state["segment_index"]
    segment = state["segment"]

    logger.info(f"Running Writer agent for segment {segment_index}: '{segment.name}'")

    try:
        # Get workflow to check for previous segments
        workflow = await AgenticPodcastWorkflow.get(state["workflow_id"])

        # Get previously written segments for context (if any)
        previous_outputs = workflow.get_writer_outputs() if workflow.writer_outputs else []
        # Only use segments before this one
        previous_segments = [w for w in previous_outputs if w.segment_index < segment_index]

        # Run writer agent
        writer_output = await writer_agent(
            segment=segment,
            segment_index=segment_index,
            content=state["content"],
            briefing=state["briefing"],
            speakers=state["speakers"],
            outline_segments=state["outline_segments"],
            previous_segments=previous_segments if previous_segments else None,
            model_name=state.get("transcript_model"),
        )

        logger.info(
            f"Writer completed segment {segment_index}: {len(writer_output.transcript)} turns"
        )

        return {
            "writer_outputs": [writer_output],
        }

    except Exception as e:
        error_msg = f"Writer agent failed for segment {segment_index}: {str(e)}"
        logger.error(error_msg)
        logger.exception(e)

        return {
            "errors": [error_msg],
        }


async def save_workflow(
    state: AgenticPodcastState, config: RunnableConfig
) -> Dict[str, Any]:
    """save the completed workflow to database

    Args:
        state: Current workflow state
        config: Runnable configuration

    Returns:
        updated state marking completion
    """
    logger.info(f"Saving workflow {state['workflow_id']}")

    try:
        workflow = await AgenticPodcastWorkflow.get(state["workflow_id"])

        # Check if there were any errors
        if state.get("errors"):
            error_msg = "; ".join(state["errors"])
            await workflow.mark_failed(error_msg)
            logger.error(f"Workflow failed with errors: {error_msg}")
            return {"current_stage": "failed"}

        # Save all writer outputs
        writer_outputs = state.get("writer_outputs", [])
        if not writer_outputs:
            error_msg = "No writer outputs generated"
            await workflow.mark_failed(error_msg)
            logger.error(error_msg)
            return {"current_stage": "failed", "errors": [error_msg]}

        # Sort by segment index and save
        sorted_outputs = sorted(writer_outputs, key=lambda x: x.segment_index)
        workflow.set_writer_outputs(sorted_outputs)

        # Mark as completed
        await workflow.mark_completed()

        logger.info(
            f"Workflow {state['workflow_id']} completed successfully with {len(sorted_outputs)} segments"
        )

        return {"current_stage": "completed"}

    except Exception as e:
        error_msg = f"Failed to save workflow: {str(e)}"
        logger.error(error_msg)
        logger.exception(e)

        try:
            workflow = await AgenticPodcastWorkflow.get(state["workflow_id"])
            await workflow.mark_failed(error_msg)
        except Exception as save_error:
            logger.error(f"Failed to mark workflow as failed: {save_error}")

        return {"current_stage": "failed", "errors": [error_msg]}


def build_agentic_podcast_graph() -> StateGraph:
    """build the LangGraph workflow for agentic podcast generation

    The workflow follows this structure:
    1. START - run_director (create outline)
    2. run_director - trigger_segment_writers (fan out)
    3. trigger_segment_writers - write_segment (parallel execution)
    4. write_segment - save_workflow (collect results)
    5. save_workflow - END

    Returns:
        compiled stategraph ready for execution
    """
    # create the graph
    workflow = StateGraph(AgenticPodcastState)

    # add nodes
    workflow.add_node("run_director", run_director)
    workflow.add_node("write_segment", write_segment)
    workflow.add_node("save_workflow", save_workflow)

    # add edges
    workflow.add_edge(START, "run_director")

    # conditional edge for fan-out to writers
    workflow.add_conditional_edges(
        "run_director",
        trigger_segment_writers,
        ["write_segment"],
    )

    # all segment writers converge to save_workflow
    workflow.add_edge("write_segment", "save_workflow")
    workflow.add_edge("save_workflow", END)

    # compile the graph
    return workflow.compile()


async def run_agentic_podcast_workflow(
    workflow_id: str,
    content: str,
    briefing: str,
    speakers: List[Dict[str, Any]],
    episode_profile_name: str,
    speaker_profile_name: str,
    num_segments: int = 5,
    outline_model: Optional[str] = None,
    transcript_model: Optional[str] = None,
) -> AgenticPodcastWorkflow:
    """execute the complete agentic podcast workflow

    this is the main entry point for running the multi-agent workflow

    Args:
        workflow_id: ID of the workflow record
        content: Source content for the podcast
        briefing: Episode briefing with goals
        speakers: List of speaker profiles
        episode_profile_name: Name of episode profile
        speaker_profile_name: Name of speaker profile
        num_segments: Number of segments to create (default: 5)
        outline_model: Optional model override for Director
        transcript_model: Optional model override for Writer

    Returns:
        completed AgenticPodcastWorkflow with all outputs

    Raises:
        exception: if workflow execution fails
    """
    logger.info(f"Starting agentic podcast workflow {workflow_id}")

    # build the workflow graph
    graph = build_agentic_podcast_graph()

    # prepare the initial state
    initial_state: AgenticPodcastState = {
        "workflow_id": workflow_id,
        "content": content,
        "briefing": briefing,
        "speakers": speakers,
        "episode_profile_name": episode_profile_name,
        "speaker_profile_name": speaker_profile_name,
        "num_segments": num_segments,
        "outline_model": outline_model,
        "transcript_model": transcript_model,
        "director_output": None,
        "writer_outputs": [],
        "current_stage": "director",
        "errors": [],
    }

    # execute the workflow
    try:
        final_state = await graph.ainvoke(initial_state)

        # retrieve and return the completed workflow
        workflow = await AgenticPodcastWorkflow.get(workflow_id)

        if final_state.get("current_stage") == "failed":
            logger.error(f"Workflow {workflow_id} failed")
        else:
            logger.info(f"Workflow {workflow_id} completed successfully")

        return workflow

    except Exception as e:
        logger.error(f"Workflow {workflow_id} execution failed: {e}")
        logger.exception(e)

        # try to mark workflow as failed
        try:
            workflow = await AgenticPodcastWorkflow.get(workflow_id)
            await workflow.mark_failed(str(e))
        except Exception as save_error:
            logger.error(f"Failed to mark workflow as failed: {save_error}")

        raise
