"""API router for agentic podcast workflows.

This module provides REST API endpoints for managing multi-agent podcast workflows:
- Create and execute workflows
- List and retrieve workflow status
- Get generated transcripts
- Delete workflows
"""

from typing import List

from fastapi import APIRouter, HTTPException
from loguru import logger

from api.agentic_podcast_service import (
    AgenticPodcastService,
    AgenticWorkflowDetailResponse,
    AgenticWorkflowRequest,
    AgenticWorkflowResponse,
    TranscriptResponse,
)

router = APIRouter()


@router.post("/workflows", response_model=AgenticWorkflowResponse, status_code=201)
async def create_agentic_workflow(request: AgenticWorkflowRequest):
    """Create and execute a new agentic podcast workflow.

    This endpoint creates a workflow using the multi-agent system:
    1. Director agent analyzes content and creates outline
    2. Writer agent generates transcript for each segment
    3. Results are saved to the database

    **Phase 1**: Synchronous execution (workflow completes before returning)
    **Phase 2** (future): Background job execution with status tracking

    Args:
        request: Workflow creation request with episode profile, content, etc.

    Returns:
        AgenticWorkflowResponse with workflow ID and status

    Raises:
        HTTPException: 400 if validation fails, 404 if profiles not found, 500 on execution error
    """
    logger.info(f"Creating agentic workflow for episode '{request.episode_name}'")
    return await AgenticPodcastService.create_workflow(request)


@router.get("/workflows", response_model=List[AgenticWorkflowResponse])
async def list_agentic_workflows():
    """List all agentic podcast workflows.

    Returns workflows sorted by creation date (most recent first).

    Returns:
        List of AgenticWorkflowResponse objects with summary information

    Raises:
        HTTPException: 500 on database error
    """
    logger.info("Listing all agentic workflows")
    return await AgenticPodcastService.list_workflows()


@router.get("/workflows/{workflow_id}", response_model=AgenticWorkflowDetailResponse)
async def get_agentic_workflow(workflow_id: str):
    """Get detailed information about a specific workflow.

    Includes all agent outputs (director outline, writer transcripts) and status.

    Args:
        workflow_id: ID of the workflow to retrieve

    Returns:
        AgenticWorkflowDetailResponse with complete workflow data

    Raises:
        HTTPException: 404 if workflow not found, 500 on database error
    """
    logger.info(f"Getting workflow {workflow_id}")
    return await AgenticPodcastService.get_workflow(workflow_id)


@router.get("/workflows/{workflow_id}/transcript", response_model=TranscriptResponse)
async def get_workflow_transcript(workflow_id: str):
    """Get the final combined transcript from a completed workflow.

    Returns the full transcript with all segments merged in order.

    Args:
        workflow_id: ID of the workflow

    Returns:
        TranscriptResponse with combined transcript lines

    Raises:
        HTTPException: 400 if workflow not completed, 404 if not found, 500 on error
    """
    logger.info(f"Getting transcript for workflow {workflow_id}")
    return await AgenticPodcastService.get_transcript(workflow_id)


@router.delete("/workflows/{workflow_id}", status_code=200)
async def delete_agentic_workflow(workflow_id: str):
    """Delete an agentic podcast workflow.

    Removes the workflow record from the database. This action cannot be undone.

    Args:
        workflow_id: ID of the workflow to delete

    Returns:
        Success message

    Raises:
        HTTPException: 404 if workflow not found, 500 on database error
    """
    logger.info(f"Deleting workflow {workflow_id}")
    return await AgenticPodcastService.delete_workflow(workflow_id)
