"""
CLI execution primitives for the reusable computer runtime.

This module intentionally stops short of owning session lifecycle.
It only handles:
- provider resolution
- command construction
- environment shaping
- subprocess spawning
"""

import os
import subprocess
from typing import Optional

from ..bridge_and_local_actions.cli_providers import CliProvider, get_provider


def resolve_cli_provider(cli_tool: str) -> CliProvider:
    """Resolve a CLI provider by name."""
    return get_provider(cli_tool)


def build_process_env(cli_cmd) -> dict:
    """Build the environment for a CLI command."""
    env = os.environ.copy()
    for key in cli_cmd.env_overrides:
        env.pop(key, None)

    # Always remove CLAUDECODE to allow nested launches.
    env.pop("CLAUDECODE", None)

    if cli_cmd.env_inject:
        env.update(cli_cmd.env_inject)

    return env


def build_run_cli_command(
    provider: CliProvider,
    prompt: str,
    system_prompt: Optional[str] = None,
):
    """Build a new-run CLI command for a provider."""
    return provider.build_run_command(prompt, system_prompt=system_prompt)


def build_resume_cli_command(
    provider: CliProvider,
    message: str,
    session_id: str,
):
    """Build a resume CLI command for a provider."""
    return provider.build_resume_command(message, session_id)


def spawn_cli_subprocess(cli_cmd, cwd: str) -> subprocess.Popen:
    """Spawn a CLI subprocess for the given command."""
    env = build_process_env(cli_cmd)
    return subprocess.Popen(
        cli_cmd.args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=cwd,
        env=env,
        bufsize=1,
        universal_newlines=False,
    )


__all__ = [
    "resolve_cli_provider",
    "build_process_env",
    "build_run_cli_command",
    "build_resume_cli_command",
    "spawn_cli_subprocess",
]
