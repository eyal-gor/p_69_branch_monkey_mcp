"""
Preview/proxy operations for the reusable computer runtime.
"""

from typing import Any, Dict

from fastapi import HTTPException

from ..bridge_and_local_actions.dev_proxy import (
    _proxy_state,
    get_proxy_status,
    set_proxy_port,
    set_proxy_target,
    start_dev_proxy,
    stop_dev_proxy,
)
from ..bridge_and_local_actions.dev_server_manager import manager


def get_preview_proxy_status() -> Dict[str, Any]:
    """Return the current proxy status."""
    return get_proxy_status()


def set_preview_proxy_target(run_id: str) -> Dict[str, Any]:
    """Point the preview proxy at a running dev server."""
    running_dev_servers = manager.get_servers()
    if run_id not in running_dev_servers:
        raise HTTPException(status_code=404, detail=f"No dev server running for run {run_id}")

    if not _proxy_state["running"]:
        start_dev_proxy()

    info = running_dev_servers[run_id]
    set_proxy_target(info["port"], run_id)
    return get_proxy_status()


def update_preview_proxy_port(port: int) -> Dict[str, Any]:
    """Set the proxy port, restarting if needed."""
    if port < 1024 or port > 65535:
        raise HTTPException(status_code=400, detail="Port must be between 1024 and 65535")

    old_port = _proxy_state["proxy_port"]
    success = set_proxy_port(port)
    if not success:
        raise HTTPException(
            status_code=500,
            detail=f"Port {port} is not available, reverted to {old_port}",
        )

    return {
        "success": True,
        "oldPort": old_port,
        "newPort": port,
        "status": get_proxy_status(),
    }


def stop_preview_proxy() -> Dict[str, Any]:
    """Stop the preview proxy."""
    stop_dev_proxy()
    return {"success": True, "status": get_proxy_status()}


__all__ = [
    "get_preview_proxy_status",
    "set_preview_proxy_target",
    "update_preview_proxy_port",
    "stop_preview_proxy",
]
