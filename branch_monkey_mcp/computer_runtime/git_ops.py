"""
Git operations for the reusable computer runtime.
"""

import os
import subprocess
from typing import Any, Dict, Optional

from ..bridge_and_local_actions.config import get_default_working_dir
from ..bridge_and_local_actions.git_utils import (
    get_current_branch,
    get_git_root,
    is_git_repo,
)


def resolve_git_root(path: Optional[str] = None) -> str:
    """Resolve the git root for a path or the default working directory."""
    work_dir = path or get_default_working_dir()
    git_root = get_git_root(work_dir)
    if not git_root:
        raise ValueError("Not in a git repository")
    return git_root


def get_git_status_summary(path: Optional[str] = None) -> Dict[str, Any]:
    """Return a porcelain-based git status summary."""
    directory = path or get_default_working_dir()

    if not directory or not os.path.isdir(directory):
        return {"error": "Invalid directory", "is_clean": None, "changes_count": 0}

    if not is_git_repo(directory):
        return {"error": "Not a git repository", "is_clean": None, "changes_count": 0}

    try:
        branch = get_current_branch(directory) or "unknown"
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=directory,
            capture_output=True,
            text=True,
            check=True,
        )

        lines = [line for line in result.stdout.strip().split("\n") if line]
        staged = 0
        unstaged = 0
        untracked = 0

        for line in lines:
            if len(line) < 2:
                continue
            index_status = line[0]
            worktree_status = line[1]

            if index_status == "?":
                untracked += 1
            elif index_status != " ":
                staged += 1

            if worktree_status not in (" ", "?"):
                unstaged += 1

        changes_count = len(lines)
        return {
            "is_clean": changes_count == 0,
            "changes_count": changes_count,
            "branch": branch,
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
        }
    except subprocess.CalledProcessError as exc:
        return {"error": str(exc), "is_clean": None, "changes_count": 0}
    except Exception as exc:
        return {"error": str(exc), "is_clean": None, "changes_count": 0}


def list_recent_commits(
    limit: int = 10,
    branch: Optional[str] = None,
    all_branches: bool = False,
    path: Optional[str] = None,
) -> Dict[str, Any]:
    """Return recent commits from the current repository."""
    git_root = resolve_git_root(path)
    cmd = ["git", "log", f"-{limit}", "--pretty=format:%H|%s|%an|%ar|%ai"]
    if all_branches:
        cmd.append("--all")
    elif branch:
        cmd.append(branch)

    result = subprocess.run(cmd, cwd=git_root, capture_output=True, text=True)
    if result.returncode != 0:
        return {"commits": [], "error": result.stderr}

    commits = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("|", 4)
        if len(parts) >= 5:
            commits.append(
                {
                    "hash": parts[0],
                    "shortHash": parts[0][:7],
                    "message": parts[1],
                    "author": parts[2],
                    "relativeDate": parts[3],
                    "date": parts[4],
                }
            )

    return {"commits": commits}


def get_commit_diff(sha: str, path: Optional[str] = None) -> Dict[str, Any]:
    """Return the patch/stat diff for a specific commit."""
    git_root = resolve_git_root(path)
    result = subprocess.run(
        ["git", "show", sha, "--stat", "--patch"],
        cwd=git_root,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise LookupError(f"Commit not found: {sha}")

    return {"sha": sha, "diff": result.stdout}
