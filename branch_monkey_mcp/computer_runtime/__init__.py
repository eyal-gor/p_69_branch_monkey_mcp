"""
Reusable computer runtime primitives.

This package is the future home for machine capabilities that can run on:
- local computers through p69
- hosted sandboxes like Vercel or E2B
"""

from .capabilities import get_available_cli_tools, get_runtime_capabilities
from .cli_runtime import (
    build_process_env,
    build_resume_cli_command,
    build_run_cli_command,
    resolve_cli_provider,
    spawn_cli_subprocess,
)
from .dev_servers import DevServerRequest, list_dev_servers, start_dev_server, stop_dev_server
from .execution import (
    broadcast_to_agent_listeners,
    build_agent_prompt,
    extract_result_from_output_buffer,
    process_provider_output_text,
)
from .git_ops import get_commit_diff, get_git_status_summary, list_recent_commits, resolve_git_root
from .machine_state import get_machine_state
from .preview_proxy import (
    get_preview_proxy_status,
    set_preview_proxy_target,
    stop_preview_proxy,
    update_preview_proxy_port,
)
from .worktree_ops import (
    create_worktree,
    delete_worktree,
    find_actual_branch,
    find_worktree_path,
    get_worktree_info,
    list_worktrees,
)
from .workspace import get_working_directory_info, set_working_directory

__all__ = [
    "get_available_cli_tools",
    "get_runtime_capabilities",
    "resolve_cli_provider",
    "build_process_env",
    "build_run_cli_command",
    "build_resume_cli_command",
    "spawn_cli_subprocess",
    "build_agent_prompt",
    "process_provider_output_text",
    "broadcast_to_agent_listeners",
    "extract_result_from_output_buffer",
    "get_machine_state",
    "DevServerRequest",
    "start_dev_server",
    "list_dev_servers",
    "stop_dev_server",
    "get_preview_proxy_status",
    "set_preview_proxy_target",
    "update_preview_proxy_port",
    "stop_preview_proxy",
    "get_working_directory_info",
    "set_working_directory",
    "get_git_status_summary",
    "list_recent_commits",
    "get_commit_diff",
    "resolve_git_root",
    "create_worktree",
    "delete_worktree",
    "find_actual_branch",
    "find_worktree_path",
    "get_worktree_info",
    "list_worktrees",
]
