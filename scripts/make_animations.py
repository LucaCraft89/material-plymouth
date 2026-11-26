#!/usr/bin/env python3
"""Record the animations of the theme as GIFs: each style is built the way `material-boot plymouth build` builds it and PLAYED in real Plymouth (the X11
renderer under Xvfb, ci/record_gif.sh), so what is recorded is what the splash does: the wavy bar, the turning and morphing shapes, the cookie, the hero card.
usage: python3 scripts/make_animations.py OUTDIR [--styles rail,clean,list,split] [--seconds 6] [--size 1280x720] [--width 600]
Needs the core (MATERIAL_LIB, MATERIAL_DATA), Plymouth with its X11 renderer, Xvfb, ffmpeg (x11grab); root or sudo. A throw-away container or a CI runner."""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MATERIAL_LIB", str(ROOT.parent / "material-boot-core"))
os.environ["MATERIAL_OVERRIDES"] = "/nonexistent/overrides.json"  # the pictures are the defaults, whoever makes them
os.environ["MG_BGRT_IMAGE"] = "/nonexistent/bgrt"  # no firmware logo: the penguin

from material_plymouth import plugin  # noqa: E402

OS_RELEASE = 'NAME="Fedora Linux"\nVERSION_ID=44\nVARIANT="Workstation Edition"\nID=fedora\nPRETTY_NAME="Fedora Linux 44 (Workstation Edition)"\n'


def build(style, size, dest):
    """Build the theme of `style` into dest/material, the way the command does, for a Fedora look."""
    root = Path(tempfile.mkdtemp(prefix="anim-root-"))
    (root / "etc").mkdir()
    (root / "etc/os-release").write_text(OS_RELEASE)
    core = SimpleNamespace(
        say=lambda *a: None, conf_path=lambda: str(root / "etc/material-grub.conf"), elevate=lambda *a: None
    )
    try:
        rc = plugin.main(
            [
                "build",
                str(dest / "material"),
                "--style",
                style,
                "--motion",
                "full",
                "--size",
                size,
                "--root",
                str(root),
            ],
            core,
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)
    if rc:
        sys.exit(f"building the {style} theme failed")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out")
    ap.add_argument("--styles", default="rail,clean,list,split")
    ap.add_argument("--seconds", type=int, default=6)
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--width", type=int, default=600)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for style in a.styles.split(","):
        work = Path(tempfile.mkdtemp(prefix=f"anim-{style}-"))
        try:
            build(style, a.size, work)
            subprocess.run(
                [
                    str(ROOT / "ci/record_gif.sh"),
                    str(work / "material"),
                    str(out / f"{style}.gif"),
                    str(a.seconds),
                    a.size,
                    str(a.width),
                ],
                check=True,
            )
        finally:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
