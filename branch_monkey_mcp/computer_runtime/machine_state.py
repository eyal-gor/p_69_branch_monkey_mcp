"""
Machine/runtime state helpers for the local computer runtime.

This module centralizes machine-facing metadata so provider adapters and
other surfaces do not need to reach into config modules directly.
"""

from typing import Any, Dict

from ..bridge_and_local_actions.config import (
    get_default_working_dir,
    get_home_directory,
    get_relay_status,
)


def get_machine_state() -> Dict[str, Any]:
    """Return normalized machine/runtime state."""
    relay_status = get_relay_status()
    return {
        "mode": "relay" if relay_status.get("connected") else "direct",
        "status": "ready",
        "working_directory": get_default_working_dir(),
        "home_directory": get_home_directory(),
        "relay": relay_status,
        "machine_id": relay_status.get("machine_id"),
        "machine_name": relay_status.get("machine_name"),
        "last_heartbeat": relay_status.get("last_heartbeat"),
    }
