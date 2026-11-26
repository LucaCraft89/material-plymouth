"""theme: the files and the script a look turns into, checked without Plymouth: every picture the script names exists, only known script API is used, the
cadence follows PLYMOUTH_MOTION and the screen size, the options decide what is in the theme, the size budget. Needs material-grub and a built package
(see tests/support.py). usage: python3 tests/test_theme.py"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402
from support import ARCH, FEDORA  # noqa: E402

from material_plymouth import adapter, theme  # noqa: E402

KNOWN_API = {
    "Plymouth": {
        "GetMode",
        "SetRefreshFunction",
        "SetBootProgressFunction",
        "SetDisplayPasswordFunction",
        "SetDisplayQuestionFunction",
        "SetDisplayNormalFunction",
    },
    "Window": {"GetWidth", "GetHeight", "SetBackgroundTopColor", "SetBackgroundBottomColor"},
    "Math": {"Int", "Sin", "Cos", "Max", "Min", "Pi"},
}
BUDGET = (
    1_500_000  # bytes of assets at 1080p, the whole theme (the plan's target is under 2 MB: it sits in every initramfs)
)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = support.core()
        cls.conf = dict(cls.c.mgrub.CONF_DEFAULTS)
        cls.ov = dict(cls.c.mgoverrides.DEFAULTS)
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def build(self, style="rail", motion="full", bar="indeterminate", osrel=FEDORA, conf=None, ov=None, W=1920, H=1080):
        conf = dict(conf or self.conf, STYLE=style)
        look = adapter.look(conf, ov or self.ov, adapter.parse_os_release(osrel), height=H, c=self.c)
        out = Path(self.tmp.name) / f"{style}-{motion}-{bar}-{W}x{H}-{abs(hash(str(ov)))}"
        r = theme.build(look, W, H, out, motion=motion, bar=bar)
        r["dir"], r["look"] = out, look
        r["script"] = (out / "material.script").read_text()
        return r


class Files(Base):
    def test_every_picture_the_script_names_exists(self):
        for style in ("rail", "clean", "list", "split"):
            for motion in ("full", "calm", "off"):
                with self.subTest(style=style, motion=motion):
                    r = self.build(style, motion)
                    named = set(re.findall(r'"([^"]+\.png)"', r["script"]))
                    self.assertTrue(named)
                    self.assertEqual(sorted(n for n in named if not (r["dir"] / n).is_file()), [])

    def test_only_known_script_api_is_used(self):
        for style in ("rail", "list", "split"):
            r = self.build(style)
            for obj, meth in re.findall(r"\b(Plymouth|Window|Math)\.(\w+)", r["script"]):
                self.assertIn(meth, KNOWN_API[obj], f"{obj}.{meth} in the {style} script")

    def test_the_plymouth_file(self):
        r = self.build()
        text = (r["dir"] / "material.plymouth").read_text()
        self.assertIn("ModuleName=script", text)
        self.assertIn(f"ImageDir={r['dir']}", text)
        self.assertIn(f"ScriptFile={r['dir']}/material.script", text)
        install = theme.build(
            r["look"], 1920, 1080, Path(self.tmp.name) / "x", install_dir="/usr/share/plymouth/themes/material"
        )
        self.assertIn(
            "ImageDir=/usr/share/plymouth/themes/material\n", (Path(self.tmp.name) / "x/material.plymouth").read_text()
        )
        self.assertTrue(install["files"])

    def test_size_budget(self):
        for style in ("rail", "list", "split"):
            self.assertLess(self.build(style)["size"], BUDGET, style)

    def test_clean_is_the_rail_scene_because_the_peek_panels_are_navigation(self):
        self.assertEqual(self.build("clean")["style"], "rail")


class Cadence(Base):
    def test_values(self):
        self.assertEqual(theme.cadence("off", 1080), {"rate": 0, "bar": 0, "pulse": 0, "morph": 0})
        full, calm = theme.cadence("full", 1080), theme.cadence("calm", 1080)
        self.assertGreater(calm["rate"], full["rate"])
        self.assertGreater(calm["bar"], full["bar"])
        self.assertEqual((calm["pulse"], calm["morph"]), (0, 0), "calm: no pulse, no morph")
        self.assertTrue(full["pulse"] and full["morph"])

    def test_a_bigger_screen_updates_less_often(self):
        a, b = theme.cadence("full", 1080), theme.cadence("full", 2160)
        self.assertEqual((b["rate"], b["bar"]), (a["rate"] * 2, a["bar"] * 2))

    def test_the_script_follows(self):
        full, calm, off = (
            self.build(motion="full")["script"],
            self.build(motion="calm")["script"],
            self.build(motion="off")["script"],
        )
        self.assertIn("Plymouth.SetRefreshFunction", full)
        self.assertIn("Plymouth.SetRefreshFunction", calm)
        # off: nothing moves. The refresh function only repaints the background colour (once a second for twenty seconds: a display attached late would
        # otherwise show the scene on black, seen on Ubuntu under UEFI), it moves and animates nothing
        body = off[off.index("fun refresh() {") : off.index("Plymouth.SetRefreshFunction")]
        for moving in ("place_rot(", "bar(", "SetImage", "SetPosition", "SetOpacity"):
            self.assertNotIn(moving, body, f"off: the per-frame function must not call {moving}")
        self.assertIn("SetBackgroundTopColor", body)
        self.assertIn("PULSE = 8", full)
        self.assertIn("PULSE = 0", calm)

    def test_off_with_a_progress_bar_still_follows_the_boot(self):
        s = self.build(motion="off", bar="progress")["script"]
        self.assertIn("Plymouth.SetRefreshFunction", s)
        self.assertNotIn("place_rot(k", s, "but nothing else moves")

    def test_one_shape_per_frame_at_most(self):
        s = self.build(motion="full")["script"]
        rate = int(re.search(r"RATE = (\d+)", s).group(1))
        n = int(re.search(r"rot_n = (\d+)", s).group(1))
        self.assertGreaterEqual(rate, n, "each turning shape gets its own frame in the cycle")

    def test_a_morph_only_in_the_list_styles_and_only_at_full(self):
        self.assertNotIn("_m0.png", self.build("rail", "full")["script"])
        self.assertIn("row_cookie_m0.png", self.build("list", "full")["script"])
        self.assertIn("side_cookie_m0.png", self.build("split", "full")["script"])
        self.assertNotIn("_m0.png", self.build("list", "calm")["script"])


class Options(Base):
    def test_cookie_and_logo(self):
        full = self.build()
        self.assertTrue((full["dir"] / "cookie.png").is_file() and (full["dir"] / "logo.png").is_file())
        nocookie = self.build(conf=dict(self.conf, COOKIE="off"))
        self.assertFalse((nocookie["dir"] / "cookie.png").is_file() or (nocookie["dir"] / "logo.png").is_file())
        self.assertNotIn('"cookie.png"', nocookie["script"])  # the quoted name: bg_cookie.png is a different file
        nologo = self.build(conf=dict(self.conf, LOGO="off"))
        self.assertTrue((nologo["dir"] / "cookie.png").is_file())
        self.assertFalse((nologo["dir"] / "logo.png").is_file())

    def test_colours_and_names_reach_the_files_and_the_script(self):
        a = self.build()
        b = self.build(ov=dict(self.ov, entries=[{"match": {"key": "fedora"}, "color": "#2E7D32", "name": "Work"}]))
        self.assertNotEqual(
            a["script"].split("\n")[1], b["script"].split("\n")[1], "the background colour follows the palette"
        )
        self.assertNotEqual((a["dir"] / "title.png").read_bytes(), (b["dir"] / "title.png").read_bytes())

    def test_the_bar_mode_is_in_the_script(self):
        self.assertIn("PROGRESS = 1", self.build(bar="progress")["script"])
        self.assertIn("PROGRESS = 0", self.build(bar="indeterminate")["script"])

    def test_the_pills_come_from_os_release_and_there_is_no_kernel_pill(self):
        for osrel, pills in ((FEDORA, ["Fedora Linux 44", "Workstation Edition"]), (ARCH, ["Arch Linux"])):
            L = self.build(osrel=osrel)["look"]
            self.assertEqual([p[0] for p in L.R.info_pills(L.entry)], pills)

    def test_the_prompt_and_the_messages_are_always_there(self):
        for style in ("rail", "list", "split"):
            r = self.build(style)
            for n in ("pw_field", "pw_dot", "pw_label", "msg_shutdown", "msg_updates", "dot", "track", "stop"):
                self.assertTrue((r["dir"] / f"{n}.png").is_file(), f"{style}: {n}")
            for fn in ("SetDisplayPasswordFunction", "SetDisplayNormalFunction", "SetBootProgressFunction", "GetMode"):
                self.assertIn(fn, r["script"])


class Sizes(Base):
    def test_the_layout_scales_and_stays_centred(self):
        a = self.build(W=1920, H=1080)
        b = self.build(W=3840, H=2160)
        self.assertIn("W = 3840; H = 2160;", b["script"])
        self.assertGreater(b["size"], a["size"])
        ba = tuple(int(x) for x in re.search(r"BX = (\d+); BY = (\d+)", a["script"]).groups())
        bb = tuple(int(x) for x in re.search(r"BX = (\d+); BY = (\d+)", b["script"]).groups())
        self.assertEqual(bb, (ba[0] * 2, ba[1] * 2))
        wide = self.build(W=2560, H=1080)
        bx = int(re.search(r"BX = (\d+)", wide["script"]).group(1))
        self.assertEqual(bx, (2560 - 560) // 2, "the bar stays centred on a wide screen")


if __name__ == "__main__":
    unittest.main()


class Preview(unittest.TestCase):
    """The stills the GUI shows: the real layers at the real positions, one per screen."""

    @classmethod
    def setUpClass(cls):
        cls.c = support.core()

    def look(self, **conf):
        from material_plymouth import adapter

        c = dict(self.c.mgrub.CONF_DEFAULTS, **conf)
        return adapter.look(c, dict(self.c.mgoverrides.DEFAULTS), adapter.parse_os_release(support.FEDORA), height=720)

    def test_each_screen_has_the_size_and_is_not_flat(self):
        from PIL import ImageStat

        shots = {s: theme.preview(self.look(), 1280, 720, s) for s in ("boot", "password", "shutdown")}
        for s, im in shots.items():
            self.assertEqual(im.size, (1280, 720), s)
            self.assertGreater(max(ImageStat.Stat(im).stddev), 5, f"{s} is drawn")
        a, b, c = shots["boot"], shots["password"], shots["shutdown"]
        self.assertNotEqual(a.tobytes(), b.tobytes())
        self.assertNotEqual(a.tobytes(), c.tobytes())
        self.assertNotEqual(b.tobytes(), c.tobytes())

    def test_the_password_screen_shows_the_field_and_no_bar(self):
        im = theme.preview(self.look(), 1280, 720, "password")
        field = self.c.mgscenes.hexc(self.look().palette["surfaceContainerHigh"])
        self.assertIn(tuple(field), set(im.getdata()), "the field's colour is on screen")

    def test_the_style_and_the_bar_change_the_picture(self):
        a = theme.preview(self.look(STYLE="rail"), 1280, 720, "boot")
        b = theme.preview(self.look(STYLE="list"), 1280, 720, "boot")
        self.assertNotEqual(a.tobytes(), b.tobytes())
        p = theme.preview(self.look(), 1280, 720, "boot", bar="progress")
        i = theme.preview(self.look(), 1280, 720, "boot", bar="indeterminate")
        self.assertNotEqual(p.tobytes(), i.tobytes(), "the progress bar is drawn longer")

    def test_an_unknown_screen_is_an_error(self):
        with self.assertRaises(ValueError):
            theme.preview(self.look(), 1280, 720, "nope")
