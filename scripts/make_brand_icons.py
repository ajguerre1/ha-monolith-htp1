"""Generate the brand icons HACS and the Home Assistant brands repository require.

Run: python scripts/make_brand_icons.py

Produces `custom_components/ha_monolith_htp1/brand/icon.png` (256x256) and `icon@2x.png`
(512x512), matching the Home Assistant brands specification: square PNG, RGBA, full-bleed.

The artwork is ORIGINAL and deliberately generic -- a volume gauge, not any manufacturer's
logo or trademark. It exists so the HACS `brands` check passes from this repository (HACS
looks for brand/icon.png here before falling back to the brands repo) and so there is
something to submit when the home-assistant/brands pull request is raised. Replace it with
better artwork whenever someone wants to; nothing depends on these exact pixels.

Everything is drawn at 8x and downsampled, because PIL has no antialiasing of its own.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[1]
BRAND_DIR = REPO_ROOT / "custom_components" / "ha_monolith_htp1" / "brand"

SUPERSAMPLE = 8

BACKGROUND = (26, 32, 44, 255)  # deep slate
ACCENT = (245, 166, 35, 255)  # amber
TRACK = (55, 65, 81, 255)  # muted slate, the unlit part of the gauge

# The gauge is a 270-degree sweep with the gap at the bottom, and the pointer sits at about
# two-thirds of travel -- a volume control that reads as "audio" rather than "settings" at
# 24 px, where every finer detail disappears anyway.
GAUGE_START_DEG = 135.0
GAUGE_SWEEP_DEG = 270.0
POINTER_FRACTION = 0.66


def _render(size: int) -> Image.Image:
    s = size * SUPERSAMPLE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Full-bleed rounded square. Home Assistant renders brand icons on varied backgrounds,
    # so the icon carries its own.
    draw.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=BACKGROUND)

    centre = s / 2
    radius = s * 0.29
    width = int(s * 0.085)
    box = [centre - radius, centre - radius, centre + radius, centre + radius]

    # PIL measures arcs clockwise from 3 o'clock, which is the mirror of the usual maths
    # convention; the whole gauge is drawn in PIL's terms to avoid converting twice.
    draw.arc(box, GAUGE_START_DEG, GAUGE_START_DEG + GAUGE_SWEEP_DEG, fill=TRACK, width=width)
    draw.arc(
        box,
        GAUGE_START_DEG,
        GAUGE_START_DEG + GAUGE_SWEEP_DEG * POINTER_FRACTION,
        fill=ACCENT,
        width=width,
    )

    # Pointer, from just off centre out to just inside the gauge track.
    angle = math.radians(GAUGE_START_DEG + GAUGE_SWEEP_DEG * POINTER_FRACTION)
    inner, outer = s * 0.055, radius - width * 0.85
    draw.line(
        [
            centre + inner * math.cos(angle),
            centre + inner * math.sin(angle),
            centre + outer * math.cos(angle),
            centre + outer * math.sin(angle),
        ],
        fill=ACCENT,
        width=int(width * 0.8),
    )

    hub = s * 0.045
    draw.ellipse([centre - hub, centre - hub, centre + hub, centre + hub], fill=ACCENT)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    for size, name in ((256, "icon.png"), (512, "icon@2x.png")):
        path = BRAND_DIR / name
        _render(size).save(path, "PNG", optimize=True)
        print(f"wrote {path.relative_to(REPO_ROOT)} ({size}x{size})")


if __name__ == "__main__":
    main()
