"""
Cerver-owned websocket transport for private local compute.

This opens an outbound websocket from the local runtime to Cerver so the
hosted gateway can forward provider requests back to the local machine.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Dict, Optional
from urllib.parse import quote

import websockets

from ..kompany_local_transport.relay_forwarding import execute_local_request

INITIAL_RECONNECT_DELAY = 1.0
MAX_RECONNECT_DELAY = 30.0
RECONNECT_BACKOFF_MULTIPLIER = 2.0

StatusCallback = Callable[[str], None]
ConnectedCallback = Callable[[Dict[str, Any]], None]


def build_cerver_connect_ws_url(cerver_url: str, compute_id: str, api_token: str = "") -> str:
    base = cerver_url.strip().rstrip("/")
    if base.startswith("https://"):
        ws_base = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        ws_base = "ws://" + base[len("http://") :]
    else:
        ws_base = base

    return f"{ws_base}/v2/connect/ws?compute_id={quote(compute_id)}&token={quote(api_token)}"


class CerverConnectTransport:
    def __init__(
        self,
        *,
        cerver_url: str,
        api_token: str,
        compute_id: str,
        local_port: int,
        on_status: Optional[StatusCallback] = None,
        on_connected: Optional[ConnectedCallback] = None,
    ):
        self.cerver_url = cerver_url
        self.api_token = api_token
        self.compute_id = compute_id
        self.local_port = local_port
        self.on_status = on_status
        self.on_connected = on_connected

        self._running = False
        self._ws: Optional[websockets.WebSocketClientProtocol] = None

    def _emit_status(self, status: str) -> None:
        if self.on_status:
            self.on_status(status)

    async def run(self) -> None:
        self._running = True
        reconnect_attempts = 0

        while self._running:
            self._emit_status("connecting")
            try:
                await self._connect_once()
                reconnect_attempts = 0
            except asyncio.CancelledError:
                break
            except Exception as exc:
                reconnect_attempts += 1
                print(f"[Cerver] Connect channel reconnecting: {exc}")
                self._emit_status("connecting")
                delay = min(
                    INITIAL_RECONNECT_DELAY
                    * (RECONNECT_BACKOFF_MULTIPLIER ** max(0, reconnect_attempts - 1)),
                    MAX_RECONNECT_DELAY,
                )
                await asyncio.sleep(delay)

        await self.close()

    async def close(self) -> None:
        self._running = False
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def _connect_once(self) -> None:
        ws_url = build_cerver_connect_ws_url(self.cerver_url, self.compute_id, self.api_token)
        async with websockets.connect(
            ws_url,
            additional_headers={
                "Authorization": f"Bearer {self.api_token}",
            },
            ping_interval=30,
            ping_timeout=10,
            close_timeout=10,
        ) as ws:
            self._ws = ws
            self._emit_status("connected")

            async for raw in ws:
                await self._handle_message(raw)

        self._ws = None

    async def _handle_message(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return

        msg_type = payload.get("type")
        if msg_type == "connected":
            if self.on_connected:
                self.on_connected(payload)
            return

        if msg_type == "ping":
            await self._send_json({"type": "pong"})
            return

        if msg_type != "request":
            return

        response = await self._execute_request(payload)
        await self._send_json(response)

    async def _execute_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request_id = payload.get("request_id")
        request = {
            "id": request_id,
            "method": payload.get("method", "GET"),
            "path": payload.get("path", "/"),
            "headers": payload.get("headers", {}),
            "body": payload.get("body"),
        }

        response = await execute_local_request(self.local_port, request)
        return {
            "type": "response",
            "request_id": request_id,
            "status": response.get("status", 500),
            "headers": response.get("headers", {}),
            "body": response.get("body"),
        }

    async def _send_json(self, payload: Dict[str, Any]) -> None:
        if self._ws is None:
            raise RuntimeError("Cerver connect websocket is not connected")
        await self._ws.send(json.dumps(payload))
