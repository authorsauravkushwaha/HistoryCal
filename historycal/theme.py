"""
theme.py
========

Two jobs:

1. Generate a colour palette *deterministically* from a date, so every
   single day of the (infinite) calendar has its own distinct "war room"
   colour mood - but reopening the app on the same day always looks the
   same, instead of randomly repainting itself.

2. Provide drawing helpers that turn a plain Tkinter Canvas into something
   that *reads* as 3D: a soft drop shadow, a top-to-bottom gradient (Canvas
   has no built-in gradient fill, so we fake it with many thin stacked
   rectangles), and a bevelled highlight/shadow edge - the same trick used
   by old-school skeuomorphic UI buttons. No images, no extra libraries,
   works anywhere Python + Tkinter run.
"""

from __future__ import annotations

import colorsys
import hashlib


FLAVOR_TEXTS = [
    "Another Day, Another Battle",
    "History Never Sleeps",
    "Empires Rise and Fall",
    "Chronicles Unfold",
    "The Front Line of Time",
    "A New Chapter Begins",
    "War Rooms and Treaties",
    "Echoes of Old Campaigns",
    "The Calendar Remembers",
    "Yesterday's Battles, Today's Lesson",
    "Kingdoms in Motion",
    "The March of History",
]


def _hash_bytes(*parts) -> bytes:
    key = "-".join(str(p) for p in parts).encode("utf-8")
    return hashlib.sha256(key).digest()


def _hex(rgb: tuple[float, float, float]) -> str:
    r, g, b = (max(0, min(255, round(c * 255))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def palette_for_date(year: int, month: int, day: int) -> dict:
    """A small, curated colour palette derived from the date. Hue is
    randomised (via hash) across the full wheel; saturation/lightness are
    kept inside ranges chosen to look like dramatic "war room" banners
    (deep, rich backgrounds; a bright metallic accent) instead of random
    neon garbage."""
    h = _hash_bytes(year, month, day)

    hue = int.from_bytes(h[0:2], "big") / 65535.0            # 0..1
    accent_hue = (hue + 0.5 + (h[2] / 255.0 - 0.5) * 0.2) % 1.0  # roughly complementary

    bg_top = colorsys.hls_to_rgb(hue, 0.16, 0.55)
    bg_bottom = colorsys.hls_to_rgb(hue, 0.07, 0.55)
    accent = colorsys.hls_to_rgb(accent_hue, 0.55, 0.65)
    accent_dark = colorsys.hls_to_rgb(accent_hue, 0.35, 0.55)

    return {
        "bg_top": _hex(bg_top),
        "bg_bottom": _hex(bg_bottom),
        "accent": _hex(accent),
        "accent_dark": _hex(accent_dark),
        "card_top": colors_lighten(hue),
        "card_bottom": colors_darken(hue),
        "shadow": "#05050a",
        "highlight": "#ffffff",
    }


def neutral_card_palette() -> dict:
    """A single fixed 'steel plaque' palette shared by every ordinary
    (non-selected) day cell in the grid. Using one shared look for the
    grid - rather than a different random hue per cell - keeps 30+ cells
    calm and readable; the per-day colour excitement instead goes into
    the big background gradient and the selected-day glow (see ui.py)."""
    hue = 0.58  # steel blue
    return {
        "card_top": colors_lighten(hue),
        "card_bottom": colors_darken(hue),
        "shadow": "#05050a",
        "highlight": "#ffffff",
        "accent": "#d4af37",   # muted gold, used for "has event" dots
    }


def colors_lighten(hue: float) -> str:
    return _hex(colorsys.hls_to_rgb(hue, 0.30, 0.35))


def colors_darken(hue: float) -> str:
    return _hex(colorsys.hls_to_rgb(hue, 0.14, 0.35))


def flavor_text_for_date(year: int, month: int, day: int) -> str:
    h = _hash_bytes("flavor", year, month, day)
    idx = h[0] % len(FLAVOR_TEXTS)
    return FLAVOR_TEXTS[idx]


# ---------------------------------------------------------------------
# Canvas drawing helpers - the "pseudo-3D" rendering trick
# ---------------------------------------------------------------------

def _blend(hex_a: str, hex_b: str, t: float) -> str:
    """Linear-interpolate between two #rrggbb colours, t in [0, 1]."""
    a = tuple(int(hex_a[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(hex_b[i:i + 2], 16) for i in (1, 3, 5))
    mixed = tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))
    return f"#{mixed[0]:02x}{mixed[1]:02x}{mixed[2]:02x}"


def draw_vertical_gradient(canvas, x1, y1, x2, y2, color_top, color_bottom,
                            steps: int = 24, **kwargs):
    """Fake a smooth top-to-bottom gradient fill using stacked thin
    rectangles - Tkinter's Canvas has no native gradient support."""
    height = max(1, y2 - y1)
    band = max(1, height / steps)
    ids = []
    for i in range(steps):
        t = i / max(1, steps - 1)
        color = _blend(color_top, color_bottom, t)
        by1 = y1 + i * band
        by2 = y1 + (i + 1) * band + 1   # +1 avoids thin seams between bands
        ids.append(canvas.create_rectangle(x1, by1, x2, by2, fill=color,
                                            outline=color, **kwargs))
    return ids


def draw_3d_card(canvas, x1, y1, x2, y2, palette, *, depth=5, radius=0,
                  selected=False):
    """Draw one 'raised card' - a day cell that looks bevelled/extruded
    rather than flat. Layering, from back to front:
      1. a soft drop shadow (several offset layers = poor man's blur)
      2. the gradient face
      3. a bright top-left highlight edge + darker bottom-right shadow
         edge, tinted from the card's own colours (not flat black/white)
         so the bevel looks like it belongs to the object, not pasted on
      4. (optional) a soft glowing accent border if the cell is selected
    """
    shadow_color = palette["shadow"]
    for offset in range(depth, 0, -1):
        stipple = "gray25" if offset == depth else ("gray50" if offset > depth // 2 else "")
        canvas.create_rectangle(x1 + offset, y1 + offset, x2 + offset, y2 + offset,
                                 fill=shadow_color, outline=shadow_color,
                                 stipple=stipple)

    draw_vertical_gradient(canvas, x1, y1, x2, y2,
                            palette["card_top"], palette["card_bottom"])

    highlight = _blend(palette["card_top"], "#ffffff", 0.65)
    inner_shadow = _blend(palette["card_bottom"], "#000000", 0.6)
    canvas.create_line(x1, y1, x2, y1, fill=highlight, width=2)
    canvas.create_line(x1, y1, x1, y2, fill=highlight, width=2)
    canvas.create_line(x1, y2, x2, y2, fill=inner_shadow, width=2)
    canvas.create_line(x2, y1, x2, y2, fill=inner_shadow, width=2)

    if selected:
        accent = palette["accent"]
        for i, w in enumerate((6, 4, 2)):
            canvas.create_rectangle(x1 - w // 2, y1 - w // 2, x2 + w // 2, y2 + w // 2,
                                     outline=accent, width=1,
                                     stipple="gray25" if i == 0 else ("gray50" if i == 1 else ""))
