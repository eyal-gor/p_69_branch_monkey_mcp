"""
Dev server management endpoints for the local server.
"""

from fastapi import APIRouter

from ...computer_runtime.dev_servers import (
    DevServerRequest,
    list_dev_servers as runtime_list_dev_servers,
    start_dev_server as runtime_start_dev_server,
    stop_dev_server as runtime_stop_dev_server,
)

router = APIRouter()


@router.post("/dev-server")
async def start_dev_server(request: DevServerRequest):
    """Start a dev server for a worktree."""
    return await runtime_start_dev_server(request)


@router.get("/dev-server")
def list_dev_servers():
    """List running dev servers."""
    return runtime_list_dev_servers()


@router.delete("/dev-server")
def stop_dev_server_endpoint(run_id: str):
    """Stop a dev server by run_id."""
    return runtime_stop_dev_server(run_id)
