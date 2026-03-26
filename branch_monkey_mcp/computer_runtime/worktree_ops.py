"""
Worktree operations for the reusable computer runtime.
"""

import os
import re
import subprocess
from typing import Any, Dict, Optional

from ..bridge_and_local_actions.config import get_default_working_dir
from ..bridge_and_local_actions.git_utils import get_git_root
from ..bridge_and_local_actions.worktree import (
    create_worktree,
    find_actual_branch,
    find_worktree_path,
    remove_worktree,
)


def delete_worktree(worktree_path: str, repo_dir: Optional[str] = None) -> Dict[str, Any]:
    """Delete a git worktree and return a normalized response."""
    work_dir = repo_dir or get_default_working_dir()
    git_root = get_git_root(work_dir) or work_dir
    remove_worktree(git_root, worktree_path)
    return {"success": True, "message": f"Worktree deleted: {worktree_path}"}


def list_worktrees() -> Dict[str, Any]:
    """List task worktrees with basic status details."""
    work_dir = get_default_working_dir()
    git_root = get_git_root(work_dir)
    if not git_root:
        return {"worktrees": [], "error": "Not in a git repository"}

    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=git_root,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return {"worktrees": [], "error": "Failed to list worktrees"}

    worktrees = []
    current_wt: Dict[str, Any] = {}

    for line in result.stdout.strip().split("\n"):
        if not line:
            if current_wt:
                worktrees.append(current_wt)
                current_wt = {}
            continue

        if line.startswith("worktree "):
            current_wt["path"] = line[9:]
        elif line.startswith("HEAD "):
            current_wt["head"] = line[5:]
        elif line.startswith("branch "):
            branch = line[7:]
            if branch.startswith("refs/heads/"):
                branch = branch[11:]
            current_wt["branch"] = branch
        elif line == "bare":
            current_wt["bare"] = True
        elif line == "detached":
            current_wt["detached"] = True

    if current_wt:
        worktrees.append(current_wt)

    task_worktrees = [
        wt
        for wt in worktrees
        if ".worktrees" in wt.get("path", "") or wt.get("branch", "").startswith("task/")
    ]

    for wt in task_worktrees:
        path = wt.get("path", "")
        branch = wt.get("branch", "")

        task_number = None
        match = re.search(r"task-(\d+)", path)
        if match:
            task_number = int(match.group(1))
        elif branch:
            match = re.search(r"task/(\d+)", branch)
            if match:
                task_number = int(match.group(1))

        wt["task_number"] = task_number

        if os.path.isdir(path):
            try:
                status_result = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=path,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                changes = [line for line in status_result.stdout.strip().split("\n") if line]
                wt["changes_count"] = len(changes)
                wt["is_clean"] = len(changes) == 0
            except Exception:
                wt["changes_count"] = None
                wt["is_clean"] = None

            try:
                log_result = subprocess.run(
                    ["git", "log", "-1", "--pretty=format:%s|%ar"],
                    cwd=path,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if log_result.returncode == 0 and log_result.stdout:
                    parts = log_result.stdout.split("|")
                    if len(parts) >= 2:
                        wt["last_commit_message"] = parts[0][:80]
                        wt["last_commit_time"] = parts[1]
            except Exception:
                pass

    return {"worktrees": task_worktrees, "git_root": git_root}


def get_worktree_info(task_number: int) -> Dict[str, Any]:
    """Return worktree info for a specific task."""
    worktree_path = find_worktree_path(task_number)
    if not worktree_path:
        raise LookupError(f"No worktree found for task {task_number}")

    work_dir = get_default_working_dir()
    git_root = get_git_root(work_dir)

    branch = None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
    except Exception:
        pass

    changes_count = 0
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            changes = [line for line in result.stdout.strip().split("\n") if line]
            changes_count = len(changes)
    except Exception:
        pass

    return {
        "task_number": task_number,
        "path": worktree_path,
        "branch": branch,
        "changes_count": changes_count,
        "git_root": git_root,
    }


__all__ = [
    "create_worktree",
    "delete_worktree",
    "find_actual_branch",
    "find_worktree_path",
    "get_worktree_info",
    "list_worktrees",
]
