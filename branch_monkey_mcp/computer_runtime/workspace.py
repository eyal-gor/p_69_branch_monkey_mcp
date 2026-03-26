"""
Workspace/runtime helpers for the reusable computer runtime.
"""

import os
from pathlib import Path
from typing import Any, Dict

from ..bridge_and_local_actions.config import (
    get_default_working_dir,
    get_home_directory,
    set_default_working_dir,
)
from ..bridge_and_local_actions.git_utils import get_git_root


def _count_worktrees(git_root: str | None) -> int:
    if not git_root:
        return 0

    worktrees_dir = Path(git_root) / ".worktrees"
    if not worktrees_dir.exists():
        return 0

    return len([entry for entry in worktrees_dir.iterdir() if entry.is_dir()])


def get_working_directory_info() -> Dict[str, Any]:
    """Return normalized workspace info for the current machine."""
    home_dir = get_home_directory()
    work_dir = get_default_working_dir()
    git_root = get_git_root(work_dir)

    return {
        "home_directory": home_dir,
        "working_directory": work_dir,
        "git_root": git_root,
        "is_git_repo": git_root is not None,
        "worktree_count": _count_worktrees(git_root),
    }


def set_working_directory(directory: str) -> Dict[str, Any]:
    """Validate and set the active working directory."""
    if not os.path.isdir(directory):
        raise ValueError(f"Directory does not exist: {directory}")

    abs_path = os.path.abspath(directory)
    git_root = get_git_root(abs_path)
    home_dir = get_home_directory()

    if not git_root and abs_path != home_dir:
        raise ValueError(f"Not a git repository: {abs_path}")

    set_default_working_dir(abs_path)

    return {
        "status": "ok",
        "home_directory": home_dir,
        "working_directory": abs_path,
        "git_root": git_root,
        "is_git_repo": git_root is not None,
        "worktree_count": _count_worktrees(git_root),
    }
