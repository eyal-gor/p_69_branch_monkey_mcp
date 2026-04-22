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


def get_animated_attrs(frame: int, width: int, row: int = 0) -> list:
    """
    Return per-character glow intensity for one logo row.

    Returns a list of floats (0.0–1.0) representing brightness.
    Two fast-moving shimmer waves create a nimble sparkle effect.
    """
    t = frame * 0.06

    attrs = []
    for x in range(width):
        nx = x / max(width, 1)

        # Primary shimmer — tight, fast
        c1 = math.sin(t * 0.5) * 0.5 + 0.5
        shimmer1 = math.exp(-((nx - c1) ** 2) * 30)

        # Secondary shimmer — offset phase, slightly slower
        c2 = math.sin(t * 0.35 + 2.0) * 0.5 + 0.5
        shimmer2 = math.exp(-((nx - c2) ** 2) * 40) * 0.7

        # Subtle noise for organic feel
        noise = _noise2d(x * 0.12 + t * 0.4, row * 0.5 + t * 0.25) * 0.08

        # Dim base + shimmer peaks
        brightness = 0.18 + max(shimmer1, shimmer2) * 0.82 + noise

        # Gentle breathe
        breathe = math.sin(t * 1.8) * 0.03
        brightness += breathe

        attrs.append(max(0.0, min(1.0, brightness)))

    return attrs


if __name__ == "__main__":
    for line in LOGO:
        print(line)
    print(f"\n({LOGO_WIDTH} x {LOGO_HEIGHT})")
