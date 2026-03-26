"""
Kompany-specific forwarding helpers for cloud-to-local requests.
"""

from typing import Any, Dict

import httpx


def build_local_url(local_port: int, path: str) -> str:
    return f"http://127.0.0.1:{local_port}{path}"


async def execute_local_request(local_port: int, request: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a cloud-forwarded request against the local server."""
    request_id = request.get("id")
    method = request.get("method", "GET")
    path = request.get("path", "/")
    body = request.get("body", {})
    headers = request.get("headers", {})

    url = build_local_url(local_port, path)

    try:
        read_timeout = 55 if method == "GET" else 180
        async with httpx.AsyncClient() as client:
            if method == "GET":
                response = await client.get(url, headers=headers, timeout=read_timeout)
            elif method == "POST":
                response = await client.post(url, json=body, headers=headers, timeout=read_timeout)
            elif method == "PUT":
                response = await client.put(url, json=body, headers=headers, timeout=read_timeout)
            elif method == "DELETE":
                response = await client.delete(url, headers=headers, timeout=read_timeout)
            elif method == "PATCH":
                response = await client.patch(url, json=body, headers=headers, timeout=read_timeout)
            else:
                return {
                    "type": "response",
                    "id": request_id,
                    "status": 405,
                    "body": {"error": f"Method {method} not supported"},
                }

            try:
                response_body = response.json()
            except Exception:
                response_body = {"text": response.text}

            return {
                "type": "response",
                "id": request_id,
                "status": response.status_code,
                "body": response_body,
            }
    except Exception as exc:
        return {
            "type": "response",
            "id": request_id,
            "status": 500,
            "body": {"error": str(exc) or f"{type(exc).__name__}: unknown error"},
        }
