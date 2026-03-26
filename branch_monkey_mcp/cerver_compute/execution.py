"""
Cerver-facing execution helpers for the p69 local computer runtime.

These helpers keep the HTTP route thin while the underlying local execution
still flows through the legacy agent manager.
"""

import asyncio
import json
from typing import Any, AsyncGenerator, Dict

from fastapi import HTTPException, Request

from .provider import build_provider_state


def _extract_normalized_text(normalized: Any) -> str:
    if not isinstance(normalized, dict):
        return ""

    if normalized.get("type") == "assistant":
        content = normalized.get("message", {}).get("content", [])
        text_blocks = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "".join(text_blocks)

    if normalized.get("type") == "tool_result":
        return normalized.get("content", "") or ""

    if normalized.get("type") == "result":
        return normalized.get("result", "") or ""

    text = normalized.get("text")
    return text if isinstance(text, str) else ""


def extract_stream_text(event: Dict[str, Any]) -> str:
    if event.get("type") != "output":
        return ""

    data = event.get("data")
    if not isinstance(data, str):
        return ""

    try:
        normalized = json.loads(data)
        return _extract_normalized_text(normalized)
    except Exception:
        return event.get("raw") or data


async def send_provider_input(agent_manager: Any, agent_id: str, message: str) -> Dict[str, Any]:
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if agent["status"] == "prepared":
        await agent_manager.spawn_cli_process(agent_id, message)
        refreshed = agent_manager.get(agent_id) or {}
        return {
            "success": True,
            "action": "started",
            "cli_tool": refreshed.get("cli_tool"),
            "images": 0,
        }

    if agent["status"] in ("paused", "completed", "failed") and agent.get("session_id"):
        await agent_manager.resume_session(agent_id, message)
        return {
            "success": True,
            "action": "resumed",
            "images": 0,
        }

    if agent["status"] == "running":
        raise HTTPException(
            status_code=400,
            detail="Agent is running. Wait for it to complete before sending another message.",
        )

    raise HTTPException(status_code=400, detail="No active session. Start a new task.")


async def collect_provider_run(
    agent_manager: Any,
    agent_id: str,
    message: str,
    timeout_seconds: int,
) -> Dict[str, Any]:
    queue = agent_manager.add_listener(agent_id)

    try:
        input_result = await send_provider_input(agent_manager, agent_id, message)
        stdout_parts = []
        stderr_parts = []
        exit_code = 0
        final_status = "running"

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=timeout_seconds)
            except asyncio.TimeoutError as exc:
                raise HTTPException(
                    status_code=408,
                    detail=f"Timed out waiting for provider output after {timeout_seconds}s",
                ) from exc

            if event.get("type") == "error":
                stderr_parts.append(event.get("error") or "Unknown local provider error")
                final_status = "failed"
                exit_code = 1
                break

            text = extract_stream_text(event)
            if text:
                stdout_parts.append(text)

            if event.get("type") == "paused":
                final_status = "paused"
                exit_code = event.get("exit_code") if isinstance(event.get("exit_code"), int) else 0
                break

            if event.get("type") == "exit":
                final_status = "completed"
                exit_code = event.get("exit_code") if isinstance(event.get("exit_code"), int) else 0
                break

        agent = agent_manager.get(agent_id) or {}
        return {
            "success": True,
            "action": input_result.get("action"),
            "command_id": agent.get("session_id") or agent_id,
            "execution_runtime": "shell",
            "exit_code": agent.get("exit_code") if isinstance(agent.get("exit_code"), int) else exit_code,
            "stdout": "".join(stdout_parts).strip(),
            "stderr": "".join(stderr_parts).strip(),
            "cwd": agent.get("work_dir"),
            "started_at": agent.get("created_at"),
            "provider_session_status": agent.get("status") or final_status,
            "can_resume": bool(agent.get("session_id")),
            "session_id": agent.get("session_id"),
        }
    finally:
        agent_manager.remove_listener(agent_id, queue)


async def provider_stream_events(
    agent_manager: Any,
    request: Request,
    agent_id: str,
    message: str,
) -> AsyncGenerator[str, None]:
    queue = agent_manager.add_listener(agent_id)

    try:
        agent = agent_manager.get(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        init_event = {"type": "connected", "agentId": agent_id, "status": agent["status"]}
        yield f"data: {json.dumps(init_event)}\n\n"

        await send_provider_input(agent_manager, agent_id, message)

        while True:
            if await request.is_disconnected():
                break

            try:
                event = await asyncio.wait_for(queue.get(), timeout=15.0)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") in ("exit", "paused"):
                    break
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
    finally:
        agent_manager.remove_listener(agent_id, queue)


def get_provider_state_response(
    agent_manager: Any,
    sandbox_id: str,
    workflow_summary: Dict[str, Any],
) -> Dict[str, Any]:
    agent = agent_manager.get(sandbox_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    return build_provider_state(
        sandbox_id=sandbox_id,
        agent=agent,
        agent_total=len(agent_manager.list()),
        workflow_summary=workflow_summary,
    )


def delete_provider_session(
    agent_manager: Any,
    sandbox_id: str,
    cleanup_worktree: bool = False,
) -> Dict[str, Any]:
    agent_manager.kill(sandbox_id, cleanup_worktree=cleanup_worktree)
    return {
        "success": True,
        "sandbox_id": sandbox_id,
        "remote_sandbox_id": sandbox_id,
        "provider": "p69",
        "status": "terminated",
    }
