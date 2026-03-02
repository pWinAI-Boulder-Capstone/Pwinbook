"""langgraph workflow for agentic podcast generation (phase 2: director + writer + reviewer + compliance)
"""

import operator
from typing import Annotated, Any, Dict, List, Optional

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from loguru import logger
from typing_extensions import TypedDict

from open_notebook.agents.compliance import compliance_agent
from open_notebook.agents.director import director_agent
from open_notebook.agents.reviewer import reviewer_agent
from open_notebook.agents.writer import writer_agent
from open_notebook.domain.agentic_podcast import (
    AgenticPodcastWorkflow,
    ComplianceOutput,
    DirectorOutput,
    OutlineSegment,
    ReviewerOutput,
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
    max_turns: int
    target_words_per_turn: Optional[int]
    target_duration_minutes: Optional[int]

    # Model configuration
    outline_model: Optional[str]
    transcript_model: Optional[str]
    reviewer_model: Optional[str]
    compliance_model: Optional[str]

    # Agent outputs
    director_output: Optional[DirectorOutput]
    writer_outputs: Annotated[List[WriterOutput], operator.add]
    reviewer_output: Optional[ReviewerOutput]
    compliance_output: Optional[ComplianceOutput]

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
    max_turns: int
    target_words_per_turn: Optional[int]
    target_duration_minutes: Optional[int]


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
                    "max_turns": state.get("max_turns", 20),
                    "target_words_per_turn": state.get("target_words_per_turn"),
                    "target_duration_minutes": state.get("target_duration_minutes"),
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
            max_turns=state.get("max_turns", 20),
            target_words_per_turn=state.get("target_words_per_turn"),
            target_duration_minutes=state.get("target_duration_minutes"),
            num_segments=len(state["outline_segments"]),
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


async def run_reviewer(
    state: AgenticPodcastState, config: RunnableConfig
) -> Dict[str, Any]:
    """execute the Reviewer agent to evaluate and revise the transcript

    The reviewer receives the combined transcript from all writer segments,
    checks it against the source content and outline, and produces a revised
    version with quality scores.

    Args:
        state: Current workflow state
        config: Runnable configuration

    Returns:
        updated state with reviewer_output
    """
    logger.info(f"Running Reviewer agent for workflow {state['workflow_id']}")

    try:
        workflow = await AgenticPodcastWorkflow.get(state["workflow_id"])
        await workflow.update_stage("reviewer", "in_progress")

        # combine all writer outputs into a single transcript
        writer_outputs = state.get("writer_outputs", [])
        sorted_outputs = sorted(writer_outputs, key=lambda x: x.segment_index)
        combined_transcript = []
        for wo in sorted_outputs:
            combined_transcript.extend(wo.transcript)

        # get the outline segments from director output
        director_output = state["director_output"]
        outline_segments = director_output.segments if director_output else []

        reviewer_output = await reviewer_agent(
            transcript=combined_transcript,
            content=state["content"],
            briefing=state["briefing"],
            speakers=state["speakers"],
            outline_segments=outline_segments,
            model_name=state.get("reviewer_model"),
        )

        # save reviewer output to workflow
        workflow.set_reviewer_output(reviewer_output)
        await workflow.save()

        logger.info(
            f"Reviewer completed: score={reviewer_output.overall_score}, "
            f"issues={len(reviewer_output.issues)}"
        )

        return {
            "reviewer_output": reviewer_output,
            "current_stage": "compliance",
        }

    except Exception as e:
        error_msg = f"Reviewer agent failed: {str(e)}"
        logger.error(error_msg)
        logger.exception(e)

        # reviewer failure is non-fatal — we can proceed without a revised transcript
        logger.warning("Proceeding to compliance with original writer transcript")
        return {
            "errors": [error_msg],
            "current_stage": "compliance",
        }


async def run_compliance(
    state: AgenticPodcastState, config: RunnableConfig
) -> Dict[str, Any]:
    """execute the Compliance agent for final safety and quality gate

    Checks the best available transcript (reviewer-revised or original writer output)
    for safety, bias, misinformation, and other compliance concerns.

    Args:
        state: Current workflow state
        config: Runnable configuration

    Returns:
        updated state with compliance_output
    """
    logger.info(f"Running Compliance agent for workflow {state['workflow_id']}")

    try:
        workflow = await AgenticPodcastWorkflow.get(state["workflow_id"])
        await workflow.update_stage("compliance", "in_progress")

        # use the reviewer's revised transcript if available, else the raw writer outputs
        reviewer_output = state.get("reviewer_output")
        if reviewer_output and reviewer_output.revised_transcript:
            transcript = reviewer_output.revised_transcript
            reviewer_summary = reviewer_output.summary
        else:
            writer_outputs = state.get("writer_outputs", [])
            sorted_outputs = sorted(writer_outputs, key=lambda x: x.segment_index)
            transcript = []
            for wo in sorted_outputs:
                transcript.extend(wo.transcript)
            reviewer_summary = None

        compliance_output = await compliance_agent(
            transcript=transcript,
            content=state["content"],
            briefing=state["briefing"],
            speakers=state["speakers"],
            reviewer_summary=reviewer_summary,
            model_name=state.get("compliance_model"),
        )

        # save compliance output to workflow
        workflow.set_compliance_output(compliance_output)
        await workflow.save()

        logger.info(
            f"Compliance completed: approved={compliance_output.approved}, "
            f"risk={compliance_output.overall_risk_level}"
        )

        return {
            "compliance_output": compliance_output,
            "current_stage": "completed",
        }

    except Exception as e:
        error_msg = f"Compliance agent failed: {str(e)}"
        logger.error(error_msg)
        logger.exception(e)

        # compliance failure is non-fatal — still save the workflow
        logger.warning("Proceeding to save without compliance check")
        return {
            "errors": [error_msg],
            "current_stage": "completed",
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
    1. START → run_director (create outline)
    2. run_director → trigger_segment_writers (fan out)
    3. trigger_segment_writers → write_segment (parallel execution)
    4. write_segment → run_reviewer (evaluate and revise transcript)
    5. run_reviewer → run_compliance (safety and quality gate)
    6. run_compliance → save_workflow (persist results)
    7. save_workflow → END

    Returns:
        compiled stategraph ready for execution
    """
    # create the graph
    workflow = StateGraph(AgenticPodcastState)

    # add nodes
    workflow.add_node("run_director", run_director)
    workflow.add_node("write_segment", write_segment)
    workflow.add_node("run_reviewer", run_reviewer)
    workflow.add_node("run_compliance", run_compliance)
    workflow.add_node("save_workflow", save_workflow)

    # add edges
    workflow.add_edge(START, "run_director")

    # conditional edge for fan-out to writers
    workflow.add_conditional_edges(
        "run_director",
        trigger_segment_writers,
        ["write_segment"],
    )

    # all segment writers converge to reviewer
    workflow.add_edge("write_segment", "run_reviewer")

    # reviewer feeds into compliance
    workflow.add_edge("run_reviewer", "run_compliance")

    # compliance feeds into save
    workflow.add_edge("run_compliance", "save_workflow")

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
    max_turns: int = 20,
    target_words_per_turn: Optional[int] = None,
    target_duration_minutes: Optional[int] = None,
    outline_model: Optional[str] = None,
    transcript_model: Optional[str] = None,
    reviewer_model: Optional[str] = None,
    compliance_model: Optional[str] = None,
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
        max_turns: Max dialogue turns per segment (default: 20)
        target_words_per_turn: Target words per turn for duration control
        target_duration_minutes: Target podcast duration in minutes
        outline_model: Optional model override for Director
        transcript_model: Optional model override for Writer
        reviewer_model: Optional model override for Reviewer
        compliance_model: Optional model override for Compliance

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
        "max_turns": max_turns,
        "target_words_per_turn": target_words_per_turn,
        "target_duration_minutes": target_duration_minutes,
        "outline_model": outline_model,
        "transcript_model": transcript_model,
        "reviewer_model": reviewer_model,
        "compliance_model": compliance_model,
        "director_output": None,
        "writer_outputs": [],
        "reviewer_output": None,
        "compliance_output": None,
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
