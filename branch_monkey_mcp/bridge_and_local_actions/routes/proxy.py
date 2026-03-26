"""
Dev proxy management endpoints for the local server.
"""

from fastapi import APIRouter

from ...computer_runtime.preview_proxy import (
    get_preview_proxy_status,
    set_preview_proxy_target,
    stop_preview_proxy,
    update_preview_proxy_port,
)

router = APIRouter()


@router.get("/dev-proxy")
def get_dev_proxy():
    """Get current dev proxy status."""
    return get_preview_proxy_status()


@router.post("/dev-proxy")
def set_dev_proxy_target(run_id: str):
    """Set proxy target to a specific running dev server by run_id."""
    return set_preview_proxy_target(run_id)


@router.put("/dev-proxy/port")
def set_dev_proxy_port_endpoint(port: int):
    """Set the proxy port. Restarts proxy if already running."""
    return update_preview_proxy_port(port)


@router.delete("/dev-proxy")
def stop_dev_proxy_endpoint():
    """Stop the dev proxy server."""
    return stop_preview_proxy()
