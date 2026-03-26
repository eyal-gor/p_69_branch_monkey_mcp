"""
Local Server Package for Kompany Relay.

This package provides a FastAPI server that handles local Claude Code agent operations.
When combined with the relay client, it allows cloud users to run agents on local machines.

Public API:
- run_server: Start the FastAPI server
- set_default_working_dir: Set the default working directory for agent execution
- set_home_directory: Set the home directory (base directory passed to relay)
"""

from .config import set_default_working_dir, set_home_directory


def run_server(*args, **kwargs):
    """Start the FastAPI server lazily to avoid import cycles."""
    from .app import run_server as _run_server

    return _run_server(*args, **kwargs)


def __getattr__(name):
    if name == "app":
        from .app import app

        return app
    raise AttributeError(name)

__all__ = [
    "app",
    "run_server",
    "set_default_working_dir",
    "set_home_directory",
]
