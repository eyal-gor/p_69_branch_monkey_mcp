"""
Cerver provider endpoints for the local server.

This exposes a provider-shaped HTTP surface so p69 can appear inside Cerver
as a first-class execution provider, just like a hosted sandbox backend.
"""

import asyncio
import json
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..agent_manager import agent_manager
from .agents import get_workflow_summary

router = APIRouter()


DEFAULT_TIMEOUT_SECONDS = 300


class CreateProviderSessionRequest(BaseModel):
    engine: Optional[str] = "shell"
    timeout_ms: Optional[int] = None
    metadata: Dict[str, Any] = {}


class ProviderRunRequest(BaseModel):
    code: str
    timeout: Optional[int] = 30
    envs: Optional[Dict[str, str]] = None


class ProviderInstallRequest(BaseModel):
    package: str


class ProviderStateRequest(BaseModel):
    state: Dict[str, Any]


def _unsupported(detail: str) -> HTTPException:
    return HTTPException(status_code=501, detail=detail)


def _infer_workflow(metadata: Dict[str, Any]) -> str:
    explicit = metadata.get("workflow")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    if metadata.get("public_preview") is True:
        return "workspace"

    return "execute"


def _agent_payload_from_request(request: CreateProviderSessionRequest) -> Dict[str, Any]:
    metadata = request.metadata or {}
    task = metadata.get("task")
    title = metadata.get("session_name") or metadata.get("title") or task or "Cerver local session"
    workload = metadata.get("workload")

    description_parts = []
    if isinstance(task, str) and task.strip():
        description_parts.append(task.strip())
    if isinstance(workload, str) and workload.strip():
        description_parts.append(f"workload: {workload.strip()}")

    return {
        "title": title,
        "description": " | ".join(description_parts) if description_parts else None,
        "working_dir": metadata.get("working_dir"),
        "workflow": _infer_workflow(metadata),
        "branch": metadata.get("branch"),
        "defer_start": True,
        "cli_tool": metadata.get("cli_tool"),
        "prompt": metadata.get("bootstrap_prompt"),
    }


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


def _extract_stream_text(event: Dict[str, Any]) -> str:
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


def _provider_session_response(agent_id: str, agent: Dict[str, Any], metadata: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "sandbox_id": agent_id,
        "remote_sandbox_id": agent_id,
        "provider": "p69",
        "engine": metadata.get("engine", "shell"),
        "status": "ready",
        "created_at": agent.get("created_at"),
        "metadata": {
            **metadata,
            "cwd": agent.get("work_dir"),
            "branch": agent.get("branch"),
            "worktree_path": agent.get("worktree_path"),
            "cli_tool": agent.get("cli_tool"),
        },
        "capabilities": [
            "shell",
            "streaming",
            "local-computer",
            "resume",
            "worktree",
        ],
    }


async def _send_provider_input(agent_id: str, message: str) -> Dict[str, Any]:
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


async def _collect_provider_run(agent_id: str, message: str, timeout_seconds: int) -> Dict[str, Any]:
    queue = agent_manager.add_listener(agent_id)

    try:
        input_result = await _send_provider_input(agent_id, message)
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

            text = _extract_stream_text(event)
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


async def _provider_stream_events(
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

        await _send_provider_input(agent_id, message)

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


@router.get("/provider")
def get_provider_info():
    return {
        "provider": "p69",
        "label": "Local Computer",
        "mode": "local",
        "capabilities": {
            "runtimes": ["shell"],
            "streaming": True,
            "persistence": "high",
            "desktop": True,
            "public_preview": False,
        },
    }


@router.post("/provider/sandboxes")
async def create_provider_session(request: CreateProviderSessionRequest):
    payload = _agent_payload_from_request(request)
    created = await agent_manager.create(
        task_title=payload["title"],
        task_description=payload["description"],
        working_dir=payload["working_dir"],
        prompt=payload["prompt"],
        skip_branch=payload["workflow"] in ("ask", "plan", "workspace"),
        branch=payload["branch"],
        defer_start=payload["defer_start"],
        cli_tool=payload["cli_tool"],
    )

    agent_id = created.get("id")
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(status_code=500, detail="Failed to create provider session")

    return _provider_session_response(
        agent_id,
        agent,
        {
            **request.metadata,
            "engine": request.engine or "shell",
            "timeout_ms": request.timeout_ms,
        },
    )


@router.post("/provider/sandboxes/{sandbox_id}/run")
async def run_provider_session(sandbox_id: str, request: ProviderRunRequest):
    timeout_seconds = max(5, int(request.timeout or DEFAULT_TIMEOUT_SECONDS))
    return await _collect_provider_run(sandbox_id, request.code, timeout_seconds)


@router.post("/provider/sandboxes/{sandbox_id}/run/stream")
async def stream_provider_session(sandbox_id: str, request: ProviderRunRequest, raw_request: Request):
    return StreamingResponse(
        _provider_stream_events(raw_request, sandbox_id, request.code),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.post("/provider/sandboxes/{sandbox_id}/install")
async def install_in_provider_session(sandbox_id: str, request: ProviderInstallRequest):
    return await _collect_provider_run(
        sandbox_id,
        f"Run this exact shell command and return the result only: npm install {request.package} || pnpm add {request.package} || yarn add {request.package} || pip install {request.package}",
        DEFAULT_TIMEOUT_SECONDS,
    )


@router.get("/provider/sandboxes/{sandbox_id}/state")
def get_provider_state(sandbox_id: str):
    agent = agent_manager.get(sandbox_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    return {
        "provider": "p69",
        "sandbox_id": sandbox_id,
        "agent": agent,
        "agent_counts": {
            "total": len(agent_manager.list()),
        },
        "workflow_summary": get_workflow_summary(),
    }


@router.put("/provider/sandboxes/{sandbox_id}/state")
def set_provider_state(sandbox_id: str, request: ProviderStateRequest):
    raise _unsupported("p69 provider does not support arbitrary state writes")


@router.get("/provider/sandboxes/{sandbox_id}/files")
def read_provider_file(sandbox_id: str, path: Optional[str] = None, encoding: str = "utf-8"):
    raise _unsupported("p69 provider does not support direct file reads through the provider interface")


@router.put("/provider/sandboxes/{sandbox_id}/files")
def write_provider_file(sandbox_id: str):
    raise _unsupported("p69 provider does not support direct file writes through the provider interface")


@router.delete("/provider/sandboxes/{sandbox_id}")
def delete_provider_session(sandbox_id: str, cleanup_worktree: bool = False):
    agent_manager.kill(sandbox_id, cleanup_worktree=cleanup_worktree)
    return {
        "success": True,
        "sandbox_id": sandbox_id,
        "remote_sandbox_id": sandbox_id,
        "provider": "p69",
        "status": "terminated",
    }
