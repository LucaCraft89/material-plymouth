"""Checks the screenshots of a played theme (ci/xvfb_play.sh): the right size, not blank, and (with --moving) that something animates.
usage: python3 ci/check_frames.py [--size WxH] [--moving] FRAME.png ...      exit 0 when every check passes, 1 otherwise (one sentence per problem)."""

import argparse
import sys

from PIL import Image, ImageChops, ImageStat


def blank(im, threshold=2.0):
    """True when the picture is (almost) one flat colour: a theme that did not draw anything is a black screen."""
    return max(ImageStat.Stat(im.convert("RGB")).stddev) < threshold


def changed(a, b, min_pixels=50):
    """True when at least `min_pixels` pixels differ visibly between two frames. A count, not a share of the screen: a spinner is a few hundred pixels of a
    two-million-pixel frame and must still count as moving."""
    diff = ImageChops.difference(a.convert("L"), b.convert("L")).point(lambda v: 255 if v > 8 else 0)
    return diff.histogram()[255] >= min_pixels


def check(paths, size=None, moving=False):
    problems = []
    frames = []
    for p in paths:
        try:
            frames.append((p, Image.open(p).convert("RGB")))
        except OSError as e:
            problems.append(f"{p}: cannot be read ({e})")
    if not frames:
        return problems + ["no frames to check"]
    for p, im in frames:
        if size and im.size != size:
            problems.append(f"{p}: is {im.size[0]}x{im.size[1]}, expected {size[0]}x{size[1]}")
        if blank(im):
            problems.append(f"{p}: is blank (one flat colour): the theme drew nothing")
    if moving and len(frames) > 1 and not any(changed(frames[0][1], im) for _, im in frames[1:]):
        problems.append("nothing moved between the first frame and the later ones, but the theme should animate")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("frames", nargs="+")
    ap.add_argument("--size", help="WxH the frames must have")
    ap.add_argument("--moving", action="store_true", help="the frames must not all be the same")
    a = ap.parse_args(argv)
    size = tuple(map(int, a.size.split("x"))) if a.size else None
    problems = check(a.frames, size, a.moving)
    for p in problems:
        print("FAIL " + p)
    if not problems:
        print(f"ok: {len(a.frames)} frames" + (", animated" if a.moving else ""))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
