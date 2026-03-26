"""
Cerver compute registration client for the local runtime.

This lets a p69-managed local machine register itself with Cerver as a
private compute, keep that compute alive with heartbeats, and unregister
on shutdown.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
import webbrowser

import httpx

from ..computer_runtime.capabilities import get_runtime_capabilities
from ..computer_runtime.machine_state import get_machine_state


DEFAULT_CERVER_URL = "https://cerver-gateway.gneyal.workers.dev"
CONFIG_DIR = Path.home() / ".kompany"
CERVER_COMPUTE_STATE_FILE = CONFIG_DIR / "cerver_compute.json"


def _normalize_base_url(url: str) -> str:
    return url.strip().rstrip("/")


def _load_cerver_state() -> Dict[str, Any]:
    if not CERVER_COMPUTE_STATE_FILE.exists():
        return {}

    try:
        return json.loads(CERVER_COMPUTE_STATE_FILE.read_text())
    except Exception:
        return {}


def _save_cerver_state(state: Dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CERVER_COMPUTE_STATE_FILE.write_text(json.dumps(state, indent=2))


class CerverComputeClient:
    def __init__(
        self,
        *,
        cerver_url: Optional[str],
        owner_id: Optional[str],
        local_port: int,
        machine_name: str,
        provider: str = "p69",
        api_token: Optional[str] = None,
    ):
        self.cerver_url = _normalize_base_url(
            cerver_url or os.environ.get("CERVER_GATEWAY_URL") or DEFAULT_CERVER_URL
        )
        self.owner_id = owner_id or os.environ.get("CERVER_OWNER_ID")
        self.local_port = local_port
        self.machine_name = machine_name
        self.provider = provider
        self.api_token = api_token or os.environ.get("CERVER_API_TOKEN")
        self.user_id: Optional[str] = None
        self.compute_id: Optional[str] = None

        self._load_persisted_auth()
        self._load_persisted_identity()

    @property
    def enabled(self) -> bool:
        return bool(self.cerver_url)

    def _auth_key(self) -> str:
        return f"auth::{self.cerver_url}"

    def _identity_key(self) -> str:
        owner_key = self.owner_id or self.user_id or "anonymous"
        return f"{self.cerver_url}|{owner_key}|{self.provider}|{self.local_port}"

    def _load_persisted_auth(self) -> None:
        state = _load_cerver_state()
        auth_state = state.get(self._auth_key())
        if not isinstance(auth_state, dict):
            return

        access_token = auth_state.get("access_token")
        user_id = auth_state.get("user_id")
        if not self.api_token and isinstance(access_token, str) and access_token:
            self.api_token = access_token
        if isinstance(user_id, str) and user_id:
            self.user_id = user_id

    def _load_persisted_identity(self) -> None:
        state = _load_cerver_state()
        compute_id = state.get(self._identity_key())
        if isinstance(compute_id, str) and compute_id:
            self.compute_id = compute_id

    def _persist_auth(self) -> None:
        if not self.api_token:
            return

        state = _load_cerver_state()
        state[self._auth_key()] = {
            "access_token": self.api_token,
            "user_id": self.user_id,
        }
        _save_cerver_state(state)

    def _persist_identity(self) -> None:
        if not self.compute_id:
            return

        state = _load_cerver_state()
        state[self._identity_key()] = self.compute_id
        _save_cerver_state(state)

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    def _build_metadata(self) -> Dict[str, Any]:
        machine_state = get_machine_state()
        return {
            "machine_name": self.machine_name,
            "mode": machine_state.get("mode"),
            "working_directory": machine_state.get("working_directory"),
            "home_directory": machine_state.get("home_directory"),
            "relay": machine_state.get("relay"),
            "relay_machine_id": machine_state.get("machine_id"),
        }

    def _build_connection(self) -> Dict[str, Any]:
        connection: Dict[str, Any] = {
            "base_url": f"http://127.0.0.1:{self.local_port}",
        }

        local_api_token = os.environ.get("P69_API_TOKEN")
        if local_api_token:
            connection["api_token"] = local_api_token

        return connection

    def _build_register_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "label": self.machine_name,
            "kind": "local",
            "provider": self.provider,
            "capabilities": get_runtime_capabilities(),
            "metadata": self._build_metadata(),
            "connection": self._build_connection(),
        }
        if self.owner_id:
            payload["owner_id"] = self.owner_id
        if self.compute_id:
            payload["compute_id"] = self.compute_id
        return payload

    async def ensure_authenticated(self) -> None:
        if self.api_token:
            return

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.cerver_url}/v2/auth/device",
                headers={"Content-Type": "application/json"},
                json={"machine_name": self.machine_name},
            )
            response.raise_for_status()
            start_payload = response.json()

        device_code = start_payload["device_code"]
        user_code = start_payload["user_code"]
        verification_uri = start_payload["verification_uri"]
        expires_in = int(start_payload.get("expires_in", 900))
        interval = int(start_payload.get("interval", 5))

        print("\n[Cerver] Starting browser login...")
        print(f"[Cerver] Visit: {verification_uri}")
        print(f"[Cerver] Code:  {user_code}")

        try:
            webbrowser.open(verification_uri)
        except Exception:
            pass

        deadline = asyncio.get_running_loop().time() + expires_in
        async with httpx.AsyncClient(timeout=30.0) as client:
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(interval)
                poll_response = await client.get(
                    f"{self.cerver_url}/v2/auth/device",
                    params={"device_code": device_code},
                )
                poll_payload = poll_response.json()

                if poll_payload.get("status") == "approved":
                    access_token = poll_payload.get("access_token")
                    user_id = poll_payload.get("user_id")
                    if not isinstance(access_token, str) or not access_token:
                        raise RuntimeError("Cerver auth approval did not return an access token")

                    self.api_token = access_token
                    self.user_id = user_id if isinstance(user_id, str) else None
                    self._persist_auth()
                    self._load_persisted_identity()
                    print("[Cerver] Login successful")
                    return

                error = poll_payload.get("error")
                if error == "access_denied":
                    raise RuntimeError("Cerver login was denied")
                if error == "expired_token":
                    raise RuntimeError("Cerver login expired before approval")

        raise RuntimeError("Timed out waiting for Cerver login approval")

    async def register(self) -> Dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("Cerver compute client is missing cerver_url")

        if not self.api_token and not self.owner_id:
            await self.ensure_authenticated()

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{self.cerver_url}/v2/computes/register",
                headers=self._headers(),
                json=self._build_register_payload(),
            )
            response.raise_for_status()
            payload = response.json()

        compute_id = payload.get("compute_id")
        if isinstance(compute_id, str) and compute_id:
            self.compute_id = compute_id
            self._persist_identity()

        return payload

    async def heartbeat(self, status: str = "online") -> Dict[str, Any]:
        if not self.compute_id:
            await self.register()

        if not self.compute_id:
            raise RuntimeError("Cerver compute registration did not return a compute_id")

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{self.cerver_url}/v2/computes/{self.compute_id}/heartbeat",
                headers=self._headers(),
                json={
                    "status": status,
                    "capabilities": get_runtime_capabilities(),
                    "metadata": self._build_metadata(),
                },
            )
            response.raise_for_status()
            return response.json()

    async def unregister(self) -> None:
        if not self.compute_id:
            return

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.delete(
                    f"{self.cerver_url}/v2/computes/{self.compute_id}",
                    headers=self._headers(),
                )
                response.raise_for_status()
        except Exception:
            return
