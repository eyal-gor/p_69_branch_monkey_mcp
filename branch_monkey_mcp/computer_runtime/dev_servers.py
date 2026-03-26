"""
Dev server operations for the reusable computer runtime.
"""

from typing import Any, Dict

from ..bridge_and_local_actions.dev_server_manager import DevServerRequest, manager


async def start_dev_server(request: DevServerRequest) -> Dict[str, Any]:
    """Start a dev server for a task/worktree."""
    run_id = request.run_id or str(request.task_number)
    return await manager.start(
        task_number=request.task_number,
        run_id=run_id,
        task_id=request.task_id,
        dev_script=request.dev_script,
        working_dir=request.working_dir,
        tunnel=request.tunnel or False,
        worktree_path=request.worktree_path,
        project_path=request.project_path,
    )


def list_dev_servers() -> Dict[str, Any]:
    """List tracked dev servers."""
    return manager.list()


def stop_dev_server(run_id: str) -> Dict[str, Any]:
    """Stop a tracked dev server."""
    return manager.stop(run_id)


__all__ = [
    "DevServerRequest",
    "start_dev_server",
    "list_dev_servers",
    "stop_dev_server",
]
