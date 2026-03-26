"""
Runtime capability helpers for local and hosted computer environments.

This module gathers the machine-level capabilities that higher layers
like the Cerver provider adapter can expose without depending directly
on route handlers.
"""

from typing import Any, Dict, List

from ..bridge_and_local_actions.cli_providers import get_available_providers


def get_available_cli_tools() -> List[str]:
    """Return installed CLI tool names."""
    tools: List[str] = []
    for provider in get_available_providers():
        name = provider.get("name")
        if isinstance(name, str) and name:
            tools.append(name)
    return tools


def get_runtime_capabilities() -> Dict[str, Any]:
    """Return a normalized capability payload for this computer runtime."""
    cli_tools = get_available_cli_tools()
    return {
        "runtimes": ["shell"],
        "streaming": True,
        "persistence": "high",
        "desktop": True,
        "public_preview": False,
        "worktrees": True,
        "dev_servers": True,
        "git": True,
        "local_computer": True,
        "cerver_provider": True,
        "cli_tools": cli_tools,
    }
