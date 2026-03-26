"""
Cerver provider endpoints for the local server.

This exposes a provider-shaped HTTP surface so p69 can appear inside Cerver
as a first-class execution provider, just like a hosted sandbox backend.
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...cerver_compute.execution import (
    collect_provider_run,
    delete_provider_session as delete_provider_session_response,
    get_provider_state_response,
    provider_stream_events,
)
from ...cerver_compute.provider import (
    create_provider_session as create_provider_session_response,
    get_provider_info as build_provider_info,
)
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


@router.get("/provider")
def get_provider_info():
    return build_provider_info()


@router.post("/provider/sandboxes")
async def create_provider_session(request: CreateProviderSessionRequest):
    return await create_provider_session_response(
        agent_manager=agent_manager,
        metadata=request.metadata or {},
        engine=request.engine or "shell",
        timeout_ms=request.timeout_ms,
    )


@router.post("/provider/sandboxes/{sandbox_id}/run")
async def run_provider_session(sandbox_id: str, request: ProviderRunRequest):
    timeout_seconds = max(5, int(request.timeout or DEFAULT_TIMEOUT_SECONDS))
    return await collect_provider_run(agent_manager, sandbox_id, request.code, timeout_seconds)


@router.post("/provider/sandboxes/{sandbox_id}/run/stream")
async def stream_provider_session(sandbox_id: str, request: ProviderRunRequest, raw_request: Request):
    return StreamingResponse(
        provider_stream_events(agent_manager, raw_request, sandbox_id, request.code),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.post("/provider/sandboxes/{sandbox_id}/install")
async def install_in_provider_session(sandbox_id: str, request: ProviderInstallRequest):
    return await collect_provider_run(
        agent_manager,
        sandbox_id,
        f"Run this exact shell command and return the result only: npm install {request.package} || pnpm add {request.package} || yarn add {request.package} || pip install {request.package}",
        DEFAULT_TIMEOUT_SECONDS,
    )


@router.get("/provider/sandboxes/{sandbox_id}/state")
def get_provider_state(sandbox_id: str):
    return get_provider_state_response(
        agent_manager=agent_manager,
        sandbox_id=sandbox_id,
        workflow_summary=get_workflow_summary(),
    )


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
    return delete_provider_session_response(
        agent_manager,
        sandbox_id,
        cleanup_worktree=cleanup_worktree,
    )
