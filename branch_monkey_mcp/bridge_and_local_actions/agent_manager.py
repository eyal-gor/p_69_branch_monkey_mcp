"""
Local Agent Manager for AI CLI execution.

This module manages the lifecycle of local AI agent instances (Claude Code, Codex, etc.),
including creation, execution, session resumption, and cleanup.
"""

import asyncio
import json
import os
import signal
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import HTTPException

from ..computer_runtime.cli_runtime import (
    build_resume_cli_command,
    build_run_cli_command,
    resolve_cli_provider,
    spawn_cli_subprocess,
)
from ..computer_runtime.execution import (
    broadcast_to_agent_listeners,
    build_agent_prompt,
    extract_result_from_output_buffer,
    process_provider_output_text,
)
from .cli_providers import CliProvider
from .config import get_default_working_dir
from .git_utils import is_git_repo, get_current_branch, generate_branch_name
from .worktree import create_worktree, find_worktree_for_branch, remove_worktree


@dataclass
class LocalAgent:
    """Represents a running local AI CLI agent."""
    id: str
    task_id: Optional[str]
    task_number: Optional[int]
    task_title: str
    task_description: Optional[str]
    repo_dir: str
    work_dir: str
    worktree_path: Optional[str]
    branch: Optional[str]
    branch_created: bool
    status: str  # prepared, starting, running, paused, completed, failed, stopped
    cli_tool: str = ""  # Which CLI provider to use (resolved at creation time)
    pid: Optional[int] = None
    process: Optional[subprocess.Popen] = None
    output_buffer: List[str] = field(default_factory=list)
    output_listeners: List[asyncio.Queue] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    exit_code: Optional[int] = None
    session_id: Optional[str] = None
    callback: Optional[Dict] = None  # Cron completion callback info
    extra_env: Optional[Dict[str, str]] = None  # Project-scoped env vars (e.g. BUFFER_API_KEY) passed by kompany/cerver and inherited by the spawned CLI process.


class LocalAgentManager:
    """Manages local Claude Code agent instances."""

    MAX_AGENTS = 10  # Maximum concurrent agents to prevent resource exhaustion
    STALE_TIMEOUT = 3600  # Agents idle for 1 hour are considered stale

    def __init__(self):
        self._agents: Dict[str, LocalAgent] = {}
        self._output_tasks: Dict[str, asyncio.Task] = {}

    def cleanup_stale_agents(self) -> int:
        """Remove agents that are completed, failed, or stale. Returns count removed."""
        now = datetime.now()
        stale_ids = []

        for agent_id, agent in self._agents.items():
            # Remove failed/stopped agents
            if agent.status in ("failed", "stopped"):
                stale_ids.append(agent_id)
                continue

            # Check if process is still running
            process_exited = False
            if agent.process:
                poll = agent.process.poll()
                if poll is not None:
                    process_exited = True

            # Remove completed/paused agents whose process has exited and are past stale timeout
            if agent.status in ("completed", "paused") or process_exited:
                if agent.created_at:
                    try:
                        age = (now - agent.created_at).total_seconds()
                        if age > self.STALE_TIMEOUT:
                            print(f"[LocalAgent] Agent {agent_id} is stale ({agent.status}, age={int(age)}s)")
                            stale_ids.append(agent_id)
                            continue
                    except Exception:
                        pass
                # No session_id = no resumption value, clean immediately
                if not agent.session_id:
                    stale_ids.append(agent_id)
                    continue

            # Check for stale agents (no activity for a while) regardless of status
            if agent.created_at:
                try:
                    if (now - agent.created_at).total_seconds() > self.STALE_TIMEOUT:
                        print(f"[LocalAgent] Agent {agent_id} is stale (created {agent.created_at})")
                        stale_ids.append(agent_id)
                except Exception:
                    pass

        for agent_id in stale_ids:
            print(f"[LocalAgent] Cleaning up agent {agent_id}")
            self.kill(agent_id)

        return len(stale_ids)

    async def create(
        self,
        task_id: Optional[str] = None,
        task_number: Optional[int] = None,
        task_title: str = "",
        task_description: Optional[str] = None,
        working_dir: Optional[str] = None,
        prompt: Optional[str] = None,
        system_prompt: Optional[str] = None,
        skip_branch: bool = False,
        branch: Optional[str] = None,
        defer_start: bool = False,
        callback: Optional[Dict] = None,
        cli_tool: Optional[str] = None,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> dict:
        """Create and optionally start a new local AI agent.

        If defer_start=True, sets up worktree/branch/tracking but does NOT spawn
        the CLI process. The session enters "prepared" status and waits for the
        first message via send_input, which calls spawn_cli_process().

        Args:
            cli_tool: Which CLI to use ('claude', 'codex'). Defaults to 'claude'.
        """

        # Clean up stale agents first
        cleaned = self.cleanup_stale_agents()
        if cleaned > 0:
            print(f"[LocalAgent] Cleaned up {cleaned} stale agents")

        # Check max agent limit
        if len(self._agents) >= self.MAX_AGENTS:
            raise HTTPException(
                status_code=429,
                detail=f"Maximum number of agents ({self.MAX_AGENTS}) reached. Kill some agents first."
            )

        # Resolve CLI provider
        provider = resolve_cli_provider(cli_tool)
        cli_path = provider.is_available()
        if not cli_path:
            raise HTTPException(
                status_code=400,
                detail=f"{provider.display_name} CLI not found. Install with: {provider.install_hint}"
            )

        agent_id = str(uuid.uuid4())[:8]
        repo_dir = working_dir or get_default_working_dir()
        work_dir = repo_dir
        target_branch = branch  # Explicit branch from caller (e.g. 'staging')
        branch_created = False
        worktree_path = None

        # Handle git worktree if in a git repo
        print(f"[LocalAgent] Worktree check: task_number={task_number}, branch={target_branch}, is_git={is_git_repo(repo_dir)}, skip_branch={skip_branch}")
        if is_git_repo(repo_dir):
            if task_number and not skip_branch:
                # Task mode: generate branch name from task number
                target_branch = generate_branch_name(task_number, task_title, agent_id)
                print(f"[LocalAgent] Creating worktree for task branch: {target_branch}")
                result = create_worktree(repo_dir, target_branch, task_number, agent_id)
                print(f"[LocalAgent] Worktree result: {result}")

                if result["success"]:
                    worktree_path = result["worktree_path"]
                    work_dir = worktree_path
                    branch_created = result["branch_created"]
                else:
                    target_branch = get_current_branch(repo_dir)
            elif target_branch:
                # If the requested branch is already checked out at repo_dir,
                # just use it directly — no point creating a duplicate worktree
                # (and `git worktree add` would fail for an already-checked-out
                # branch anyway).
                current = get_current_branch(repo_dir)
                if current == target_branch:
                    print(f"[LocalAgent] Branch '{target_branch}' already checked out at {repo_dir}, using it directly")
                    work_dir = repo_dir
                else:
                    print(f"[LocalAgent] Creating worktree for explicit branch: {target_branch}")
                    result = create_worktree(repo_dir, target_branch, 0, f"{target_branch}-{agent_id}")
                    print(f"[LocalAgent] Worktree result: {result}")

                    if result["success"]:
                        worktree_path = result["worktree_path"]
                        work_dir = worktree_path
                        branch_created = result["branch_created"]
                    else:
                        # Worktree creation failed — usually because the branch
                        # is already checked out in another worktree. Find that
                        # worktree and use it, so we don't end up running on
                        # whatever stale branch repo_dir happens to be on.
                        existing = find_worktree_for_branch(repo_dir, target_branch)
                        if existing:
                            print(f"[LocalAgent] Reusing existing worktree for '{target_branch}': {existing}")
                            worktree_path = existing
                            work_dir = existing
                        else:
                            print(f"[LocalAgent] Worktree create failed and no existing worktree for '{target_branch}'; falling back to repo_dir on '{current}'")
                            work_dir = repo_dir
                            target_branch = current
            else:
                # No task, no explicit branch: work in current directory
                target_branch = get_current_branch(repo_dir)

        # If deferring start, create the agent record in "prepared" status and return
        if defer_start:
            agent = LocalAgent(
                id=agent_id,
                task_id=task_id,
                task_number=task_number,
                task_title=task_title,
                task_description=task_description,
                repo_dir=repo_dir,
                work_dir=work_dir,
                worktree_path=worktree_path,
                branch=target_branch,
                branch_created=branch_created,
                status="prepared",
                cli_tool=provider.name,
                callback=callback,
                extra_env=extra_env,
            )
            self._agents[agent_id] = agent
            print(f"[LocalAgent] Session prepared (deferred start): {agent_id}")

            return {
                "id": agent_id,
                "task_id": task_id,
                "task_number": task_number,
                "task_title": task_title,
                "status": "prepared",
                "type": "local",
                "work_dir": work_dir,
                "worktree_path": worktree_path,
                "branch": target_branch,
                "branch_created": branch_created,
                "is_worktree": worktree_path is not None
            }

        # Build prompt and spawn CLI process immediately
        final_prompt = self._build_prompt(prompt, task_id, task_number, task_title, task_description, target_branch, worktree_path, work_dir)

        agent = LocalAgent(
            id=agent_id,
            task_id=task_id,
            task_number=task_number,
            task_title=task_title,
            task_description=task_description,
            repo_dir=repo_dir,
            work_dir=work_dir,
            worktree_path=worktree_path,
            branch=target_branch,
            branch_created=branch_created,
            status="starting",
            cli_tool=provider.name,
            callback=callback,
            extra_env=extra_env,
        )

        self._agents[agent_id] = agent

        # Push the initial user prompt to cerver so the transcript starts
        # with the user's question, not the agent's first response. Uses the
        # raw `prompt` arg (not the worktree-augmented final_prompt) — that's
        # what the user actually asked.
        if prompt:
            self._push_user_message(agent, prompt)

        try:
            self._start_cli_process(agent, final_prompt, system_prompt=system_prompt)

            return {
                "id": agent_id,
                "task_id": task_id,
                "task_number": task_number,
                "task_title": task_title,
                "status": agent.status,
                "type": "local",
                "cli_tool": agent.cli_tool,
                "work_dir": work_dir,
                "worktree_path": worktree_path,
                "branch": target_branch,
                "branch_created": branch_created,
                "is_worktree": worktree_path is not None
            }

        except Exception as e:
            agent.status = "failed"
            raise HTTPException(status_code=500, detail=f"Failed to start {provider.display_name}: {str(e)}")

    def _build_prompt(
        self,
        prompt: Optional[str],
        task_id: Optional[str],
        task_number: Optional[int],
        task_title: str,
        task_description: Optional[str],
        target_branch: Optional[str],
        worktree_path: Optional[str],
        work_dir: Optional[str] = None
    ) -> str:
        """Build the final prompt, prepending worktree/workspace info if applicable."""
        return build_agent_prompt(
            prompt=prompt,
            task_id=task_id,
            task_number=task_number,
            task_title=task_title,
            task_description=task_description,
            target_branch=target_branch,
            worktree_path=worktree_path,
        )

    def _get_provider(self, agent: LocalAgent) -> CliProvider:
        """Get the CLI provider for an agent."""
        return resolve_cli_provider(agent.cli_tool)

    def _start_cli_process(self, agent: LocalAgent, final_prompt: str, system_prompt: Optional[str] = None) -> None:
        """Spawn the CLI process and start reading output."""
        provider = self._get_provider(agent)
        cli_cmd = build_run_cli_command(
            provider, final_prompt, system_prompt=system_prompt
        )
        process = spawn_cli_subprocess(cli_cmd, agent.work_dir, extra_env=agent.extra_env)

        agent.pid = process.pid
        agent.process = process
        agent.status = "running"

        print(f"[LocalAgent] Started {provider.display_name}, PID: {process.pid}")

        self._output_tasks[agent.id] = asyncio.create_task(
            self._read_json_output(agent)
        )

    async def spawn_cli_process(self, agent_id: str, message: str, image_paths: List[str] = None) -> None:
        """Spawn a CLI process for a prepared session (first message).

        This is called when send_input detects a "prepared" agent.
        Builds the prompt from the message and starts the CLI process.
        """
        agent = self._agents.get(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        if agent.status != "prepared":
            raise HTTPException(status_code=400, detail=f"Agent is not in prepared state (status: {agent.status})")

        # Build the final prompt with worktree/workspace context + user message
        final_prompt = self._build_prompt(
            message, agent.task_id, agent.task_number,
            agent.task_title, agent.task_description,
            agent.branch, agent.worktree_path, agent.work_dir
        )

        print(f"[LocalAgent] Spawning CLI for prepared session {agent_id}")

        # Mirror the user's first message into cerver before the CLI starts
        # producing assistant output.
        self._push_user_message(agent, message)

        try:
            self._start_cli_process(agent, final_prompt)
        except Exception as e:
            agent.status = "failed"
            provider = self._get_provider(agent)
            raise HTTPException(status_code=500, detail=f"Failed to start {provider.display_name}: {str(e)}")

    async def _read_json_output(self, agent: LocalAgent) -> None:
        """Read JSON output from subprocess and broadcast to listeners."""
        loop = asyncio.get_event_loop()
        provider = self._get_provider(agent)

        def read_line():
            try:
                if agent.process and agent.process.stdout:
                    line = agent.process.stdout.readline()
                    return line
                return b''
            except Exception:
                return b''

        while agent.status == "running":
            try:
                line = await loop.run_in_executor(None, read_line)

                if not line:
                    break

                text = line.decode('utf-8', errors='replace').strip()
                if not text:
                    continue

                agent.last_activity = datetime.now()
                before_session_id = agent.session_id
                event = process_provider_output_text(agent, provider, text)
                if not event:
                    continue
                if agent.session_id and agent.session_id != before_session_id:
                    print(f"[LocalAgent] Got session_id: {agent.session_id}")
                await broadcast_to_agent_listeners(agent, event)

                # Push every event to cerver in the background (fire-and-forget).
                # Lets headless cron / workflow runs persist their full
                # transcript instead of just the final output.
                self._push_event_to_cerver(agent, event)

            except Exception as e:
                print(f"[LocalAgent] Read error: {e}")
                break

        if agent.process:
            agent.exit_code = agent.process.wait()

        # Belt-and-suspenders: when the read loop exits, flush the final
        # result text from the buffer to cerver. The streaming push already
        # handles each event during the run, but if the cerver POST for the
        # last event(s) failed (network blip, cerver 5xx) the transcript
        # would otherwise miss the answer. Idempotency is OK — cerver will
        # de-dup or just append; either way the answer is preserved.
        try:
            final_text = self._extract_result(agent)
            if final_text:
                self._post_transcript_entries(
                    agent,
                    [{"role": "assistant", "kind": "text", "content": final_text}],
                )
        except Exception as exc:
            print(f"[LocalAgent] final flush to cerver failed: {exc}")

        # Cron agents (with callback) should complete, not pause — they don't need
        # session resumption and would otherwise linger in the compute pool.
        if agent.callback:
            agent.status = "completed" if agent.exit_code == 0 else "failed"
            agent.session_id = None  # Don't keep session — allows cleanup
            print(f"[LocalAgent] Cron agent {agent.id} {agent.status} (exit={agent.exit_code})")

            await broadcast_to_agent_listeners(
                agent,
                {
                    "type": "exit",
                    "exit_code": agent.exit_code,
                },
            )

            await self._fire_callback(agent)
        elif agent.session_id:
            agent.status = "paused"
            print(f"[LocalAgent] Agent {agent.id} paused, session can be resumed")

            await broadcast_to_agent_listeners(
                agent,
                {
                    "type": "paused",
                    "exit_code": agent.exit_code,
                    "session_id": agent.session_id,
                    "can_resume": True,
                },
            )
        else:
            agent.status = "completed" if agent.exit_code == 0 else "failed"

            await broadcast_to_agent_listeners(
                agent,
                {
                    "type": "exit",
                    "exit_code": agent.exit_code,
                },
            )

    def _extract_result(self, agent: LocalAgent) -> str:
        """Extract the final result text from the agent's output buffer.

        Looks for the 'result' type message in the stream-json output.
        Falls back to collecting assistant message text content.
        """
        return extract_result_from_output_buffer(agent.output_buffer)

    def _event_to_cerver_entries(self, event: Dict) -> list:
        """Convert a normalized agent stream event into cerver
        SessionTranscriptEntry objects (one per content block).

        process_provider_output_text wraps every line as
        {"type": "output", "data": <inner-json-string>, "raw": <line>},
        so we have to parse the inner event before mapping. Inner events
        follow Claude Code's stream-json shape: assistant/user/result/system.
        """
        # Unwrap the outer "output" envelope to get the actual stream event.
        if event.get("type") == "output" and isinstance(event.get("data"), str):
            try:
                inner = json.loads(event["data"])
            except (json.JSONDecodeError, TypeError):
                return []
        else:
            inner = event

        etype = (inner or {}).get("type")
        entries = []
        if etype == "assistant":
            blocks = ((inner.get("message") or {}).get("content")) or []
            for b in blocks:
                btype = b.get("type")
                if btype == "text":
                    entries.append({"role": "assistant", "kind": "text", "content": b.get("text", "")})
                elif btype == "tool_use":
                    entries.append({
                        "role": "assistant",
                        "kind": "tool_use",
                        "content": "",
                        "tool_id": b.get("id"),
                        "tool_name": b.get("name"),
                        "tool_input": b.get("input"),
                    })
        elif etype == "user":
            blocks = ((inner.get("message") or {}).get("content")) or []
            for b in blocks:
                if b.get("type") == "tool_result":
                    raw = b.get("content")
                    if isinstance(raw, list):
                        text = "".join(c.get("text", "") for c in raw if isinstance(c, dict) and c.get("type") == "text")
                    else:
                        text = str(raw or "")
                    entries.append({
                        "role": "tool",
                        "kind": "tool_result",
                        "content": text,
                        "tool_id": b.get("tool_use_id"),
                        "is_error": bool(b.get("is_error")),
                    })
                elif b.get("type") == "text":
                    entries.append({"role": "user", "kind": "text", "content": b.get("text", "")})
        elif etype == "result":
            # Claude's final summary message at end of run. Capture it as a
            # final assistant entry so the transcript ends with the answer
            # the agent produced, not an in-flight tool_use.
            text = inner.get("result") or ""
            if text:
                entries.append({"role": "assistant", "kind": "text", "content": text})
        return entries

    def _post_transcript_entries(self, agent: LocalAgent, entries: list) -> None:
        """Fire-and-forget POST of transcript entries to cerver. No-op if the
        agent isn't bound to a cerver session (chat sessions started from the
        Kompany frontend write transcripts via the kompany API instead).
        """
        if not entries:
            return
        callback = agent.callback or {}
        cerver_url = callback.get("cerver_url")
        cerver_token = callback.get("cerver_api_token")
        cerver_session_id = callback.get("cerver_session_id")
        if not (cerver_url and cerver_token and cerver_session_id):
            return

        async def _push():
            import httpx
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.post(
                        f"{cerver_url.rstrip('/')}/v2/sessions/{cerver_session_id}/transcript",
                        json={"entries": entries},
                        headers={
                            "Authorization": f"Bearer {cerver_token}",
                            "Content-Type": "application/json",
                        },
                    )
            except Exception as exc:
                print(f"[LocalAgent] cerver transcript push failed: {exc}")

        try:
            asyncio.create_task(_push())
        except Exception:
            pass

    def _push_event_to_cerver(self, agent: LocalAgent, event: Dict) -> None:
        """Push one CLI stream event to cerver as transcript entries."""
        self._post_transcript_entries(agent, self._event_to_cerver_entries(event))

    def _push_user_message(self, agent: LocalAgent, content: str) -> None:
        """Push a user-side message (initial prompt or follow-up input) so the
        cerver transcript captures the full conversation, not just assistant
        output. Without this, cron / workflow sessions start at the agent's
        first response with no context for what was asked.
        """
        if not content:
            return
        self._post_transcript_entries(
            agent, [{"role": "user", "kind": "text", "content": content}]
        )

    async def _fire_callback(self, agent: LocalAgent) -> None:
        """Push transcript + status to cerver for cron-triggered agents.

        Callback config is expected to include cerver_url + cerver_api_token
        + cerver_session_id (Kompany sets these when scheduling the run).
        Falls back to nothing — no more Kompany /api/crons/callback hop.
        """
        import httpx

        callback = agent.callback
        if not callback:
            return

        cerver_url = callback.get("cerver_url")
        cerver_token = callback.get("cerver_api_token")
        cerver_session_id = callback.get("cerver_session_id")
        if not (cerver_url and cerver_token and cerver_session_id):
            print(f"[LocalAgent] _fire_callback: missing cerver fields for {agent.task_title}; skipping")
            return

        # Per-event transcript pushes happen in _push_event_to_cerver during
        # the run, so this callback only updates the lifecycle status.
        status = agent.status
        cerver_status = "completed" if status in ("completed", "paused") else "failed"

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                status_resp = await client.post(
                    f"{cerver_url.rstrip('/')}/v2/sessions/{cerver_session_id}/status",
                    json={"status": cerver_status, "end_reason": f"agent {status}"},
                    headers={
                        "Authorization": f"Bearer {cerver_token}",
                        "Content-Type": "application/json",
                    },
                )
                print(f"[LocalAgent] cerver status for {agent.task_title}: {status_resp.status_code}")
        except Exception as e:
            print(f"[LocalAgent] cerver status push failed for {agent.task_title}: {e}")

    async def _run_with_resume(self, agent: LocalAgent, message: str, image_paths: List[str] = None) -> None:
        """Run a follow-up message using session resume.

        Args:
            agent: The agent to resume
            message: The follow-up message
            image_paths: Optional list of image file paths (already included in message text)
        """
        if not agent.session_id:
            return

        provider = self._get_provider(agent)
        cli_cmd = build_resume_cli_command(provider, message, agent.session_id)

        if image_paths:
            print(f"[LocalAgent] Message includes {len(image_paths)} image paths for CLI to read")

        print(f"[LocalAgent] Resuming session {agent.session_id} with {provider.display_name}")

        process = spawn_cli_subprocess(cli_cmd, agent.work_dir, extra_env=agent.extra_env)

        agent.process = process
        agent.pid = process.pid
        agent.status = "running"

        await self._read_json_output(agent)

    def get(self, agent_id: str) -> Optional[dict]:
        """Get agent info by ID."""
        agent = self._agents.get(agent_id)
        if not agent:
            return None

        return {
            "id": agent.id,
            "task_id": agent.task_id,
            "task_number": agent.task_number,
            "task_title": agent.task_title,
            "status": agent.status,
            "type": "local",
            "cli_tool": agent.cli_tool,
            "work_dir": agent.work_dir,
            "worktree_path": agent.worktree_path,
            "branch": agent.branch,
            "branch_created": agent.branch_created,
            "is_worktree": agent.worktree_path is not None,
            "created_at": agent.created_at.isoformat(),
            "last_activity": agent.last_activity.isoformat(),
            "exit_code": agent.exit_code,
            "session_id": agent.session_id,
            "can_resume": agent.session_id is not None
        }

    def list(self) -> List[dict]:
        """List all agents."""
        return [
            {
                "id": a.id,
                "task_id": a.task_id,
                "task_number": a.task_number,
                "task_title": a.task_title,
                "status": a.status,
                "type": "local",
                "cli_tool": a.cli_tool,
                "branch": a.branch,
                "worktree_path": a.worktree_path,
                "created_at": a.created_at.isoformat(),
                "last_activity": a.last_activity.isoformat(),
                "session_id": a.session_id,
                "can_resume": a.session_id is not None
            }
            for a in self._agents.values()
        ]

    async def resume_session(self, agent_id: str, message: str, image_paths: List[str] = None) -> bool:
        """Resume an agent session with a follow-up message.

        Args:
            agent_id: The agent to resume
            message: The follow-up message (may already contain image references)
            image_paths: Optional list of image file paths to include
        """
        agent = self._agents.get(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        if not agent.session_id:
            raise HTTPException(
                status_code=400,
                detail="No session ID available. Cannot resume session."
            )

        if agent.status == "running":
            raise HTTPException(
                status_code=400,
                detail="Agent is already running. Wait for it to complete."
            )

        if image_paths:
            print(f"[LocalAgent] Resuming with {len(image_paths)} images: {image_paths}")

        # Push the follow-up user message before the resumed agent starts
        # streaming its response, so the cerver transcript reads in order.
        self._push_user_message(agent, message)

        try:
            if agent_id in self._output_tasks:
                self._output_tasks[agent_id].cancel()

            self._output_tasks[agent_id] = asyncio.create_task(
                self._run_with_resume(agent, message, image_paths)
            )

            return True

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to resume session: {str(e)}")

    def kill(self, agent_id: str, cleanup_worktree: bool = False) -> None:
        """Kill an agent and optionally cleanup worktree."""
        agent = self._agents.get(agent_id)
        if not agent:
            return

        print(f"[LocalAgent] Killing agent {agent_id}")

        # Cancel output reading task first
        if agent_id in self._output_tasks:
            self._output_tasks[agent_id].cancel()
            del self._output_tasks[agent_id]

        # Close stdout pipe to release file descriptor
        if agent.process and agent.process.stdout:
            try:
                agent.process.stdout.close()
            except Exception:
                pass

        # Terminate the process
        if agent.process:
            try:
                agent.process.terminate()
                try:
                    agent.process.wait(timeout=2)
                except Exception:
                    agent.process.kill()
                    agent.process.wait(timeout=1)
            except Exception:
                pass
        elif agent.pid:
            try:
                os.kill(agent.pid, signal.SIGTERM)
                try:
                    os.waitpid(agent.pid, os.WNOHANG)
                except Exception:
                    pass
            except ProcessLookupError:
                pass
            except Exception:
                try:
                    os.kill(agent.pid, signal.SIGKILL)
                except Exception:
                    pass

        agent.status = "stopped"

        if cleanup_worktree and agent.worktree_path and agent.repo_dir:
            remove_worktree(agent.repo_dir, agent.worktree_path)

        del self._agents[agent_id]
        print(f"[LocalAgent] Agent {agent_id} killed, {len(self._agents)} agents remaining")

    def add_listener(self, agent_id: str) -> asyncio.Queue:
        """Add an output listener for streaming."""
        agent = self._agents.get(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        queue = asyncio.Queue()

        for item in agent.output_buffer:
            if isinstance(item, dict):
                queue.put_nowait({"type": "output", **item})
            else:
                queue.put_nowait({"type": "output", "data": item})

        agent.output_listeners.append(queue)
        return queue

    def remove_listener(self, agent_id: str, queue: asyncio.Queue) -> None:
        """Remove an output listener."""
        agent = self._agents.get(agent_id)
        if agent and queue in agent.output_listeners:
            agent.output_listeners.remove(queue)

    def get_output(self, agent_id: str) -> str:
        """Get full output buffer."""
        agent = self._agents.get(agent_id)
        if not agent:
            return ""
        parts = []
        for item in agent.output_buffer:
            if isinstance(item, dict):
                parts.append(item.get("data", ""))
            else:
                parts.append(item)
        return "".join(parts)


# Singleton instance
agent_manager = LocalAgentManager()
