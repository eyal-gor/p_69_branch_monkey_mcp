"""
Cerver / Kompany ASCII art logo.

Compact half-block pixel font, 2 lines tall.
Animated with smooth shimmer effect using 256-color gradient.

The relay is a cerver runtime — `cerver` is the platform brand. We render
that as the big logo and let `for kompany` live as the subtitle in the TUI
so both identities are present without competing for the eye.

Each letter encodes a 4-pixel-tall design in 2 display rows:
  █ = both top and bottom pixels filled
  ▀ = only top pixel filled
  ▄ = only bottom pixel filled
  (space) = both empty

To preview:
    python -m branch_monkey_mcp.logo
"""

import math
import random
from collections import deque

# ── letter definitions (2 display rows, half-block encoded) ──

# fmt: off
# Original kompany letters — kept around for the subtitle render path
# and so anyone landing here can compare style.
_k = ["█ ▄▀", "█▀▄ "]
_o = ["▄▀▀▄", "▀▄▄▀"]
_m = ["█▀▄▀█", "█ ▀ █"]
_p = ["█▀▀▄", "█▀▀ "]
_a = ["▄▀▀▄", "█▀▀█"]
_n = ["█▀▀▄", "█  █"]
_y = ["█  █", " ▀▀ "]

# Cerver letters — same half-block style.
_c = ["█▀▀▀", "█▄▄▄"]
_e = ["██▀▀", "██▄▄"]
_r = ["█▀▀▄", "█▀█ "]
_v = ["█  █", " ██ "]
# fmt: on

_LETTERS = [_c, _e, _r, _v, _e, _r]
_GAP = 1

# Build static logo lines
LOGO = []
for row in range(2):
    LOGO.append((" " * _GAP).join(letter[row] for letter in _LETTERS))

LOGO_WIDTH = max(len(line) for line in LOGO)
LOGO_HEIGHT = len(LOGO)


# ── 256-color gradient for smooth animation ──

# Indigo gradient: dark → bright → white. Reads well against the dark
# terminal bg and matches both the kompany #6366f1 and cerver palettes.
GRADIENT_COLORS = [56, 57, 63, 99, 105, 147, 189, 231]


# ── Noise for organic animation ──

def _noise2d(x: float, y: float) -> float:
    """Cheap 2D value noise using layered sines. Returns ~0.0–1.0."""
    v = 0.0
    v += math.sin(x * 0.7 + y * 1.3) * 0.5
    v += math.sin(x * 1.9 - y * 0.8 + 2.1) * 0.25
    v += math.sin(x * 0.4 + y * 2.7 + 5.3) * 0.25
    return (v + 1.0) / 2.0


# ── Rain animation: ripples spreading from random impact points ──
#
# Each "raindrop" lands at a random (x, y) inside the logo and births a
# ring of brightness that radiates outward, fading as it grows. Multiple
# ripples can be active at once; they additively brighten cells they
# touch. Drop spawn rate scales with workload — idle relay is sparse
# rain, busy relay is a downpour.
#
# State is module-level (mutable across calls) because the renderer
# calls get_animated_attrs once per row per frame; we want all rows of
# a given frame to see the same ripple field.

_RIPPLE_LIFETIME = 25       # frames a ripple is visible (~2.5s @ 10fps)
_RIPPLE_SPEED = 0.65        # cells per frame the ring spreads
_RIPPLE_THICKNESS = 1.8     # falloff width on either side of the ring
_BASELINE = 0.16            # min glyph brightness so the logo isn't dark between drops

_ripples = deque()          # (origin_x, origin_y, birth_frame)
_last_render_frame = -1     # spawn drops once per new frame, not per row


def _maybe_spawn(frame: int, workload: int) -> None:
    """Probabilistically spawn one new raindrop. Spawn-rate scales with
    workload (0 → ~1 drop / 3s, 4+ → ~1 drop / 0.3s). Capped so even a
    very busy relay doesn't strobe."""
    global _last_render_frame
    if frame == _last_render_frame:
        return
    _last_render_frame = frame

    # Garbage-collect dead ripples up front so the live list stays small.
    while _ripples and frame - _ripples[0][2] > _RIPPLE_LIFETIME:
        _ripples.popleft()

    drop_rate = 0.04 * (1 + min(workload, 4) * 1.4)
    if random.random() < drop_rate:
        rx = random.randint(0, max(0, LOGO_WIDTH - 1))
        ry = random.randint(0, max(0, LOGO_HEIGHT - 1))
        _ripples.append((rx, ry, frame))


def get_animated_attrs(frame: int, width: int, row: int = 0, workload: int = 0) -> list:
    """
    Return per-character glow intensity (0.0–1.0) for one logo row,
    composited from all active rain-ripples.

    Args:
        frame:    animation tick (incremented at the TUI's ~10fps)
        width:    number of cells in this logo row
        row:      which logo row (0..LOGO_HEIGHT-1)
        workload: count of running agents — scales drop spawn rate
    """
    _maybe_spawn(frame, workload)

    # Tiny breathe so the baseline isn't perfectly flat (organic feel
    # between raindrops).
    breathe = math.sin(frame * 0.08) * 0.04

    attrs = []
    for x in range(width):
        intensity = _BASELINE + breathe

        for rx, ry, birth in _ripples:
            age = frame - birth
            radius = age * _RIPPLE_SPEED
            dist = math.sqrt((x - rx) ** 2 + (row - ry) ** 2)
            ring_distance = abs(dist - radius)
            if ring_distance < _RIPPLE_THICKNESS:
                # Brightness at the ring's center, falling off either side,
                # multiplied by age-fade (newer ripples are brighter).
                age_factor = max(0.0, 1.0 - age / _RIPPLE_LIFETIME)
                edge_factor = 1.0 - (ring_distance / _RIPPLE_THICKNESS)
                ring = edge_factor * age_factor
                # Additive so overlapping ripples compound a little, but
                # cap so we don't blow out into pure white.
                intensity = min(1.0, intensity + ring * 0.85)

        attrs.append(max(0.0, min(1.0, intensity)))

    return attrs


if __name__ == "__main__":
    for line in LOGO:
        print(line)
    print(f"\n({LOGO_WIDTH} x {LOGO_HEIGHT})")
