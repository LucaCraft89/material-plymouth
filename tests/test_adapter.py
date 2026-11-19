"""adapter: finding material-grub, os-release, who is booting, and the resolved look. Needs material-grub and a built package (see tests/support.py).
usage: python3 tests/test_adapter.py"""

import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402
from support import ARCH, FEDORA, UBUNTU, UNKNOWN  # noqa: E402

from material_plymouth import adapter  # noqa: E402


class OsRelease(unittest.TestCase):
    def test_parse(self):
        d = adapter.parse_os_release(
            "# c\nNAME=\"Fedora Linux\"\nID=fedora\nVERSION_ID=44\nANSI_COLOR='0;38;2;60;110;180'\nBAD LINE\nHOME_URL=https://x.org\n"
        )
        self.assertEqual(
            (d["NAME"], d["ID"], d["VERSION_ID"], d["ANSI_COLOR"], d["HOME_URL"]),
            ("Fedora Linux", "fedora", "44", "0;38;2;60;110;180", "https://x.org"),
        )
        self.assertNotIn("BAD LINE", d)

    def test_the_class_grub_mkconfig_gives(self):
        for name, cls in (
            ("Fedora Linux", "fedora"),
            ("Arch Linux", "arch"),
            ("Pop!_OS", "pop__os"),
            ("openSUSE Tumbleweed", "opensuse"),
            ("", ""),
        ):
            self.assertEqual(adapter.grub_class({"NAME": name}), cls)

    def test_search_path_names_a_missing_core(self):
        with unittest.mock.patch.dict(os.environ, {"MATERIAL_GRUB": "/nonexistent"}), unittest.mock.patch.object(
            adapter, "_core", None
        ):
            with unittest.mock.patch.object(
                adapter, "candidates", return_value=[(Path("/nonexistent/bin"), Path("/nonexistent/pkg"))]
            ):
                with self.assertRaises(adapter.CoreNotFound) as cm:
                    adapter.core(refresh=True)
        self.assertIn("/nonexistent/bin", str(cm.exception))


class Identity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = support.core()

    def key(self, text):
        return adapter.identify(adapter.parse_os_release(text), self.c)

    def test_known_distros(self):
        self.assertEqual(self.key(FEDORA)[0], "fedora")
        self.assertEqual(self.key(ARCH)[0], "arch")
        self.assertEqual(self.key(UBUNTU)[0], "ubuntu")

    def test_an_unknown_distro_is_the_penguin_like_in_grub_even_with_an_id_like(self):
        self.assertEqual(self.key(UNKNOWN)[0], "tux")

    def test_the_class_finds_a_distro_the_title_does_not(self):
        key, _ = self.key('NAME="Asahi"\nID=fedora-asahi-remix\nPRETTY_NAME="Some Remix 1"\n')
        self.assertEqual(key, "fedora")

    def test_the_entry_has_no_kernel_pill_and_the_os_fields_come_from_os_release(self):
        _, e = self.key(FEDORA)
        self.assertEqual(
            (e["os"], e["osver"], e["edition"], e["kver"], e["where"]),
            ("Fedora Linux", "44", "Workstation Edition", None, None),
        )
        pills = [p[0] for p in self.c.mgscenes.Renderer.info_pills(e)]
        self.assertEqual(pills, ["Fedora Linux 44", "Workstation Edition"])
        _, e = self.key(ARCH)
        self.assertEqual([p[0] for p in self.c.mgscenes.Renderer.info_pills(e)], ["Arch Linux"])


class Look(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = support.core()
        cls.conf = dict(cls.c.mgrub.CONF_DEFAULTS)
        cls.ov = dict(cls.c.mgoverrides.DEFAULTS)

    def look(self, osrel=FEDORA, conf=None, ov=None, **kw):
        return adapter.look(conf or self.conf, ov or self.ov, adapter.parse_os_release(osrel), c=self.c, **kw)

    def test_defaults_are_the_catalog_palette_and_title(self):
        L = self.look()
        pal = json.loads((self.c.pkg / "palettes.json").read_text())
        self.assertEqual(
            (L.key, L.title, L.icon, L.cookie, L.logo, L.style), ("fedora", "Fedora", None, True, True, "rail")
        )
        self.assertEqual(L.palette["primary"], pal["fedora"]["primary"])

    def test_options_follow_the_conf(self):
        self.assertEqual(
            (self.look(conf=dict(self.conf, COOKIE="off")).cookie, self.look(conf=dict(self.conf, COOKIE="off")).logo),
            (False, False),
        )
        L = self.look(conf=dict(self.conf, LOGO="off"))
        self.assertEqual((L.cookie, L.logo), (True, False))
        self.assertEqual(self.look(conf=dict(self.conf, STYLE="split")).style, "split")
        self.assertEqual(
            self.look(conf=dict(self.conf, STYLE="full")).style, "rail", "full is Ventoy's: never a Plymouth style"
        )

    def test_overrides_are_applied_by_the_same_code_as_grub(self):
        ov = dict(
            self.ov,
            entries=[{"match": {"key": "fedora"}, "name": "Work laptop", "color": "#2E7D32", "icon": "tux"}],
        )
        L = self.look(ov=ov)
        self.assertEqual(L.title, "Work laptop")
        self.assertEqual(L.icon, "tux")
        self.assertNotEqual(L.palette["primary"], self.look().palette["primary"])
        self.assertEqual(L.palette["seed"], "#2E7D32")
        self.assertEqual(L.key, "fedora~1")

    def test_one_seed_colour_for_every_distro(self):
        ov = dict(self.ov, seed={"mode": "single", "color": "#7E57C2"})
        a, b = self.look(FEDORA, ov=ov), self.look(ARCH, ov=ov)
        self.assertEqual(a.palette, b.palette)
        self.assertEqual(a.palette["seed"], "#7E57C2")

    def test_a_title_rule_applies_when_it_matches_the_title(self):
        ov = dict(self.ov, entries=[{"match": {"title": "fedora"}, "color": "#C62828"}])
        self.assertEqual(self.look(ov=ov).palette["seed"], "#C62828")
        self.assertNotEqual(self.look(ARCH, ov=ov).palette.get("seed"), "#C62828")

    def test_a_picture_of_your_own(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as t:
            Image.new("RGBA", (64, 64), (200, 30, 30, 255)).save(Path(t) / "mine.png")
            ov = dict(self.ov, entries=[{"match": {"key": "fedora"}, "icon": "file:mine.png"}])
            L = self.look(ov=ov, icon_dir=t)
            self.assertEqual(L.icon, "file")
            self.assertIn(L.key, L.R.logos)

    def test_a_picture_that_cannot_be_read_keeps_the_default(self):
        with tempfile.TemporaryDirectory() as t:
            ov = dict(self.ov, entries=[{"match": {"key": "fedora"}, "icon": "file:gone.png"}])
            self.assertIsNone(self.look(ov=ov, icon_dir=t).icon)

    def test_summary_has_no_objects(self):
        json.dumps(self.look().summary())


if __name__ == "__main__":
    unittest.main()
