"""Turn a rendered frame sequence into the README's animated WebP.

Frames are streamed to the encoder one at a time (a long sequence would not
fit in memory), and runs of identical frames become one frame held longer:
most of the demo is a still screen, so the file stays small.

    python scripts/webp.py out/short out/demo.webp --fps 30 --step 2 --quality 75

Needs Pillow built with WebP (`python -c "import PIL.features as f; print(f.check('webp'))"`).
"""

import argparse
import hashlib
import pathlib

from PIL import Image, _webp


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("frames", type=pathlib.Path)
    parser.add_argument("output", type=pathlib.Path)
    parser.add_argument("--fps", type=float, default=30)
    parser.add_argument("--quality", type=int, default=75)
    # Keep one frame in `step`: 2 turns a 30 fps render into a 15 fps animation.
    parser.add_argument("--step", type=int, default=1)
    args = parser.parse_args()

    files = sorted(p for p in args.frames.iterdir() if p.suffix in {".png", ".jpeg", ".jpg"})[:: args.step]
    if not files:
        raise SystemExit(f"no frames in {args.frames}")
    step = 1000 * args.step / args.fps
    with Image.open(files[0]) as first:
        size = first.size
    # Loop forever, opaque white background, keyframes as in gif2webp.
    enc = _webp.WebPAnimEncoder(size, 0xFFFFFFFF, 0, False, 3, 5, False, False)

    timestamp = 0.0
    previous = None
    kept = 0
    for path in files:
        data = path.read_bytes()
        digest = hashlib.sha1(data).digest()
        if digest != previous:
            with Image.open(path) as im:
                frame = im.convert("RGBA")
                enc.add(frame.getim(), round(timestamp), False, args.quality, 100, 4)
            previous = digest
            kept += 1
        timestamp += step
    enc.add(None, round(timestamp), False, args.quality, 100, 0)
    args.output.write_bytes(enc.assemble("", "", ""))
    size_mb = args.output.stat().st_size / 1e6
    print(f"{args.output}: {kept} distinct frames of {len(files)}, {timestamp / 1000:.1f} s, {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
