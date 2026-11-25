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

    def test_all_three_need_the_core_with_the_plugin_api_and_not_material_grub(self):
        for f in ("rpm/material-plymouth.spec", "arch/PKGBUILD", "debian/debian/control"):
            text = (PK / f).read_text()
            self.assertRegex(text, r"material-boot-core\s*(>=|\(>=)\s*1\.0\.0", f)
            for line in text.splitlines():
                if re.match(r"(Requires:|Depends:|depends=)", line):
                    self.assertNotIn("material-grub", line, f"{f}: this part needs only the core")

    def test_the_python_floor_is_the_cores(self):
        for f, pat in (("arch/PKGBUILD", "python>=3.9"), ("debian/debian/control", "python3 (>= 3.9)")):
            self.assertIn(pat, (PK / f).read_text(), f)

    def test_all_three_need_what_the_theme_needs_at_boot(self):
        # the label plugin: Plymouth 26's script plugin crashes without it (found by the QEMU boot tier)
        self.assertIn("plymouth-plugin-label", (PK / "rpm/material-plymouth.spec").read_text())
        self.assertIn("plymouth-label", (PK / "debian/debian/control").read_text())

    def test_no_scriptlet_makes_a_first_time_change(self):
        # installing must not rebuild the initramfs or edit the kernel command line: the scriptlets only call the hook, which asks the unified installer for a
        # PACKAGE install (the part's own install hook applies nothing without a theme applied before, and never edits the command line then: tests/test_hooks.py)
        hook = (PK / "package-hook.sh").read_text()
        self.assertIn("--from-package", hook, "a package install is told so: the hook then applies nothing by itself")
        self.assertIn("--only plymouth", hook)
        self.assertNotIn(
            "plymouth apply", hook.replace("`material-boot plymouth apply`", ""), "the hook never runs apply itself"
        )
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
                    line, r"package-hook\.sh (configure|remove)\b", f"{f}: a scriptlet may only call the hook"
                )
                self.assertNotIn("apply", line, f"{f} must not apply the theme by itself")

    def test_install_and_upgrade_both_record_the_part(self):
        self.assertIn("package-hook.sh configure", (PK / "rpm/material-plymouth.spec").read_text())
        self.assertIn("package-hook.sh configure", (PK / "debian/debian/postinst").read_text())
        arch = (PK / "arch/material-plymouth.install").read_text()
        self.assertRegex(arch, r"post_install\(\).*configure")
        self.assertRegex(arch, r"post_upgrade\(\).*configure")


if __name__ == "__main__":
    unittest.main()
