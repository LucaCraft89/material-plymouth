"""The theme in real Plymouth (the X11 renderer under Xvfb): what is on the screen, not what is in the files. Every style animates and motion levels cost less,
every customisation reaches the pixels, the disk-password prompt takes and shows input, shutdown mode shows its message.
Needs plymouth, plymouth-x11, Xvfb, ImageMagick, xdotool, bc and root or sudo (it links a theme into /usr/share/plymouth: a CI runner or a throw-away
machine); without them these tests skip, and REQUIRE_PLAY=1 (CI) makes that a failure. Also needs material-grub and a built package.
usage: python3 tests/test_theme_play.py"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402
from support import FEDORA  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ci"))
import check_frames  # noqa: E402

from material_plymouth import adapter, theme  # noqa: E402

W, H = 1920, 1080
REQUIRE = os.environ.get("REQUIRE_PLAY") == "1"
TOOLS = ("plymouthd", "plymouth", "Xvfb", "import", "xdotool", "bc")


TOL = 6  # Plymouth's X11 path quantises colour a little (a palette colour lands a few levels off): compare with a tolerance


def near(a, b, tol=TOL):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def count(im, colour, box, tol=TOL):
    """How many pixels within `tol` of `colour` (per channel) are inside box (x0, y0, x1, y1)."""
    data = im.convert("RGB").crop(box).tobytes()
    r, g, b = colour
    return sum(
        1
        for i in range(0, len(data), 3)
        if abs(data[i] - r) <= tol and abs(data[i + 1] - g) <= tol and abs(data[i + 2] - b) <= tol
    )


class Play(unittest.TestCase):
    n = 0  # counts the plays: one directory each

    @classmethod
    def setUpClass(cls):
        missing = [t for t in TOOLS if shutil.which(t) is None]
        if not missing and os.geteuid() != 0 and shutil.which("sudo") is None:
            missing = ["root or sudo"]
        if (
            not missing
            and not Path("/usr/lib/x86_64-linux-gnu/plymouth/renderers/x11.so").exists()
            and not list(Path("/usr/lib").glob("**/plymouth/renderers/x11.so"))
            and not list(Path("/usr/lib64").glob("**/plymouth/renderers/x11.so"))
        ):
            missing = ["the Plymouth X11 renderer (plymouth-x11)"]
        if missing:
            msg = "cannot play a theme here, missing: " + ", ".join(missing)
            if REQUIRE:
                raise AssertionError(msg)
            raise unittest.SkipTest(msg)
        cls.c = support.core()
        cls.conf = dict(cls.c.mgrub.CONF_DEFAULTS)
        cls.ov = dict(cls.c.mgoverrides.DEFAULTS)
        cls.hexc = staticmethod(cls.c.mgscenes.hexc)
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def play(
        self, style="rail", motion="full", bar="indeterminate", conf=None, ov=None, mode="boot", prompt=False, secs=4
    ):
        """Build the theme for these options and play it. Returns {frames, cpu, answer, look}."""
        Play.n += 1
        base = Path(self.tmp.name) / f"case{Play.n}"
        conf = dict(conf or self.conf, STYLE=style)
        look = adapter.look(conf, ov or self.ov, adapter.parse_os_release(FEDORA), c=self.c)
        theme.build(look, W, H, base / "material", motion=motion, bar=bar)
        env = dict(os.environ, PLY_MODE=mode, PROMPT="1" if prompt else "0")
        r = subprocess.run(
            [str(ROOT / "ci/xvfb_play.sh"), str(base / "material"), str(base / "shot"), str(secs)],
            capture_output=True,
            text=True,
            env=env,
            timeout=240,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        frames = sorted(base.glob("shot-*.png"), key=lambda p: int(p.stem.rsplit("-", 1)[1]))
        keep = os.environ.get("PLAY_SHOTS")  # CI keeps the screenshots as an artifact
        if keep:
            Path(keep).mkdir(parents=True, exist_ok=True)
            for f in frames:
                shutil.copy(
                    f, Path(keep) / f"case{Play.n}-{style}-{motion}-{mode}{'-prompt' if prompt else ''}-{f.name}"
                )
        cpu = float((base / "shot.cpu").read_text()) if (base / "shot.cpu").exists() else None
        answer = (base / "shot.answer").read_text() if (base / "shot.answer").exists() else None
        return {
            "frames": [Image.open(f).convert("RGB") for f in frames],
            "paths": [str(f) for f in frames],
            "cpu": cpu,
            "answer": answer,
            "look": look,
        }

    def moves(self, r):
        return any(check_frames.changed(r["frames"][0], f) for f in r["frames"][1:])


class Styles(Play):
    def test_every_style_draws_something_and_moves(self):
        for style in ("rail", "list", "split"):
            with self.subTest(style=style):
                r = self.play(style)
                self.assertEqual(check_frames.check(r["paths"], size=(W, H), moving=True), [])

    def test_motion_levels_cost_less_and_off_is_still(self):
        full, calm, off = self.play("rail", "full"), self.play("rail", "calm"), self.play("rail", "off")
        self.assertTrue(self.moves(full) and self.moves(calm))
        self.assertFalse(self.moves(off), "motion off: every frame is the same")
        self.assertEqual(check_frames.check(off["paths"], size=(W, H)), [], "and it still draws the scene")
        self.assertLess(off["cpu"], full["cpu"], "off costs less than full")
        self.assertLess(calm["cpu"], full["cpu"], "calm costs less than full")
        print(f"\ncpu (one core, software X11): full {full['cpu']}%, calm {calm['cpu']}%, off {off['cpu']}%")


class Customisations(Play):
    """What the user set for GRUB, found on the real Plymouth screen."""

    COOKIE = (W - 150 - 115, 140 - 115, W - 150 + 115, 140 + 115)
    CARD_PROBE = (W // 2 - 250, 360)  # inside the hero card, clear of the glyph: the card's fill

    def test_cookie_and_logo_follow_the_conf(self):
        full = self.play(secs=2)
        pc = self.hexc(full["look"].palette["primaryContainer"])
        ink = (0x14, 0x14, 0x18)  # the penguin (no firmware logo here)
        self.assertGreater(count(full["frames"][1], pc, self.COOKIE), 5000)
        self.assertGreater(count(full["frames"][1], ink, self.COOKIE), 500)
        nologo = self.play(conf=dict(self.conf, LOGO="off"), secs=2)
        self.assertGreater(count(nologo["frames"][1], pc, self.COOKIE), 5000, "LOGO=off keeps the cookie")
        self.assertEqual(count(nologo["frames"][1], ink, self.COOKIE), 0, "and removes the logo")
        nocookie = self.play(conf=dict(self.conf, COOKIE="off"), secs=2)
        self.assertEqual(count(nocookie["frames"][1], pc, self.COOKIE), 0, "COOKIE=off removes the cookie")
        self.assertEqual(count(nocookie["frames"][1], ink, self.COOKIE), 0, "and the logo with it")

    def test_a_colour_override_and_the_one_seed_colour_reach_the_screen(self):
        default = self.play(secs=2)
        green = self.play(ov=dict(self.ov, entries=[{"match": {"key": "fedora"}, "color": "#2E7D32"}]), secs=2)
        seed = self.play(ov=dict(self.ov, seed={"mode": "single", "color": "#7E57C2"}), secs=2)
        got = lambda r: r["frames"][1].getpixel(self.CARD_PROBE)  # noqa: E731
        for r in (default, green, seed):
            self.assertTrue(
                near(got(r), self.hexc(r["look"].palette["primaryContainer"])),
                f"{got(r)} is not this look's card colour",
            )
        looks = [got(default), got(green), got(seed)]
        for i in range(3):
            for j in range(i + 1, 3):
                self.assertFalse(near(looks[i], looks[j], 30), "three different looks")


class Prompt(Play):
    def field(self):
        """(x0, y0, x1, y1) of the password field in the screen's pixels, from the script's own numbers."""
        import re

        s = (Path(self.tmp.name) / f"case{Play.n}/material/material.script").read_text()
        fx, fy = (int(v) for v in re.search(r"FX = (\d+); FY = (\d+)", s).groups())
        return (fx, fy, fx + 560, fy + 72)

    def test_the_disk_password_prompt(self):
        for style in ("rail", "list"):
            with self.subTest(style=style):
                r = self.play(style, prompt=True)
                box = self.field()
                dot = self.hexc(r["look"].palette["onSurface"])
                px = [count(f, dot, box) for f in r["frames"]]
                unit = max(px[1] / 7, 1)  # the first typed characters: 7 dots
                self.assertEqual(px[0], 0, "the empty field has no dots")
                self.assertEqual(
                    [round(v / unit) for v in px[1:3]], [7, 5], "7 typed characters, then 5 after two backspaces"
                )
                self.assertEqual(px[3], 0, "after Enter the field is gone")
                self.assertEqual(r["answer"], "huntex", "the typed answer reached the program that asked")
                # the field's own fill, measured on a band clear of the pills and the dots (the pills row shares the colour and reaches into the box's top rows)
                x0, y0, x1, y1 = box
                band = (x0 + 300, y0 + 12, x1 - 20, y1 - 12)
                fill = self.hexc(r["look"].palette["surfaceContainerHigh"])
                self.assertGreater(count(r["frames"][0], fill, band), 5000, "the field is drawn")
                self.assertLess(count(r["frames"][3], fill, band), 500, "and gone after Enter")


class Messages(Play):
    def test_shutdown_mode_shows_its_message_instead_of_the_pills(self):
        boot, down = self.play(mode="boot", secs=2), self.play(mode="shutdown", secs=2)
        ink = self.hexc(down["look"].palette["onSurfaceVariant"])
        slot = (W // 2 - 200, 701 - 30, W // 2 + 200, 701 + 30)
        self.assertLess(
            count(boot["frames"][1], ink, slot), 30, "in boot mode the slot holds the pills, not the message"
        )
        self.assertGreater(count(down["frames"][1], ink, slot), 100, "the message is on the screen")
        pill = self.hexc(down["look"].palette["surfaceContainerHigh"])
        self.assertGreater(count(boot["frames"][1], pill, slot), 5000)
        self.assertLess(count(down["frames"][1], pill, slot), 300, "and the pills are gone")


if __name__ == "__main__":
    unittest.main()
