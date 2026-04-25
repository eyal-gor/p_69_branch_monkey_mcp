"""
Log tail endpoints for the relay.

Lets cerver (or any operator) read recent relay log lines without SSH.
Reachable through cerver as:

  POST /v2/computes/<compute_id>/exec
  body: { "method": "GET", "path": "/api/local-claude/logs/tail",
           "query": { "n": "200", "grep": "transcript" } }

Cerver routes that through the connect channel to this relay; the
response body is a JSON list of log lines.
"""

import os
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException

router = APIRouter()

CONFIG_DIR = Path.home() / ".kompany"
DEFAULT_LOG_PATH = CONFIG_DIR / "relay.log"
ERR_LOG_PATH = CONFIG_DIR / "relay.err.log"
NOHUP_LOG_PATH = Path("/tmp/relay.log")

# Hard cap on lines returned in one call. Stops a runaway grep from
# pulling 100k lines through the connect channel.
MAX_LINES = 2000
DEFAULT_LINES = 200


def _resolve_log_path(name: str) -> Path:
    """Map a friendly log-file name to a real path.

    Accepts:
      - 'relay'  → ~/.kompany/relay.log (launchd stdout)
      - 'err'    → ~/.kompany/relay.err.log (launchd stderr)
      - 'nohup'  → /tmp/relay.log (manual `nohup uvx ...` runs)
    """
    if name == "err":
        return ERR_LOG_PATH
    if name == "nohup":
        return NOHUP_LOG_PATH
    return DEFAULT_LOG_PATH


def _tail_file(path: Path, n: int) -> List[str]:
    """Return the last `n` lines of `path` (UTF-8, errors=replace).

    Uses an O(n) backwards seek instead of reading the whole file —
    cheap even on multi-megabyte logs.
    """
    if not path.exists():
        return []

    n = max(1, min(n, MAX_LINES))
    block_size = 4096
    data = b""
    line_count = 0

    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        end = f.tell()
        pos = end
        while pos > 0 and line_count <= n:
            read_size = min(block_size, pos)
            pos -= read_size
            f.seek(pos)
            chunk = f.read(read_size)
            data = chunk + data
            line_count = data.count(b"\n")

    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    return lines[-n:] if len(lines) > n else lines


@router.get("/logs/tail")
def tail_logs(
    n: int = DEFAULT_LINES,
    grep: Optional[str] = None,
    file: str = "buffer",
    stream: Optional[str] = None,
):
    """Return recent relay log lines.

    Query params:
      n      — number of lines from the tail (default 200, max 2000)
      grep   — optional substring filter (case-sensitive, NOT regex —
               kept simple to avoid ReDoS surprises across the connect
               channel)
      file   — 'buffer' (in-memory ring, default — works regardless of
               how the relay was launched), or 'relay' / 'err' / 'nohup'
               for explicit on-disk reads
      stream — 'stdout' | 'stderr' | None (only used when file='buffer')
    """
    if file == "buffer":
        try:
            from ...log_buffer import get_lines, buffer_size, is_installed
        except Exception as exc:
            return {
                "source": "buffer",
                "error": f"log_buffer unavailable: {exc}",
                "lines": [],
                "total_returned": 0,
                "filtered_by": grep,
            }

        rows = get_lines(n=n, grep=grep, stream=stream)
        return {
            "source": "buffer",
            "installed": is_installed(),
            "buffer_size": buffer_size(),
            "lines": rows,
            "total_returned": len(rows),
            "filtered_by": grep,
            "filtered_by_stream": stream,
        }

    path = _resolve_log_path(file)
    if not path.exists():
        return {
            "source": "file",
            "log_path": str(path),
            "exists": False,
            "lines": [],
            "total_returned": 0,
            "filtered_by": grep,
        }

    lines = _tail_file(path, n)
    if grep:
        lines = [ln for ln in lines if grep in ln]

    return {
        "source": "file",
        "log_path": str(path),
        "exists": True,
        "lines": lines,
        "total_returned": len(lines),
        "filtered_by": grep,
    }


@router.get("/logs/files")
def list_log_files():
    """List the known log files and whether each exists / its size."""
    out = []
    for name, path in (
        ("relay", DEFAULT_LOG_PATH),
        ("err", ERR_LOG_PATH),
        ("nohup", NOHUP_LOG_PATH),
    ):
        try:
            size = path.stat().st_size if path.exists() else None
        except Exception:
            size = None
        out.append({
            "name": name,
            "path": str(path),
            "exists": path.exists(),
            "size_bytes": size,
        })
    return {"files": out}
