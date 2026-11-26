"""The recordings of the animations (docs/animations/*.gif, made by scripts/make_animations.py from the theme playing in real Plymouth): there is one per style,
each is a real animation (many frames, the picture changes, nothing is frozen), small enough for a README, and the README shows every one. No Plymouth needed.
usage: python3 tests/test_animations.py   (ANIMATIONS_DIR=DIR: check the recordings of a fresh run instead of the committed ones; CI does both)"""

import os
import unittest
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parent.parent
STYLES = ("rail", "clean", "list", "split")
MIN_FRAMES, MAX_BYTES, WIDTH = 40, 1_500_000, 600
DIR = Path(os.environ.get("ANIMATIONS_DIR") or ROOT / "docs/animations")


def frames(path):
    im = Image.open(path)
    out = []
    for k in range(im.n_frames):
        im.seek(k)
        out.append(im.convert("RGB"))
    return out


def moving(fr):
    """How many of the frames after the first differ from it, by more than the noise of the palette."""
    first = fr[0]
    n = 0
    for f in fr[1:]:
        box = ImageChops.difference(first, f).convert("L").point(lambda v: 255 if v > 24 else 0).getbbox()
        n += box is not None
    return n


class Recordings(unittest.TestCase):
    def test_there_is_one_per_style_and_nothing_else(self):
        self.assertEqual(sorted(p.stem for p in DIR.glob("*.gif")), sorted(STYLES))

    def test_each_is_a_real_animation_of_the_right_size(self):
        for style in STYLES:
            with self.subTest(style=style):
                path = DIR / f"{style}.gif"
                fr = frames(path)
                self.assertGreaterEqual(len(fr), MIN_FRAMES, "too few frames to be an animation")
                self.assertEqual(fr[0].size[0], WIDTH)
                self.assertLessEqual(path.stat().st_size, MAX_BYTES, "too big for a README")
                self.assertGreaterEqual(
                    moving(fr), len(fr) // 2, "the picture hardly changes: is Plymouth really playing?"
                )
                self.assertIsNotNone(ImageChops.difference(fr[0], fr[len(fr) // 2]).getbbox())

    def test_a_still_picture_is_not_accepted(self):
        """The check itself: a clip whose frames are all the same is refused."""
        still = [Image.new("RGB", (WIDTH, 338), (10, 20, 30))] * 60
        self.assertEqual(moving(still), 0)

    def test_the_picture_is_not_blank(self):
        for style in STYLES:
            with self.subTest(style=style):
                fr = frames(DIR / f"{style}.gif")[len(frames(DIR / f"{style}.gif")) // 2]
                self.assertGreater(len(set(fr.getdata())), 8, "a flat picture")


class Readme(unittest.TestCase):
    def test_the_readme_shows_every_style(self):
        text = (ROOT / "README.md").read_text()
        for style in STYLES:
            self.assertIn(f"docs/animations/{style}.gif", text, style)

    def test_the_recordings_are_in_the_repository_not_ignored(self):
        ignore = (ROOT / ".gitignore").read_text() if (ROOT / ".gitignore").exists() else ""
        self.assertNotIn("*.gif", ignore)


if __name__ == "__main__":
    unittest.main()
