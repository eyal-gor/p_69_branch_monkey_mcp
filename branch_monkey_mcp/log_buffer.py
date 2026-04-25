"""
In-memory ring buffer for relay stdout/stderr.

The relay is often started by `uvx ... &` directly in a Terminal — its
output goes to that Terminal's screen, not to any file. That makes
remote diagnostics impossible: ~/.kompany/relay.log only fills when
launchd is in use, and `/tmp/relay.log` only fills when the operator
remembered to redirect stdout. Most of the time both are empty.

This module installs a tee on sys.stdout/sys.stderr that writes to the
original stream (so the operator still sees the live tail in their
Terminal) AND appends each completed line to a thread-safe deque. The
log-tail HTTP endpoint reads from that deque, so cerver / kompany /
any operator can pull recent output without SSH and without needing
the relay to have been launched a particular way.

Capped at MAX_LINES (~5000) so memory stays bounded.
"""

from __future__ import annotations

import sys
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Deque, List, Optional, TextIO, Tuple

MAX_LINES = 5000

_lock = threading.Lock()
_buffer: Deque[Tuple[str, str, str]] = deque(maxlen=MAX_LINES)
# Each entry: (iso_timestamp, "stdout"|"stderr", line_without_trailing_newline)


class _TeeStream:
    """File-like wrapper that writes to a real stream AND appends to
    the global ring buffer.

    Buffers partial writes per-stream until a newline arrives, so a line
    like 'Pushing event' that comes through three write() calls still
    ends up in the buffer as one entry.
    """

    def __init__(self, real: TextIO, label: str) -> None:
        self._real = real
        self._label = label
        self._partial = ""
        self._partial_lock = threading.Lock()

    # File-protocol methods used by print() / logging
    def write(self, data: str) -> int:
        try:
            written = self._real.write(data)
        except Exception:
            # Don't let a downstream stdout failure crash the relay.
            written = len(data)

        try:
            self._capture(data)
        except Exception:
            # Buffer must never raise — operator-side log is best-effort.
            pass

        return written if isinstance(written, int) else len(data)

    def flush(self) -> None:
        try:
            self._real.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        try:
            return self._real.isatty()
        except Exception:
            return False

    def fileno(self) -> int:
        return self._real.fileno()

    def writable(self) -> bool:
        return True

    # ----- internal -----

    def _capture(self, data: str) -> None:
        if not data:
            return
        with self._partial_lock:
            combined = self._partial + data
            *complete_lines, self._partial = combined.split("\n")
        if not complete_lines:
            return
        ts = datetime.now(timezone.utc).isoformat()
        with _lock:
            for line in complete_lines:
                _buffer.append((ts, self._label, line))


_installed = False


def install() -> None:
    """Replace sys.stdout / sys.stderr with tees. Idempotent.

    Call once during relay startup, before any worker threads are
    spawned, so every later print() / logging output is captured.
    """
    global _installed
    if _installed:
        return
    sys.stdout = _TeeStream(sys.stdout, "stdout")  # type: ignore[assignment]
    sys.stderr = _TeeStream(sys.stderr, "stderr")  # type: ignore[assignment]
    _installed = True


def get_lines(
    n: int = 200,
    grep: Optional[str] = None,
    stream: Optional[str] = None,
) -> List[dict]:
    """Return up to `n` recent lines from the buffer.

    Args:
        n: number of lines from the tail (capped at MAX_LINES)
        grep: optional substring filter (case-sensitive, NOT regex)
        stream: 'stdout' | 'stderr' | None (both)

    Returns: list of {timestamp, stream, line} dicts, oldest first.
    """
    n = max(1, min(n, MAX_LINES))
    with _lock:
        snapshot = list(_buffer)

    if stream:
        snapshot = [row for row in snapshot if row[1] == stream]
    if grep:
        snapshot = [row for row in snapshot if grep in row[2]]

    if len(snapshot) > n:
        snapshot = snapshot[-n:]

    return [
        {"timestamp": ts, "stream": label, "line": line}
        for ts, label, line in snapshot
    ]


def buffer_size() -> int:
    """Number of lines currently held in the buffer."""
    with _lock:
        return len(_buffer)


def is_installed() -> bool:
    return _installed
