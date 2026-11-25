"""adapter: finding the core, os-release, who is booting, and the resolved look. Needs material-boot-core and its built data (see tests/support.py).
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
        with unittest.mock.patch.dict(os.environ, {"MATERIAL_LIB": "/nonexistent"}), unittest.mock.patch.object(
            adapter, "_core", None
        ):
            with unittest.mock.patch.object(
                adapter, "candidates", return_value=[(Path("/nonexistent/lib"), Path("/nonexistent/data"))]
            ):
                with self.assertRaises(adapter.CoreNotFound) as cm:
                    adapter.core(refresh=True)
        self.assertIn("/nonexistent/lib", str(cm.exception))

    def test_the_search_order_and_the_data_next_to_the_library(self):
        with unittest.mock.patch.dict(os.environ, {"MATERIAL_LIB": "/x/lib"}, clear=False):
            os.environ.pop("MATERIAL_DATA", None)
            self.assertEqual(adapter.candidates(), [(Path("/x/lib"), Path("/x/data"))])
            with (
                tempfile.TemporaryDirectory()
            ) as d:  # a library with no data next to it (a bundle's): the data the installer built is used
                built = Path(d) / "data"
                built.mkdir()
                (built / "palettes.json").write_text("{}")
                real = Path.is_file
                with unittest.mock.patch.object(adapter, "Path", wraps=Path):
                    pass
                with unittest.mock.patch.object(
                    Path,
                    "is_file",
                    lambda self: str(self) == "/usr/share/material-boot/data/palettes.json" or real(self),
                ):
                    self.assertEqual(adapter.candidates(), [(Path("/x/lib"), Path("/usr/share/material-boot/data"))])
            os.environ["MATERIAL_DATA"] = "/y/data"
            self.assertEqual(adapter.candidates(), [(Path("/x/lib"), Path("/y/data"))])
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MATERIAL_LIB", None)
            os.environ.pop("MATERIAL_DATA", None)
            self.assertEqual(
                [str(lib) for lib, _ in adapter.candidates()],
                ["/usr/share/material-boot/lib", "/usr/local/share/material-boot/lib", "/var/lib/material-boot/lib"],
            )

    def test_a_core_of_another_api_or_too_old_is_refused_with_the_reason(self):
        import tempfile

        for version, api, word in (("1.0.0", 1, "plugin API"), ("0.9.0", 2, "older")):
            with tempfile.TemporaryDirectory() as t:
                lib = Path(t) / "lib"
                (lib / "material_boot").mkdir(parents=True)
                (lib / "material_boot/__init__.py").write_text(f'__version__ = "{version}"\nCORE_API = {api}\n')
                for m in ("conf", "custom", "overrides", "scenes", "titles"):
                    (lib / f"material_boot/{m}.py").write_text("")
                (Path(t) / "data").mkdir()
                (Path(t) / "data/palettes.json").write_text("{}")
                saved = {k: v for k, v in sys.modules.items() if k == "material_boot" or k.startswith("material_boot.")}
                for k in saved:
                    del sys.modules[k]
                try:
                    with unittest.mock.patch.object(adapter, "_core", None), unittest.mock.patch.dict(
                        os.environ, {"MATERIAL_LIB": str(lib)}
                    ):
                        with self.assertRaises(adapter.CoreNotFound) as cm:
                            adapter.core(refresh=True)
                    self.assertIn(word, str(cm.exception))
                finally:
                    for k in [k for k in sys.modules if k == "material_boot" or k.startswith("material_boot.")]:
                        del sys.modules[k]
                    sys.modules.update(saved)
                    if str(lib) in sys.path:
                        sys.path.remove(str(lib))


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
