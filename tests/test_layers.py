"""layers: the Plymouth scene's pictures are GRUB's pixels (pixel-identical to Renderer's own drawing), and every customisation shows up in them.
Needs material-grub and a built package (see tests/support.py). usage: python3 tests/test_layers.py"""

import itertools
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402
from support import ARCH, FEDORA, UBUNTU, UNKNOWN  # noqa: E402

from material_plymouth import adapter, layers  # noqa: E402

W, H = 1920, 1080


def dominant(im):
    """The most common fully opaque colour of a layer (what its fill is)."""
    data = im.convert("RGBA").tobytes()
    px = Counter(data[i : i + 3] for i in range(0, len(data), 4) if data[i + 3] == 255)
    return tuple(px.most_common(1)[0][0]) if px else None


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = support.core()
        cls.conf = dict(cls.c.mgrub.CONF_DEFAULTS)
        cls.ov = dict(cls.c.mgoverrides.DEFAULTS)
        cls.hexc = staticmethod(cls.c.mgscenes.hexc)  # a plain function stored on the class would be bound as a method

    def look(self, osrel=FEDORA, conf=None, ov=None, height=H, **kw):
        return adapter.look(
            conf or self.conf, ov or self.ov, adapter.parse_os_release(osrel), height=height, c=self.c, **kw
        )


class PixelIdentity(Base):
    """At rest the layers composite to exactly what GRUB draws. These are the tests that keep the hand-over from jumping."""

    def same(self, a, b, what):
        self.assertIsNone(ImageChops.difference(a, b).getbbox(), f"{what}: differs from GRUB's drawing")

    def test_the_hero_block(self):
        for osrel in (FEDORA, ARCH, UBUNTU, UNKNOWN):
            for ov in (
                self.ov,
                dict(self.ov, entries=[{"match": {"key": "fedora"}, "name": "A rather long name for the Work laptop"}]),
                dict(self.ov, seed={"mode": "single", "color": "#7E57C2"}),
            ):
                with self.subTest(os=osrel.splitlines()[0], ov=bool(ov["entries"])):
                    L = self.look(osrel, ov=ov)
                    ly = layers.all_layers(L, W, H)
                    ref = layers._blank(W, H)
                    L.R.hero(ref, L.entry, L.palette)
                    self.same(ref, layers.composite(ly, W, H, only=("card", "title", "pills")), "hero block")

    def test_the_hero_block_with_a_picture_of_your_own(self):
        with tempfile.TemporaryDirectory() as t:
            Image.new("RGBA", (120, 60), (200, 30, 30, 255)).save(Path(t) / "wide.png")
            ov = dict(self.ov, entries=[{"match": {"key": "fedora"}, "icon": "file:wide.png"}])
            L = self.look(ov=ov, icon_dir=t)
            ref = layers._blank(W, H)
            L.R.hero(ref, L.entry, L.palette)
            self.same(
                ref,
                layers.composite(layers.all_layers(L, W, H), W, H, only=("card", "title", "pills")),
                "hero with a logo",
            )

    def test_the_cookie_and_its_logo(self):
        L = self.look()
        ly = layers.all_layers(L, W, H)
        ref = layers._blank(W, H)
        L.R.preview_logo = self.c.mgscenes.machine_logo(self.c.pkg, L.R.u(120))
        L.R.draw_cookie(ref, L.palette)
        self.same(ref, layers.composite(ly, W, H, only=("cookie", "logo")), "cookie with logo")

    def test_the_background_shapes(self):
        L = self.look()
        ly = layers.all_layers(L, W, H)
        scene = self.c.mgscenes.Renderer.panel_scene(
            L.R, (W, H), "fedora", hero=False, p=L.palette
        )  # GRUB's own background
        mine = Image.new("RGBA", (W, H), self.hexc(L.palette["surface"]) + (255,))
        mine.alpha_composite(layers.composite(ly, W, H, only=("bg_cookie", "bg_sunny", "bg_clover")))
        diff = ImageChops.difference(scene.convert("RGBA"), mine)
        for x, y in (
            (0, 0),
            (W - 64, 0),
            (0, H - 64),
            (W - 64, H - 64),
        ):  # GRUB clips its panel with 64 px rounded corners; Plymouth has the screen edge
            diff.paste((0, 0, 0, 0), (x, y, x + 64, y + 64))
        self.assertIsNone(diff.getbbox(), "the background shapes differ from GRUB's panel")


class ListStyles(Base):
    """list and split: one row instead of the list, the hero of split in layers; both are GRUB's own drawing."""

    def test_the_single_row_is_what_grub_draws_for_a_list_of_one(self):
        for osrel in (FEDORA, ARCH, UNKNOWN):
            for ov in (
                self.ov,
                dict(self.ov, entries=[{"match": {"key": "fedora"}, "name": "Work laptop", "color": "#2E7D32"}]),
            ):
                with self.subTest(os=osrel.splitlines()[0], named=bool(ov["entries"])):
                    L = self.look(osrel, ov=ov)
                    ref = layers._blank(W, H)
                    L.R.draw_list(ref, L.palette, [L.entry], 0, {"shape": "cookie"})
                    r = layers.row(L, W, H)
                    mine = layers._blank(W, H)
                    for n in ("row_cookie", "row_glyph", "row_pill"):
                        layers._paste(mine, *r[n])
                    self.assertIsNone(ImageChops.difference(ref, mine).getbbox())

    def test_the_row_in_split_sits_on_the_right(self):
        L = self.look()
        r = layers.row(L, W, H, L.R.split_x(W))
        self.assertEqual(r["geometry"]["x0"], round(W * 0.47))
        ref = layers._blank(W, H)
        L.R.draw_list(ref, L.palette, [L.entry], 0, {"shape": "cookie"}, L.R.split_x(W))
        mine = layers._blank(W, H)
        for n in ("row_cookie", "row_glyph", "row_pill"):
            layers._paste(mine, *r[n])
        self.assertIsNone(ImageChops.difference(ref, mine).getbbox())

    def test_the_side_hero(self):
        L = self.look()
        sh = layers.side_hero(L, W, H)
        ref = layers._blank(W, H)
        L.R.draw_side_hero(ref, L.key, L.palette, {}, None, L.R.title_for(L.entry))
        mine = layers._blank(W, H)
        for n in ("side_cookie", "side_glyph", "side_title"):
            layers._paste(mine, *sh[n])
        self.assertIsNone(ImageChops.difference(ref, mine).getbbox())

    def test_the_side_hero_with_a_picture_of_your_own_is_a_white_card(self):
        with tempfile.TemporaryDirectory() as t:
            Image.new("RGBA", (120, 60), (200, 30, 30, 255)).save(Path(t) / "wide.png")
            L = self.look(ov=dict(self.ov, entries=[{"match": {"key": "fedora"}, "icon": "file:wide.png"}]), icon_dir=t)
            sh = layers.side_hero(L, W, H)
            self.assertIn("side_card", sh)
            self.assertNotIn("side_cookie", sh)
            ref = layers._blank(W, H)
            L.R.draw_side_hero(ref, L.key, L.palette, {}, None, L.R.title_for(L.entry))
            mine = layers._blank(W, H)
            for n in ("side_card", "side_title"):
                layers._paste(mine, *sh[n])
            self.assertIsNone(ImageChops.difference(ref, mine).getbbox())

    def test_the_list_pills_are_where_grub_puts_them(self):
        L = self.look()
        ref = layers._blank(W, H)
        L.R.pill_row(L.R.info_pills(L.entry), L.palette, W, L.R.u(846), ref, h=L.R.u(46))
        mine = layers._blank(W, H)
        layers._paste(mine, *layers.list_pills(L, W, H, y=L.R.u(846), h=L.R.u(46)))
        self.assertIsNone(ImageChops.difference(ref, mine).getbbox())


class Assets(Base):
    """The bar, the prompt and the messages: in the palette's colours, in proportion to the screen."""

    def test_colours_and_sizes(self):
        L = self.look()
        p, hx = L.palette, self.hexc
        bar, prompt, msgs = layers.bar_assets(L), layers.prompt_assets(L), layers.message_assets(L)
        self.assertEqual(dominant(bar["dot"]), hx(p["primary"]))
        self.assertEqual(dominant(bar["track"]), hx(p["secondaryContainer"]))
        self.assertEqual(dominant(prompt["pw_field"]), hx(p["surfaceContainerHigh"]))
        self.assertEqual(dominant(prompt["pw_dot"]), hx(p["onSurface"]))
        self.assertEqual(bar["track"].size, (560, 10))
        big = layers.bar_assets(self.look(height=2160))
        self.assertEqual(big["track"].size, (1120, 20))
        for im in msgs.values():
            self.assertGreater(im.width, 100)

    def test_strings_are_pictures_so_the_initramfs_needs_no_fonts(self):
        L = self.look()
        a, b = layers.text_line(L, "Enter your disk password", 30), layers.text_line(L, "Shutting down", 40)
        self.assertNotEqual(a.tobytes(), b.tobytes())
        self.assertEqual(a.mode, "RGBA")


class Customisations(Base):
    """Every option and override reaches the layers, in the right colour."""

    def expect_colours(self, L, ly):
        p, hx = L.palette, self.hexc
        self.assertEqual(dominant(ly["title"][0]), hx(p["primary"]))
        self.assertEqual(dominant(ly["bg_cookie"][0]), hx(p["surfaceContainerHigh"]))
        self.assertEqual(dominant(ly["bg_sunny"][0]), hx(p["surfaceContainer"]))
        self.assertEqual(dominant(ly["bg_clover"][0]), hx(p["surfaceContainer"]))
        self.assertEqual(ly["surface"], p["surface"])
        if "cookie" in ly:
            self.assertEqual(dominant(ly["cookie"][0]), hx(p["primaryContainer"]))
        self.assertEqual(dominant(ly["card"][0]), (255, 255, 255) if L.icon == "file" else hx(p["primaryContainer"]))

    def test_matrix_of_options_and_overrides(self):
        ovs = {
            "default": self.ov,
            "one seed": dict(self.ov, seed={"mode": "single", "color": "#7E57C2"}),
            "distro colour": dict(
                self.ov,
                entries=[
                    {"match": {"key": "fedora"}, "color": "#2E7D32"},
                    {"match": {"key": "arch"}, "color": "#E53935"},
                ],
            ),
            "name and icon": dict(self.ov, entries=[{"match": {"title": "ubuntu"}, "name": "Work", "icon": "tux"}]),
            "bad file falls back": None,  # a rejected overrides file is the defaults (see below)
        }
        confs = {
            "default": self.conf,
            "no cookie": dict(self.conf, COOKIE="off"),
            "no logo": dict(self.conf, LOGO="off"),
        }
        for (osname, osrel), (on, ov), (cn, conf) in itertools.product(
            (("fedora", FEDORA), ("arch", ARCH), ("ubuntu", UBUNTU), ("unknown", UNKNOWN)), ovs.items(), confs.items()
        ):
            if ov is None:
                continue
            with self.subTest(os=osname, overrides=on, conf=cn):
                L = self.look(osrel, conf=conf, ov=ov)
                ly = layers.all_layers(L, W, H)
                self.expect_colours(L, ly)
                self.assertEqual("cookie" in ly, conf["COOKIE"] == "on", "COOKIE")
                self.assertEqual(
                    "logo" in ly,
                    conf["COOKIE"] == "on" and conf["LOGO"] == "on",
                    "LOGO (and no cookie also means no logo)",
                )
                if on == "name and icon" and osname == "ubuntu":
                    self.assertEqual(L.title, "Work")

    def test_a_name_changes_the_title_layer_only(self):
        a = layers.all_layers(self.look(), W, H)
        b = layers.all_layers(
            self.look(ov=dict(self.ov, entries=[{"match": {"key": "fedora"}, "name": "Work laptop"}])), W, H
        )
        self.assertNotEqual(a["title"][0].tobytes(), b["title"][0].tobytes())
        self.assertEqual(a["card"][0].tobytes(), b["card"][0].tobytes())

    def test_a_bad_overrides_file_is_the_defaults(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "overrides.json"
            f.write_text('{"seed": {"mode": "single", "color": "not a colour"}}')
            ov, problems = self.c.mgoverrides.load(f)
            self.assertTrue(problems)
            self.assertEqual(self.look(ov=ov).palette, self.look().palette)

    def test_no_kernel_pill_and_the_pills_follow_os_release(self):
        L = self.look(UBUNTU)
        self.assertEqual([p[0] for p in L.R.info_pills(L.entry)], ["Ubuntu 24.04"])


class Sizes(Base):
    def test_layers_scale_with_the_screen(self):
        a = layers.all_layers(self.look(height=1080), 1920, 1080)
        b = layers.all_layers(self.look(height=2160), 3840, 2160)
        for name in ("card", "title", "pills", "cookie", "logo", "bg_cookie"):
            self.assertAlmostEqual(b[name][0].width / a[name][0].width, 2, delta=0.1, msg=name)
            self.assertAlmostEqual(b[name][2] / max(a[name][2], 1), 2, delta=0.15, msg=name + " (position)")

    def test_the_cookie_sits_in_the_top_right_corner_on_a_wide_screen(self):
        L = self.look()
        for w in (1920, 2560, 3440):
            ly = layers.all_layers(L, w, 1080)
            im, x, y = ly["cookie"]
            self.assertEqual(x + im.width // 2, w - 150)
            self.assertEqual(y + im.height // 2, 140)
            self.assertEqual(ly["card"][1] + ly["card"][0].width // 2, w // 2, "the hero stays centred")


if __name__ == "__main__":
    unittest.main()
