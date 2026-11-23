"""The three package definitions agree with the code and with each other. (That they build and install is the CI `package` job's: it needs rpm, dpkg and pacman.)"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PK = ROOT / "packaging"


def code_version():
    return re.search(r'__version__ = "([^"]+)"', (ROOT / "material_plymouth/__init__.py").read_text())[1]


class Versions(unittest.TestCase):
    def test_every_package_is_the_version_of_the_code(self):
        v = code_version()
        spec = (PK / "rpm/material-plymouth.spec").read_text()
        self.assertEqual(re.search(r"^Version:\s*(\S+)", spec, re.M)[1], v, "rpm spec")
        self.assertIn(f"- {v}-1\n", spec, "rpm changelog has the version")
        self.assertEqual(re.search(r"^pkgver=(\S+)", (PK / "arch/PKGBUILD").read_text(), re.M)[1], v, "PKGBUILD")
        self.assertEqual(
            re.match(r"material-plymouth \(([^)]+)\)", (PK / "debian/debian/changelog").read_text())[1], v, "debian"
        )

    def test_all_three_need_material_grub_with_the_plugin_api(self):
        for f in ("rpm/material-plymouth.spec", "arch/PKGBUILD", "debian/debian/control"):
            self.assertRegex((PK / f).read_text(), r"material-grub\s*(>=|\(>=)\s*0\.8\.0", f)

    def test_all_three_need_what_the_theme_needs_at_boot(self):
        # the label plugin: Plymouth 26's script plugin crashes without it (found by the QEMU boot tier)
        self.assertIn("plymouth-plugin-label", (PK / "rpm/material-plymouth.spec").read_text())
        self.assertIn("plymouth-label", (PK / "debian/debian/control").read_text())

    def test_no_scriptlet_makes_a_first_time_change(self):
        # installing must not rebuild the initramfs or edit the kernel command line: only `upgrade` (a theme applied before) and `remove` call the hook
        hook = (PK / "package-hook.sh").read_text()
        self.assertIn("--no-cmdline", hook, "an upgrade never touches the kernel command line")
        self.assertIn("state.json", hook, "the hook acts only on a theme that was applied")
        for f in (
            "rpm/material-plymouth.spec",
            "arch/material-plymouth.install",
            "debian/debian/postinst",
            "debian/debian/prerm",
        ):
            for line in (PK / f).read_text().splitlines():
                if line.lstrip().startswith("#") or "package-hook.sh" not in line:
                    continue
                self.assertRegex(
                    line, r"package-hook\.sh (upgrade|remove)\b", f"{f}: a scriptlet may only call the hook"
                )
                self.assertNotIn("apply", line, f"{f} must not apply the theme by itself")


if __name__ == "__main__":
    unittest.main()
