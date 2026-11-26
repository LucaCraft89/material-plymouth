"""The command, end to end: this part is installed with packaging/install-tree.sh, found by material-grub's own plugin dispatcher, and driven as
`material-grub plymouth ...` against a staged root, with small fake dracut / lsinitrd / plymouth-set-default-theme programs run through the real subprocess
path. Needs a material-grub checkout WITH the plugin API (REQUIRE_CONTRACT=1 in CI) and a built package. usage: python3 tests/test_plugin.py"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fakes  # noqa: E402
import support  # noqa: E402
from fakes import snapshot  # noqa: E402
from support import FEDORA  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MG = Path(os.environ["MATERIAL_GRUB"])
THEME = "usr/share/plymouth/themes/material"

DRACUT = """#!/bin/sh
[ -n "$FAKE_DRACUT_FAIL" ] && { echo "dracut: boom" >&2; exit 1; }
for i in "$FAKE_ROOT"/boot/initramfs-*.img; do
  { echo usr/lib64/plymouth/script.so; echo usr/lib64/plymouth/label-freetype.so; [ -d "$FAKE_ROOT/%(theme)s" ] && for f in "$FAKE_ROOT/%(theme)s"/*; do echo "usr/share/plymouth/themes/material/$(basename "$f")"; done; head -c 2000 /dev/zero | tr '\\0' x; } > "$i"
done
"""
LISTER = '#!/bin/sh\ncat "$1"\n'
SETDEF = """#!/bin/sh
f="$FAKE_ROOT/etc/plymouth/default-theme"
mkdir -p "$(dirname "$f")"
if [ $# -eq 0 ]; then cat "$f" 2>/dev/null || echo bgrt; elif [ "$1" = "--reset" ]; then echo bgrt > "$f"; else echo "$1" > "$f"; fi
"""


class Command(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (MG / "install/bin/mgplugins.py").is_file():
            msg = f"material-grub at {MG} has no plugin API"
            if os.environ.get("REQUIRE_CONTRACT") == "1":
                raise AssertionError(msg)
            raise unittest.SkipTest(msg)
        support.core()
        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)
        prefix = (
            t / "installed/usr"
        )  # the manifest names the final place of the files: install with that as the prefix, no DESTDIR
        subprocess.run([str(ROOT / "packaging/install-tree.sh"), str(ROOT), "", str(prefix)], check=True)
        cls.plugins = prefix / "share/material-boot/plugins.d"
        cls.bin = t / "bin"
        cls.bin.mkdir()
        for name, body in (
            ("dracut", DRACUT % {"theme": THEME}),
            ("lsinitrd", LISTER),
            ("plymouth-set-default-theme", SETDEF),
        ):
            (cls.bin / name).write_text(body)
            (cls.bin / name).chmod(0o755)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir=self.tmp.name))
        fakes.base_root(self.root, ("6.1.0",))
        (self.root / "etc/os-release").write_text(FEDORA)
        (self.root / "etc/default/grub").write_text('GRUB_CMDLINE_LINUX_DEFAULT="quiet"\n')
        self.env = dict(
            os.environ,
            MATERIAL_PLUGIN_PATH=str(self.plugins),
            MATERIAL_GRUB=str(MG),
            MATERIAL_OVERRIDES="/nonexistent/overrides.json",
            MG_BGRT_IMAGE="/nonexistent",
            PATH=f"{self.bin}:{os.environ['PATH']}",
            FAKE_ROOT=str(self.root),
        )
        self.env.pop("FAKE_DRACUT_FAIL", None)

    def mg(self, *args, **env):
        r = subprocess.run(
            [sys.executable, str(MG / "install/bin/cmd_cli.py"), *args],
            capture_output=True,
            text=True,
            env={**self.env, **env},
            stdin=subprocess.DEVNULL,
            timeout=300,
        )
        return r.returncode, r.stdout + r.stderr

    def test_material_grub_finds_the_part(self):
        rc, out = self.mg("help")
        self.assertIn("material-grub plymouth", out)
        rc, out = self.mg("version")
        self.assertRegex(out, r"plymouth \d+\.\d+\.\d+")

    def test_the_manifest_is_valid_for_the_installed_material_grub(self):
        rc, out = self.mg("doctor", "--json")
        rows = [r for r in json.loads(out) if r["check"] == "plugin plymouth"]
        self.assertEqual([r["status"] for r in rows], ["ok"], rows)

    def test_preview_writes_a_still_of_each_screen(self):
        from PIL import Image

        for screen in ("boot", "password", "shutdown"):
            out = self.root / f"{screen}.png"
            rc, text = self.mg("plymouth", "preview", screen, str(out), "--size", "640x360", "--root", str(self.root))
            self.assertEqual(rc, 0, text)
            self.assertEqual(Image.open(out).size, (640, 360), screen)

    def test_status(self):
        rc, out = self.mg("plymouth", "status", "--json", "--root", str(self.root))
        self.assertEqual(rc, 0, out)
        st = json.loads(out)
        self.assertFalse(st["installed"])
        self.assertTrue(st["script_plugin"].endswith("script.so"))
        self.assertEqual(st["initramfs_tool"], "dracut")

    def test_build_only_writes_the_theme_to_a_directory(self):
        out_dir = self.root / "preview"
        rc, out = self.mg(
            "plymouth", "build", str(out_dir), "--style", "list", "--size", "1366x768", "--root", str(self.root)
        )
        self.assertEqual(rc, 0, out)
        self.assertTrue((out_dir / "material.script").is_file())
        self.assertIn("1366x768", out)
        self.assertFalse((self.root / THEME).exists(), "nothing was installed")

    def test_dry_run_changes_nothing(self):
        before = snapshot(self.root)
        rc, out = self.mg("plymouth", "apply", "--dry-run", "--root", str(self.root))
        self.assertEqual(rc, 0, out)
        self.assertIn("Would:", out)
        self.assertEqual(snapshot(self.root), before)

    def test_apply_then_remove(self):
        rc, out = self.mg("plymouth", "apply", "--yes", "--root", str(self.root))
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / THEME / "material.script").is_file())
        self.assertEqual((self.root / "etc/plymouth/default-theme").read_text().strip(), "material")
        self.assertIn("themes/material", (self.root / "boot/initramfs-6.1.0.img").read_text())
        self.assertIn("quiet splash", (self.root / "etc/default/grub").read_text())
        rc, out = self.mg("plymouth", "status", "--json", "--root", str(self.root))
        self.assertTrue(json.loads(out)["installed"])
        rc, out = self.mg("plymouth", "apply", "--yes", "--if-changed", "--root", str(self.root))
        self.assertIn("nothing to do", out)
        rc, out = self.mg("plymouth", "remove", "--yes", "--root", str(self.root))
        self.assertEqual(rc, 0, out)
        self.assertFalse((self.root / THEME).exists())
        self.assertEqual((self.root / "etc/plymouth/default-theme").read_text().strip(), "bgrt")
        self.assertEqual((self.root / "etc/default/grub").read_text(), 'GRUB_CMDLINE_LINUX_DEFAULT="quiet"\n')

    def test_a_failing_rebuild_rolls_back_through_the_real_command(self):
        before = snapshot(self.root)
        rc, out = self.mg("plymouth", "apply", "--yes", "--root", str(self.root), FAKE_DRACUT_FAIL="1")
        self.assertEqual(rc, 1, out)
        self.assertIn("dracut failed", out)
        self.assertIn("put back", out)
        # the fake default-theme tool reports "bgrt" for a missing file and writes it on a reset: the same state, so it is compared by value
        after = snapshot(self.root)
        after.pop("etc/plymouth/default-theme", None)
        self.assertEqual(after, before)
        self.assertEqual((self.root / "etc/plymouth/default-theme").read_text().strip(), "bgrt")

    def test_declining_is_the_default_without_a_terminal(self):
        rc, out = self.mg("plymouth", "apply", "--root", str(self.root))
        self.assertEqual(rc, 0, out)
        self.assertNotIn(
            "splash",
            (self.root / "etc/default/grub").read_text(),
            "no --yes and no terminal: the command line is left alone",
        )
        self.assertTrue((self.root / THEME).is_dir())

    def test_a_bad_option_is_a_usage_error_not_a_crash(self):
        rc, out = self.mg("plymouth", "apply", "--no-such-thing")
        self.assertNotEqual(rc, 0)
        self.assertNotIn("Traceback", out)


if __name__ == "__main__":
    unittest.main()
