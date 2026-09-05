import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from historycal import theme

HEX_RE = re.compile(r"^#[0-9a-f]{6}$")


def test_palette_is_deterministic():
    p1 = theme.palette_for_date(2026, 9, 5)
    p2 = theme.palette_for_date(2026, 9, 5)
    assert p1 == p2


def test_palette_differs_across_days():
    seen = set()
    for day in range(1, 29):
        p = theme.palette_for_date(2026, 2, day)
        seen.add(p["bg_top"])
    # not a strict guarantee (hash collisions are astronomically unlikely
    # here, but let's just sanity check we get a good spread)
    assert len(seen) >= 25


def test_palette_values_are_valid_hex_colors():
    p = theme.palette_for_date(-5000, 6, 15)   # far past year too
    for key in ("bg_top", "bg_bottom", "accent", "accent_dark",
                "card_top", "card_bottom", "shadow", "highlight"):
        assert HEX_RE.match(p[key]), f"{key} = {p[key]!r} is not valid #rrggbb"


def test_flavor_text_deterministic_and_valid():
    f1 = theme.flavor_text_for_date(2026, 9, 5)
    f2 = theme.flavor_text_for_date(2026, 9, 5)
    assert f1 == f2
    assert f1 in theme.FLAVOR_TEXTS


def test_blend_endpoints():
    assert theme._blend("#000000", "#ffffff", 0.0) == "#000000"
    assert theme._blend("#000000", "#ffffff", 1.0) == "#ffffff"
    mid = theme._blend("#000000", "#ffffff", 0.5)
    assert mid in ("#7f7f7f", "#808080")


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK  {t.__name__}")
    print(f"\nAll {len(tests)} theme tests passed.")
