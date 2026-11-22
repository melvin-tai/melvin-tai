#!/usr/bin/env python3
"""
Turn a photo into ASCII art, if you ever want to replace the owl.

    pip install pillow
    python tools/make_ascii.py photo.jpg                # writes ascii.txt
    python tools/make_ascii.py photo.jpg --cols 40 --rows 25 --invert

A crop of your face or a logo with a plain background works best.
Dense characters (@, #) are drawn where the image is BRIGHT, which suits
dark mode. Use --invert if the picture reads better the other way round.
"""
import argparse
from pathlib import Path

from PIL import Image, ImageOps

RAMP = " .,:;i1tfLCG08@"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("image")
    p.add_argument("--cols", type=int, default=40)
    p.add_argument("--rows", type=int, default=25, help="lines; match your card's line count")
    p.add_argument("--invert", action="store_true")
    p.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "ascii.txt"))
    a = p.parse_args()

    img = ImageOps.exif_transpose(Image.open(a.image)).convert("L")
    img = ImageOps.autocontrast(img, cutoff=2)
    if a.invert:
        img = ImageOps.invert(img)
    # Resizing to exactly cols × rows corrects for characters being ~2× taller than wide.
    img = img.resize((a.cols, a.rows), Image.LANCZOS)

    px = img.load()
    lines = []
    for y in range(a.rows):
        row = "".join(RAMP[px[x, y] * (len(RAMP) - 1) // 255] for x in range(a.cols))
        lines.append(row.rstrip())
    Path(a.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {a.out} ({a.cols}×{a.rows})")


if __name__ == "__main__":
    main()
