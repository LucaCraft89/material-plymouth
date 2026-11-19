"""ci/check_frames.py: the checks that tell a theme that drew something and moves from a black screen. Pillow only. usage: python3 tests/test_check_frames.py"""

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ci"))
import check_frames  # noqa: E402


def frame(path, size=(400, 300), bg=(10, 10, 20), dot=None):
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    d.rectangle([20, 20, 120, 80], fill=(200, 200, 220))  # something drawn, so the frame is not blank
    if dot:
        d.rectangle([dot[0], dot[1], dot[0] + 12, dot[1] + 12], fill=(255, 255, 255))  # 169 px: a small spinner
    im.save(path)
    return str(path)


class Frames(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_good_static_frame(self):
        self.assertEqual(check_frames.check([frame(self.d / "a.png")], size=(400, 300)), [])

    def test_a_blank_frame_is_a_theme_that_drew_nothing(self):
        Image.new("RGB", (400, 300), (0, 0, 0)).save(self.d / "b.png")
        problems = check_frames.check([str(self.d / "b.png")])
        self.assertEqual(len(problems), 1)
        self.assertIn("blank", problems[0])

    def test_a_wrong_size(self):
        problems = check_frames.check([frame(self.d / "a.png")], size=(1920, 1080))
        self.assertIn("expected 1920x1080", problems[0])

    def test_a_small_movement_counts_as_animation(self):
        a, b = frame(self.d / "a.png", dot=(200, 200)), frame(self.d / "b.png", dot=(230, 200))
        self.assertEqual(check_frames.check([a, b], moving=True), [])

    def test_identical_frames_are_not_animation(self):
        a, b = frame(self.d / "a.png", dot=(200, 200)), frame(self.d / "b.png", dot=(200, 200))
        self.assertEqual(check_frames.check([a, b]), [], "fine when nothing has to move")
        problems = check_frames.check([a, b], moving=True)
        self.assertIn("nothing moved", problems[0])

    def test_a_few_stray_pixels_are_not_animation(self):
        a = frame(self.d / "a.png")
        im = Image.open(a)
        im.putpixel((300, 200), (255, 255, 255))
        im.save(self.d / "b.png")
        self.assertIn("nothing moved", check_frames.check([a, str(self.d / "b.png")], moving=True)[0])

    def test_unreadable_and_missing_frames(self):
        (self.d / "x.png").write_text("not an image")
        self.assertIn("cannot be read", check_frames.check([str(self.d / "x.png")])[0])
        self.assertEqual(check_frames.check([]), ["no frames to check"])

    def test_the_command_line(self):
        a, b = frame(self.d / "a.png", dot=(200, 200)), frame(self.d / "b.png", dot=(230, 200))
        self.assertEqual(check_frames.main(["--size", "400x300", "--moving", a, b]), 0)
        self.assertEqual(check_frames.main(["--size", "800x600", a]), 1)


if __name__ == "__main__":
    unittest.main()
