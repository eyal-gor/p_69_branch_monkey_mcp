"""Worktree management endpoints for the local server."""

from fastapi import APIRouter, HTTPException

from ...computer_runtime.worktree_ops import (
    delete_worktree,
    get_worktree_info,
    list_worktrees as runtime_list_worktrees,
)

router = APIRouter()


@router.delete("/worktree")
def delete_worktree_endpoint(task_number: int, worktree_path: str):
    """Delete a git worktree."""
    try:
        return delete_worktree(worktree_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete worktree: {str(exc)}") from exc


@router.get("/worktrees")
def list_worktrees():
    """List all git worktrees in the repository with detailed info."""
    try:
        return runtime_list_worktrees()
    except Exception as exc:
        return {"worktrees": [], "error": str(exc)}


@router.get("/worktree/{task_number}")
def get_worktree(task_number: int):
    """Get worktree info for a specific task."""
    try:
        return get_worktree_info(task_number)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
