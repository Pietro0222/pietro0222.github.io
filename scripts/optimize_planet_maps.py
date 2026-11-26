#!/usr/bin/env python3
"""Optimize the planet maps (holomap/i/*-map.webp) used by the HOLOMAP system view.

For every map it does two things, in this order:

1. preview: creates holomap/i/1k/<name>-map.webp at 1024x512 from the original.
   The system view loads this light version first and switches to the
   full-size map only when the camera gets close to the planet. Maps that are
   1024 px wide or less get no preview (the page falls back to the original).
2. recompress: re-encodes the original in place at a lower webp quality, but
   keeps the new file only if it is at least MIN_SAVING smaller. A map that
   was already optimized does not shrink enough to be replaced again, so the
   script can be run repeatedly without degrading the images.

Requires ImageMagick (`magick`). Existing previews are never regenerated, so
running it again after adding new planets only processes the new maps.

Usage:
    python3 scripts/optimize_planet_maps.py [--quality 75] [--preview-quality 80] [--jobs 8]
"""

import argparse
import concurrent.futures
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "holomap" / "i"
DST = SRC / "1k"
PREVIEW_WIDTH = 1024
MIN_SAVING = 0.10


def width_of(path):
    out = subprocess.run(["magick", "identify", "-format", "%w", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return int(out.split()[0])


def process(src, quality, preview_quality):
    before = src.stat().st_size
    preview = "none"
    dst = DST / src.name
    if dst.exists():
        preview = "kept"
    elif width_of(src) > PREVIEW_WIDTH:
        tmp = dst.with_suffix(".tmp.webp")
        subprocess.run(["magick", str(src), "-resize", f"{PREVIEW_WIDTH}x{PREVIEW_WIDTH // 2}",
                        "-quality", str(preview_quality), str(tmp)], check=True)
        tmp.replace(dst)
        preview = "made"

    tmp = src.with_suffix(".tmp.webp")
    subprocess.run(["magick", str(src), "-quality", str(quality), str(tmp)], check=True)
    after = tmp.stat().st_size
    if after <= before * (1 - MIN_SAVING):
        tmp.replace(src)
        return preview, before, after
    tmp.unlink()
    return preview, before, before


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quality", type=int, default=75, help="webp quality of the full-size maps")
    ap.add_argument("--preview-quality", type=int, default=80, help="webp quality of the 1024 previews")
    ap.add_argument("--jobs", type=int, default=8)
    args = ap.parse_args()

    DST.mkdir(exist_ok=True)
    maps = sorted(p for p in SRC.glob("*-map.webp") if not p.name.endswith(".tmp.webp"))
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        results = list(pool.map(lambda p: process(p, args.quality, args.preview_quality), maps))

    previews = [r[0] for r in results]
    before = sum(r[1] for r in results)
    after = sum(r[2] for r in results)
    recompressed = sum(r[2] < r[1] for r in results)
    print(f"{len(maps)} maps")
    print(f"  previews: {previews.count('made')} made, {previews.count('kept')} already there, "
          f"{previews.count('none')} not needed")
    print(f"  originals: {recompressed} recompressed, {before / 1e6:.1f} MB -> {after / 1e6:.1f} MB")
    total = sum(f.stat().st_size for f in DST.glob("*.webp"))
    print(f"  previews folder: {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
