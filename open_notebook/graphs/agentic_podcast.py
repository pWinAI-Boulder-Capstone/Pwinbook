"""langgraph workflow for agentic podcast generation (phase 2: director + writer + reviewer + fixer + compliance)
"""

import operator
from typing import Annotated, Any, Dict, List, Optional

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from loguru import logger
from typing_extensions import TypedDict

from open_notebook.agents.compliance import compliance_agent
from open_notebook.agents.director import director_agent
from open_notebook.agents.fixer import fixer_agent
from open_notebook.agents.reviewer import reviewer_agent
from open_notebook.agents.writer import writer_agent
from open_notebook.domain.agentic_podcast import (
    AgenticPodcastWorkflow,
    ComplianceOutput,
    DirectorOutput,
    FixerOutput,
    OutlineSegment,
    ReviewerOutput,
    WriterOutput,
)

# Review-fix loop configuration
DEFAULT_REVISION_THRESHOLD = 9.0  # minimum acceptable score (raised to test fixer)
DEFAULT_MAX_REVISIONS = 2  # maximum number of fix cycles


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
    fixer_outputs: Annotated[List[FixerOutput], operator.add]
    compliance_output: Optional[ComplianceOutput]

    # Revision loop control
    revision_count: int
    max_revisions: int
    revision_threshold: float

    # Control flow
    current_stage: str
    errors: Annotated[List[str], operator.add]





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


async def run_writers_sequential(
    state: AgenticPodcastState, config: RunnableConfig
) -> Dict[str, Any]:
    """run all segment writers sequentially so each segment has context from previous ones

    This replaces the parallel fan-out approach to ensure proper conversational
    flow between segments — each writer sees the actual output of prior segments.

    Args:
        state: Current workflow state
        config: Runnable configuration

    Returns:
        updated state with all writer_outputs
    """
    if not state.get("director_output"):
        logger.error("No director output available for writers")
        return {"errors": ["No director output"], "current_stage": "failed"}

    director_output = state["director_output"]
    segments = director_output.segments

    logger.info(f"Running {len(segments)} segment writers sequentially")

    all_outputs: List[WriterOutput] = []
    errors: List[str] = []

    for i, segment in enumerate(segments):
        logger.info(f"Writing segment {i}/{len(segments)}: '{segment.name}'")

        try:
            # Pass actual previous outputs for context
            previous_segments = all_outputs if all_outputs else None

            writer_output = await writer_agent(
                segment=segment,
                segment_index=i,
                content=state["content"],
                briefing=state["briefing"],
                speakers=state["speakers"],
                outline_segments=segments,
                previous_segments=previous_segments,
                model_name=state.get("transcript_model"),
                max_turns=state.get("max_turns", 20),
                target_words_per_turn=state.get("target_words_per_turn"),
                target_duration_minutes=state.get("target_duration_minutes"),
                num_segments=len(segments),
            )

            all_outputs.append(writer_output)

            logger.info(
                f"Writer completed segment {i}: {len(writer_output.transcript)} turns"
            )

            # Save progress to workflow DB after each segment
            try:
                workflow = await AgenticPodcastWorkflow.get(state["workflow_id"])
                workflow.set_writer_outputs(all_outputs)
                await workflow.save()
                logger.info(f"Saved progress: {len(all_outputs)}/{len(segments)} segments written")
            except Exception as save_err:
                logger.warning(f"Could not save segment progress: {save_err}")

        except Exception as e:
            error_msg = f"Writer agent failed for segment {i}: {str(e)}"
            logger.error(error_msg)
            logger.exception(e)
            errors.append(error_msg)

    if not all_outputs:
        return {
            "errors": errors or ["All writers failed"],
            "current_stage": "failed",
        }

    if errors:
        logger.warning(f"{len(errors)} segment(s) failed, {len(all_outputs)} succeeded")

    return {
        "writer_outputs": all_outputs,
        "current_stage": "reviewer",
        "errors": errors,
    }


async def run_reviewer(
    state: AgenticPodcastState, config: RunnableConfig
) -> Dict[str, Any]:
    """execute the Reviewer agent to evaluate the transcript

    On the first pass, reviews the combined writer output.
    On subsequent passes (after fixer), reviews the fixer's corrected transcript.

    Args:
        state: Current workflow state
        config: Runnable configuration

    Returns:
        updated state with reviewer_output
    """
    revision_count = state.get("revision_count", 0)
    logger.info(
        f"Running Reviewer agent for workflow {state['workflow_id']} "
        f"(revision round {revision_count})"
    )

    try:
        workflow = await AgenticPodcastWorkflow.get(state["workflow_id"])
        await workflow.update_stage("reviewer", "in_progress")

        # Use the best available transcript:
        # - If we've been through the fixer, use its latest output
        # - Otherwise, combine writer outputs
        fixer_outputs = state.get("fixer_outputs", [])
        if fixer_outputs:
            latest_fix = max(fixer_outputs, key=lambda f: f.revision_round)
            combined_transcript = latest_fix.revised_transcript
            logger.info(
                f"Reviewing fixer output from round {latest_fix.revision_round} "
                f"({len(combined_transcript)} lines)"
            )
        else:
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
            model_name=state.get("reviewer_model") or state.get("transcript_model"),
        )

        # tag the review with the current revision round
        reviewer_output.revision_round = revision_count

        # save reviewer output to workflow
        workflow.set_reviewer_output(reviewer_output)
        await workflow.save()

        logger.info(
            f"Reviewer completed (round {revision_count}): "
            f"score={reviewer_output.overall_score}, "
            f"issues={len(reviewer_output.issues)}"
        )

        return {
            "reviewer_output": reviewer_output,
            "current_stage": "post_review",
        }

    except Exception as e:
        error_msg = f"Reviewer agent failed: {str(e)}"
        logger.error(error_msg)
        logger.exception(e)

        # reviewer failure is non-fatal — we can proceed without review
        logger.warning("Proceeding to compliance with current transcript")
        return {
            "errors": [error_msg],
            "current_stage": "compliance",
        }


async def run_compliance(
    state: AgenticPodcastState, config: RunnableConfig
) -> Dict[str, Any]:
    """execute the Compliance agent for final safety and quality gate

    Checks the best available transcript (fixer-revised, reviewer-passed, or
    original writer output) for safety, bias, misinformation, and other
    compliance concerns.

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

        # use the best available transcript:
        # latest fixer output > reviewer's transcript > raw writer outputs
        fixer_outputs = state.get("fixer_outputs", [])
        reviewer_output = state.get("reviewer_output")

        if fixer_outputs:
            latest_fix = max(fixer_outputs, key=lambda f: f.revision_round)
            transcript = latest_fix.revised_transcript
            reviewer_summary = reviewer_output.summary if reviewer_output else None
        elif reviewer_output and reviewer_output.revised_transcript:
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
            model_name=state.get("compliance_model") or state.get("transcript_model"),
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

        # Save fixer outputs if any
        fixer_outputs = state.get("fixer_outputs", [])
        if fixer_outputs:
            for fo in fixer_outputs:
                workflow.add_fixer_output(fo)

        # Mark as completed
        await workflow.mark_completed()

        revision_count = state.get("revision_count", 0)
        logger.info(
            f"Workflow {state['workflow_id']} completed successfully with "
            f"{len(sorted_outputs)} segments, {revision_count} revision(s)"
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


# ── Fixer node and revision routing ──────────────────────────────────────────


async def run_fixer(
    state: AgenticPodcastState, config: RunnableConfig
) -> Dict[str, Any]:
    """execute the Fixer agent to correct issues identified by the Reviewer

    Takes the reviewer's issues and the current transcript, produces a corrected
    version, then the workflow loops back to the reviewer for re-evaluation.

    Args:
        state: Current workflow state
        config: Runnable configuration

    Returns:
        updated state with fixer output and incremented revision count
    """
    revision_count = state.get("revision_count", 0)
    new_round = revision_count + 1
    reviewer_output = state.get("reviewer_output")

    logger.info(
        f"Running Fixer agent for workflow {state['workflow_id']} "
        f"(revision round {new_round}, reviewer score={reviewer_output.overall_score if reviewer_output else 'N/A'})"
    )

    try:
        workflow = await AgenticPodcastWorkflow.get(state["workflow_id"])
        await workflow.update_stage("writer", "in_progress")  # reuse "writer" stage for UI

        # Get the current transcript to fix — same logic as reviewer
        fixer_outputs = state.get("fixer_outputs", [])
        if fixer_outputs:
            latest_fix = max(fixer_outputs, key=lambda f: f.revision_round)
            current_transcript = latest_fix.revised_transcript
        else:
            writer_outputs = state.get("writer_outputs", [])
            sorted_outputs = sorted(writer_outputs, key=lambda x: x.segment_index)
            current_transcript = []
            for wo in sorted_outputs:
                current_transcript.extend(wo.transcript)

        fixer_output = await fixer_agent(
            transcript=current_transcript,
            content=state["content"],
            briefing=state["briefing"],
            speakers=state["speakers"],
            overall_score=reviewer_output.overall_score,
            scores=reviewer_output.scores,
            issues=reviewer_output.issues,
            reviewer_summary=reviewer_output.summary,
            revision_round=new_round,
            model_name=state.get("transcript_model"),
        )

        # Save fixer output to workflow
        workflow.add_fixer_output(fixer_output)
        await workflow.save()

        logger.info(
            f"Fixer completed round {new_round}: "
            f"{len(fixer_output.revised_transcript)} lines, "
            f"summary={fixer_output.fix_summary[:100]}"
        )

        return {
            "fixer_outputs": [fixer_output],
            "revision_count": new_round,
            "current_stage": "reviewer",
        }

    except Exception as e:
        error_msg = f"Fixer agent failed (round {new_round}): {str(e)}"
        logger.error(error_msg)
        logger.exception(e)

        # fixer failure is non-fatal — proceed to compliance with what we have
        logger.warning("Fixer failed, proceeding to compliance with current transcript")
        return {
            "errors": [error_msg],
            "current_stage": "compliance",
        }


def should_fix_or_proceed(state: AgenticPodcastState) -> str:
    """conditional routing after reviewer: fix or proceed to compliance

    Routes to the fixer if:
    1. The reviewer produced output with a score below the threshold
    2. There are issues to fix (at least one high or medium severity)
    3. We haven't exceeded the maximum number of revision rounds

    Otherwise, routes to compliance.

    Args:
        state: Current workflow state

    Returns:
        "run_fixer" or "run_compliance"
    """
    reviewer_output = state.get("reviewer_output")
    revision_count = state.get("revision_count", 0)
    max_revisions = state.get("max_revisions", DEFAULT_MAX_REVISIONS)
    threshold = state.get("revision_threshold", DEFAULT_REVISION_THRESHOLD)

    # No reviewer output → proceed
    if not reviewer_output:
        logger.info("No reviewer output, proceeding to compliance")
        return "run_compliance"

    score = reviewer_output.overall_score

    # Score meets threshold → proceed
    if score >= threshold:
        logger.info(
            f"Reviewer score {score} >= threshold {threshold}, "
            f"proceeding to compliance"
        )
        return "run_compliance"

    # Max revisions reached → proceed
    if revision_count >= max_revisions:
        logger.warning(
            f"Max revisions ({max_revisions}) reached with score {score}, "
            f"proceeding to compliance anyway"
        )
        return "run_compliance"

    # Check if there are actionable issues (high or medium severity)
    issues = reviewer_output.issues or []
    actionable = [
        i for i in issues
        if i.get("severity", "").lower() in ("high", "medium")
    ]

    if not actionable:
        logger.info(
            f"Score {score} below threshold but no actionable issues, "
            f"proceeding to compliance"
        )
        return "run_compliance"

    logger.info(
        f"Score {score} < threshold {threshold}, "
        f"{len(actionable)} actionable issues found, "
        f"routing to fixer (round {revision_count + 1}/{max_revisions})"
    )
    return "run_fixer"


def build_agentic_podcast_graph() -> StateGraph:
    """build the LangGraph workflow for agentic podcast generation

    The workflow follows this structure:
    1. START → run_director (create outline)
    2. run_director → run_writers_sequential (write segments one by one)
    3. run_writers_sequential → run_reviewer (evaluate transcript)
    4. run_reviewer → should_fix_or_proceed (conditional routing)
       a. If score < threshold and revisions remain → run_fixer → run_reviewer (loop)
       b. If score >= threshold or max revisions reached → run_compliance
    5. run_compliance → save_workflow (persist results)
    6. save_workflow → END

    Returns:
        compiled stategraph ready for execution
    """
    # create the graph
    workflow = StateGraph(AgenticPodcastState)

    # add nodes
    workflow.add_node("run_director", run_director)
    workflow.add_node("run_writers_sequential", run_writers_sequential)
    workflow.add_node("run_reviewer", run_reviewer)
    workflow.add_node("run_fixer", run_fixer)
    workflow.add_node("run_compliance", run_compliance)
    workflow.add_node("save_workflow", save_workflow)

    # add edges
    workflow.add_edge(START, "run_director")
    workflow.add_edge("run_director", "run_writers_sequential")
    workflow.add_edge("run_writers_sequential", "run_reviewer")

    # conditional edge: after reviewer, decide whether to fix or proceed
    workflow.add_conditional_edges(
        "run_reviewer",
        should_fix_or_proceed,
        {
            "run_fixer": "run_fixer",
            "run_compliance": "run_compliance",
        },
    )

    # fixer loops back to reviewer for re-evaluation
    workflow.add_edge("run_fixer", "run_reviewer")

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
        "fixer_outputs": [],
        "compliance_output": None,
        "revision_count": 0,
        "max_revisions": DEFAULT_MAX_REVISIONS,
        "revision_threshold": DEFAULT_REVISION_THRESHOLD,
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
