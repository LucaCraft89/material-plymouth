"""The hooks of the unified installer (material_plymouth.hooks) on a fake machine (tests/fakes.py): the real logic of apply and remove, scripted programs.
Needs material-boot-core and its built data (see tests/support.py). usage: python3 tests/test_hooks.py"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fakes  # noqa: E402
import support  # noqa: E402
from fakes import snapshot  # noqa: E402
from support import FEDORA  # noqa: E402

support.core()  # the core's library on sys.path before the plugin API is imported
from material_boot import plugins  # noqa: E402

from material_plymouth import __version__, hooks  # noqa: E402

THEME = "usr/share/plymouth/themes/material"
LEVELS = {"ok", "info", "warn", "fail", "error"}


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = support.core()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fs = fakes.fedora(self.root)
        (self.root / "etc").mkdir(exist_ok=True)
        (self.root / "etc/os-release").write_text(FEDORA)
        patch = mock.patch.object(hooks, "make_system", lambda root: self.fs)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def ctx(self, **kw):
        kw.setdefault("root", str(self.root))
        kw.setdefault("yes", True)
        return plugins.make_ctx(**kw)


class Entry(unittest.TestCase):
    def test_the_entry_file_defines_exactly_the_hooks_the_manifest_lists_and_main(self):
        import importlib.util
        import json

        root = Path(__file__).resolve().parent.parent
        listed = json.loads((root / "packaging/plymouth.json.in").read_text())["hooks"]
        spec = importlib.util.spec_from_file_location("mgplugin_entry", root / "bin/mgplugin.py")
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
        defined = sorted(n[len("hook_") :] for n in dir(entry) if n.startswith("hook_"))
        self.assertEqual(defined, sorted(listed))
        self.assertTrue(callable(entry.main))
        self.assertTrue(set(listed) <= set(plugins.HOOKS))


class Detect(Base):
    def test_nothing_is_found_on_a_fresh_machine(self):
        self.assertFalse(hooks.hook_detect(self.ctx())["found"])

    def test_an_applied_theme_is_found_with_its_version(self):
        hooks.hook_install(self.ctx())
        d = hooks.hook_detect(self.ctx())
        self.assertTrue(d["found"])
        self.assertEqual(d["version"], __version__)
        self.assertTrue(any("theme is applied" in x for x in d["details"]))

    def test_a_part_that_is_installed_and_not_applied_is_found_through_the_record(self):
        d = hooks.hook_detect(self.ctx(previous="1.0.0"))
        self.assertEqual((d["found"], d["version"]), (True, "1.0.0"))
        self.assertTrue(any("not applied" in x for x in d["details"]))


class Install(Base):
    def test_choosing_the_part_applies_the_theme(self):
        r = hooks.hook_install(self.ctx())
        self.assertTrue(r["changed"])
        self.assertTrue((self.root / THEME / "material.script").is_file())
        self.assertEqual((self.root / "etc/plymouth/default-theme").read_text().strip(), "material")

    def test_again_with_the_same_look_rebuilds_nothing(self):
        hooks.hook_install(self.ctx())
        n = len(self.fs.calls)
        r = hooks.hook_install(self.ctx())
        self.assertFalse(r["changed"])
        self.assertEqual(self.fs.calls[n:], [], "no program was run")

    def test_a_dry_run_changes_nothing_and_says_what_it_would_do(self):
        before = snapshot(self.root)
        r = hooks.hook_install(self.ctx(dry_run=True))
        self.assertEqual((r["changed"], snapshot(self.root)), (False, before))
        self.assertTrue(r["notes"])

    def test_the_plan_is_sentences_and_changes_nothing(self):
        before = snapshot(self.root)
        plan = hooks.hook_plan(self.ctx())
        self.assertTrue(plan and all(isinstance(x, str) for x in plan))
        self.assertEqual(snapshot(self.root), before)

    def test_a_package_install_does_not_turn_the_splash_on(self):
        before = snapshot(self.root)
        r = hooks.hook_install(self.ctx(how="package"))
        self.assertEqual((r["changed"], snapshot(self.root)), (False, before))
        self.assertIn("material-boot plymouth apply", r["notes"][0])
        self.assertEqual(self.fs.calls, [], "no program was run")

    def test_a_package_upgrade_reapplies_a_theme_that_was_applied_and_leaves_the_command_line(self):
        hooks.hook_install(self.ctx(options={"no-cmdline": True}))  # applied, the command line never edited
        n = len(self.fs.calls)
        conf = dict(self.c.mgrub.CONF_DEFAULTS, STYLE="list")
        with mock.patch.object(hooks, "_settings", lambda ctx: (conf, dict(self.c.mgoverrides.DEFAULTS), {})):
            r = hooks.hook_install(self.ctx(how="package"))
        self.assertTrue(r["changed"], r)
        self.assertTrue(any(c[0] == "dracut" for c in self.fs.calls[n:]), "the initramfs was rebuilt for the new look")
        self.assertFalse(
            any(c[0] == "grubby" for c in self.fs.calls[n:]), "a package never touches the kernel command line"
        )

    def test_a_failing_rebuild_raises_and_leaves_the_machine_as_it_was(self):
        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fs = fakes.fedora(self.root, fail=True)
        (self.root / "etc").mkdir(exist_ok=True)
        (self.root / "etc/os-release").write_text(FEDORA)
        before = snapshot(self.root)
        with self.assertRaisesRegex(RuntimeError, "failed"):
            hooks.hook_install(self.ctx())
        after = snapshot(self.root)
        after.pop("etc/plymouth/default-theme", None)
        before.pop("etc/plymouth/default-theme", None)
        self.assertEqual(after, before)

    def test_no_cmdline_is_honoured(self):
        hooks.hook_install(self.ctx(options={"no-cmdline": True}))
        self.assertFalse(any(c[0] == "grubby" for c in self.fs.calls))

    def test_without_the_option_the_command_line_is_edited(self):
        hooks.hook_install(self.ctx())
        self.assertTrue(any(c[0] == "grubby" for c in self.fs.calls))


class VerifyUninstallDoctor(Base):
    def test_nothing_applied_nothing_to_verify(self):
        self.assertEqual(hooks.hook_verify(self.ctx()), [])

    def test_a_good_install_verifies(self):
        hooks.hook_install(self.ctx())
        self.assertEqual(hooks.hook_verify(self.ctx()), [])

    def test_a_changed_default_theme_is_reported(self):
        hooks.hook_install(self.ctx())
        (self.root / "etc/plymouth/default-theme").write_text("spinner")
        self.assertTrue(any("spinner" in p for p in hooks.hook_verify(self.ctx())))

    def test_a_missing_theme_directory_is_reported(self):
        hooks.hook_install(self.ctx())
        import shutil

        shutil.rmtree(self.root / THEME)
        self.assertTrue(any("missing" in p for p in hooks.hook_verify(self.ctx())))

    def test_uninstall_takes_the_theme_out_and_restores_the_default(self):
        hooks.hook_install(self.ctx())
        r = hooks.hook_uninstall(self.ctx())
        self.assertTrue(r["changed"])
        self.assertFalse((self.root / THEME).exists())
        self.assertEqual((self.root / "etc/plymouth/default-theme").read_text().strip(), "bgrt")

    def test_uninstall_of_nothing_is_nothing(self):
        before = snapshot(self.root)
        self.assertEqual(hooks.hook_uninstall(self.ctx()), {"changed": False})
        self.assertEqual(snapshot(self.root), before)

    def test_uninstall_dry_run_changes_nothing(self):
        hooks.hook_install(self.ctx())
        before = snapshot(self.root)
        hooks.hook_uninstall(self.ctx(dry_run=True))
        self.assertEqual(snapshot(self.root), before)

    def test_doctor_lines_have_known_levels_and_report_a_missing_tool(self):
        for level, text in hooks.hook_doctor(self.ctx()):
            self.assertIn(level, LEVELS)
            self.assertTrue(text)
        self.assertIn(
            ("info", "the theme is not applied (material-boot plymouth apply)"), hooks.hook_doctor(self.ctx())
        )
        hooks.hook_install(self.ctx())
        self.assertTrue(any("theme applied" in t for _l, t in hooks.hook_doctor(self.ctx())))
        self.fs.tools.pop("dracut")
        self.assertIn("fail", [lv for lv, _t in hooks.hook_doctor(self.ctx())])


if __name__ == "__main__":
    unittest.main()
