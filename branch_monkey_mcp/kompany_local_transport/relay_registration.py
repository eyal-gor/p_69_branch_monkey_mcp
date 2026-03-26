"""
Kompany-specific relay registration and heartbeat helpers.
"""

from typing import Any, Dict, Optional

import httpx


def build_cloud_heartbeat_payload(
    machine_id: str,
    machine_name: str,
    local_port: int,
    status: str = "online",
) -> Dict[str, Any]:
    return {
        "machine_id": machine_id,
        "machine_name": machine_name,
        "status": status,
        "local_port": local_port,
    }


async def post_cloud_heartbeat(
    cloud_url: str,
    access_token: Optional[str],
    machine_id: str,
    machine_name: str,
    local_port: int,
    status: str = "online",
) -> Dict[str, Any]:
    headers = {}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{cloud_url}/api/relay/heartbeat",
            headers=headers,
            json=build_cloud_heartbeat_payload(
                machine_id=machine_id,
                machine_name=machine_name,
                local_port=local_port,
                status=status,
            ),
            timeout=15,
        )
        response.raise_for_status()
        return response.json()


async def post_local_heartbeat(
    local_port: int,
    machine_id: str,
    machine_name: str,
    cloud_url: str,
) -> None:
    async with httpx.AsyncClient() as client:
        await client.post(
            f"http://127.0.0.1:{local_port}/api/relay/heartbeat",
            json={
                "machine_id": machine_id,
                "machine_name": machine_name,
                "cloud_url": cloud_url,
            },
            timeout=5,
        )


async def post_local_disconnect(local_port: int) -> None:
    async with httpx.AsyncClient() as client:
        await client.post(
            f"http://127.0.0.1:{local_port}/api/relay/disconnect",
            timeout=5,
        )
