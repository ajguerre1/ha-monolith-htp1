"""Generate `brand/icon.png` and `brand/icon@2x.png` from the supplied brand artwork.

    python scripts/make_brand_icons.py path/to/Monolith.png

The source is the manufacturer's logo lockup — the monument mark, a rule beneath it, and the
word MONOLITH — laid out wide on a near-black ground. Home Assistant renders an integration
icon at roughly 48 pixels in the integrations list, where that whole lockup would be unusable:
the word alone would be about four pixels tall. **Only the mark is used**, which is what a mark
is for.

The dark ground is kept rather than dropped for transparency. The artwork is white, so a
transparent version would be invisible against any light theme. Keeping the brand's own ground
is both faithful and legible on either theme.

The wide source is not committed. It is the manufacturer's marketing asset and the repository
only needs what it renders; run this against a local copy if the icons ever need regenerating.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[1]
BRAND_DIR = REPO_ROOT / "custom_components" / "ha_monolith_htp1" / "brand"

# Sampled from the source's own background rather than guessed.
GROUND = (18, 22, 23, 255)
# How much of the square the mark spans. Enough to read at 48 px, with margin so the mark does
# not collide with the rounded corners.
MARK_SPAN = 0.66
# Proportional corner radius, the usual app-icon treatment, so a dark tile does not sit as a
# hard-edged square beside the rounded icons Home Assistant shows around it.
CORNER = 0.18
# Anything at or above this luminance is artwork; the ground sits near 20.
INK = 200


def extract_mark(source: Image.Image) -> Image.Image:
    """The monument and its rule, as white-on-transparent, tightly trimmed.

    Bands of artwork are found by scanning rows, then the wordmark — always the last band, and
    separated from the rule by a wide gap — is dropped.
    """
    grey = source.convert("L")
    width, height = grey.size
    pixels = grey.load()

    rows = [any(pixels[x, y] >= INK for x in range(0, width, 2)) for y in range(height)]
    bands: list[tuple[int, int]] = []
    start: int | None = None
    for y, filled in enumerate(rows):
        if filled and start is None:
            start = y
        elif not filled and start is not None:
            bands.append((start, y - 1))
            start = None
    if start is not None:
        bands.append((start, height - 1))
    if len(bands) < 2:
        raise SystemExit(f"expected at least two bands of artwork, found {len(bands)}")

    # The mark is everything above the largest vertical gap: monument, then rule, then a wide
    # space, then the word.
    gaps = [(bands[i + 1][0] - bands[i][1], i) for i in range(len(bands) - 1)]
    _, split = max(gaps)
    top, bottom = bands[0][0], bands[split][1]

    # White where the source is artwork, transparent elsewhere — so the ground's wave texture,
    # which is noise at this size, does not come along.
    region = grey.crop((0, top, width, bottom + 1))
    mask = region.point(lambda v: 255 if v >= INK else 0, mode="L")
    mark = Image.new("RGBA", region.size, (255, 255, 255, 0))
    mark.putalpha(mask)
    mark.paste((255, 255, 255, 255), (0, 0), mask)
    return mark.crop(mark.getbbox())


def render(mark: Image.Image, size: int) -> Image.Image:
    span = int(size * MARK_SPAN)
    scale = min(span / mark.width, span / mark.height)
    scaled = mark.resize(
        (max(1, round(mark.width * scale)), max(1, round(mark.height * scale))),
        Image.LANCZOS,
    )

    tile = Image.new("RGBA", (size, size), GROUND)
    tile.paste(scaled, ((size - scaled.width) // 2, (size - scaled.height) // 2), scaled)

    rounded = Image.new("L", (size, size), 0)
    ImageDraw.Draw(rounded).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=int(size * CORNER), fill=255
    )
    tile.putalpha(rounded)
    return tile


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    source = Image.open(sys.argv[1])
    source.load()
    mark = extract_mark(source)
    print(f"mark extracted: {mark.width}x{mark.height} from {source.width}x{source.height}")

    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
        out = BRAND_DIR / name
        render(mark, size).save(out, "PNG", optimize=True)
        print(f"wrote {out.relative_to(REPO_ROOT)}  {size}x{size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
