"""apply and remove on a fake machine (tests/fakes.py): the real logic, scripted programs, and a failure injected at every step. The promise under test: a failed
apply or remove leaves the machine EXACTLY as it was (same files, same images, same default theme), and a successful one does what it said and can be undone.
Needs material-grub and a built package for the rendering (see tests/support.py). usage: python3 tests/test_apply.py"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fakes  # noqa: E402
import support  # noqa: E402
from fakes import snapshot  # noqa: E402
from support import FEDORA  # noqa: E402

from material_plymouth import adapter, apply  # noqa: E402

THEME = "usr/share/plymouth/themes/material"


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = support.core()
        cls.conf = dict(cls.c.mgrub.CONF_DEFAULTS)
        cls.ov = dict(cls.c.mgoverrides.DEFAULTS)
        cls.osrel = adapter.parse_os_release(FEDORA)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.n = 0

    def tearDown(self):
        self.tmp.cleanup()

    def machine(self, kind="fedora", **kw):
        self.fs = getattr(fakes, kind)(self.root, **kw)
        return self.fs

    def apply(self, fs=None, conf=None, **kw):
        self.n += 1
        kw.setdefault("yes", True)
        kw.setdefault("stamp", f"t{self.n}")
        kw.setdefault("log", lambda *_a: None)
        return apply.apply(fs or self.fs, conf or self.conf, self.ov, self.osrel, **kw)

    def remove(self, **kw):
        self.n += 1
        kw.setdefault("yes", True)
        kw.setdefault("stamp", f"r{self.n}")
        kw.setdefault("log", lambda *_a: None)
        return apply.remove(self.fs, **kw)

    def images_text(self):
        return {i.name: i.read_text() for i in self.fs.images()}


class Fedora(Base):
    def test_a_fresh_apply_does_everything_it_says(self):
        fs = self.machine("fedora")
        r = self.apply()
        self.assertEqual(r.status, "applied", r.messages)
        self.assertTrue((self.root / THEME / "material.plymouth").is_file())
        self.assertTrue((self.root / THEME / "material.script").is_file())
        self.assertIn(
            f"ImageDir=/{THEME}\n",
            (self.root / THEME / "material.plymouth").read_text(),
            "it points at where it is installed",
        )
        self.assertEqual((self.root / "etc/plymouth/default-theme").read_text(), "material")
        for name, text in self.images_text().items():
            self.assertIn("themes/material/material.script", text, name)
        for e in (self.root / "boot/loader/entries").glob("*.conf"):
            self.assertIn("quiet splash", e.read_text(), "grubby added the words to every entry")
        st = apply.read_state(fs)
        self.assertEqual((st["default_before"], st["tool"], st["size"]), ("bgrt", "dracut", [1366, 768]))
        self.assertEqual(st["edits"], {"grubby": ["quiet", "splash"]})
        self.assertEqual(len(st["images"]), 2)
        self.assertTrue(
            (self.root / "var/backups/material-plymouth/t1/images/initramfs-6.1.0.img").is_file(),
            "the old images were backed up first",
        )

    def test_the_resolution_is_the_displays_not_a_default(self):
        self.assertEqual(apply.detect_resolution(self.machine("fedora")), (1366, 768))

    def test_dry_run_changes_nothing(self):
        fs = self.machine("fedora")
        before = snapshot(self.root)
        r = self.apply(dry_run=True)
        self.assertEqual(r.status, "dry-run")
        self.assertTrue(any("kernel command line" in p for p in r.plan))
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse([c for c in fs.calls if c[0] in ("dracut", "grubby") and "--info=ALL" not in c])

    def test_if_changed_does_nothing_when_nothing_changed_and_applies_when_it_did(self):
        self.machine("fedora")
        self.assertEqual(self.apply(if_changed=True).status, "applied")
        before = snapshot(self.root)
        calls = len(self.fs.calls)
        r = self.apply(if_changed=True)
        self.assertEqual(r.status, "unchanged")
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse([c for c in self.fs.calls[calls:] if c[0] == "dracut"], "no initramfs rebuild")
        r = self.apply(if_changed=True, conf=dict(self.conf, STYLE="list"))
        self.assertEqual(r.status, "applied")
        self.assertEqual(apply.read_state(self.fs)["style"], "list")

    def test_declining_the_command_line_edit_still_installs_the_theme(self):
        self.machine("fedora")
        r = self.apply(yes=False, ask=lambda text: False)
        self.assertEqual(r.status, "applied")
        for e in (self.root / "boot/loader/entries").glob("*.conf"):
            self.assertNotIn("splash", e.read_text())
        self.assertEqual(apply.read_state(self.fs)["edits"], {})

    def test_remove_undoes_exactly_what_apply_did(self):
        self.machine("fedora")
        before = snapshot(self.root)
        self.apply()
        r = self.remove()
        self.assertEqual(r.status, "removed", r.messages)
        self.assertFalse((self.root / THEME).exists())
        self.assertEqual((self.root / "etc/plymouth/default-theme").read_text(), "bgrt")
        for e in (self.root / "boot/loader/entries").glob("*.conf"):
            self.assertEqual(e.read_text().count("splash"), 0)
        self.assertIsNone(apply.read_state(self.fs))
        for _name, text in self.images_text().items():
            self.assertNotIn("themes/material", text, "the images were rebuilt without the theme")
        after = snapshot(self.root)
        # the images were rebuilt (not the old bytes), everything else is as it was
        self.assertEqual(
            {k: v for k, v in after.items() if "initramfs" not in k},
            {k: v for k, v in before.items() if "initramfs" not in k},
        )

    def test_remove_when_nothing_is_installed(self):
        self.machine("fedora")
        self.assertEqual(self.remove().status, "nothing-to-do")

    def test_plymouth_off_in_the_conf_removes_it(self):
        self.machine("fedora")
        self.apply()
        r = self.apply(conf=dict(self.conf, PLYMOUTH="off"))
        self.assertEqual(r.status, "removed")
        self.assertFalse((self.root / THEME).exists())
        self.assertEqual(self.apply(conf=dict(self.conf, PLYMOUTH="off")).status, "nothing-to-do")

    def test_a_second_apply_keeps_the_record_of_what_the_first_added(self):
        self.machine("fedora")
        self.apply()
        self.apply(conf=dict(self.conf, STYLE="split"))
        self.assertEqual(
            apply.read_state(self.fs)["edits"],
            {"grubby": ["quiet", "splash"]},
            "so remove still knows what to take out",
        )

    def test_images_of_removed_kernels_are_left_alone_and_not_verified(self):
        self.machine("fedora")
        stale = self.root / "boot/initramfs-5.0.0.img"
        stale.write_text("an image of a kernel that is gone\n" + "x" * 2000)
        fakes.age(stale)
        # the builder rewrites every image: make the stale one old again afterwards, like dracut leaving it alone
        fs = self.fs
        build = fs.tools["dracut"]

        def build_but_not_the_stale_one(f, cmd):
            old = stale.read_text()
            rc = build(f, cmd)
            stale.write_text(old)
            fakes.age(stale)
            return rc

        fs.tools["dracut"] = build_but_not_the_stale_one
        self.assertEqual(self.apply().status, "applied")
        self.assertNotIn("material", stale.read_text())
        self.assertEqual(sorted(apply.read_state(fs)["images"]), ["initramfs-6.1.0.img", "initramfs-6.2.0.img"])

    def test_a_missing_lister_is_reported_not_fatal(self):
        self.machine("fedora")
        del self.fs.tools["lsinitrd"]
        r = self.apply()
        self.assertEqual(r.status, "applied")
        self.assertTrue(any("could not list" in m for m in r.messages))


class Rollback(Base):
    """A failure at any step puts the machine back exactly as it was."""

    def assert_untouched(self, before, r):
        self.assertEqual(r.status, "rolled-back", r.messages)
        self.assertEqual(snapshot(self.root), before, "the machine is exactly as before")
        self.assertIsNone(apply.read_state(self.fs))

    def test_the_initramfs_rebuild_fails(self):
        self.machine("fedora", fail=True)
        before = snapshot(self.root)
        r = self.apply()
        self.assert_untouched(before, r)
        self.assertIn("dracut failed", r.messages[0])

    def test_the_rebuilt_image_does_not_hold_the_theme(self):
        self.machine("fedora", include_theme=False)
        before = snapshot(self.root)
        r = self.apply()
        self.assert_untouched(before, r)
        self.assertIn("not right", r.messages[0])

    def test_setting_the_default_theme_fails(self):
        self.machine("fedora")
        self.fs.tools["plymouth-set-default-theme"] = lambda fs, cmd: (
            (1, "no such theme") if len(cmd) > 1 and cmd[1] == "material" else fakes.set_default_theme(fs, cmd)
        )
        before = snapshot(self.root)
        self.assert_untouched(before, self.apply())

    def test_grubby_fails(self):
        self.machine("fedora")
        real = self.fs.tools["grubby"]
        self.fs.tools["grubby"] = lambda fs, cmd: (1, "grubby: boom") if "--args" in cmd else real(fs, cmd)
        before = snapshot(self.root)
        self.assert_untouched(before, self.apply())

    def test_a_failure_after_the_edits_restores_the_edited_files_too(self):
        self.machine("ubuntu", fail=True)
        before = snapshot(self.root)
        r = self.apply(regen_grub=lambda: (True, ""))
        self.assert_untouched(before, r)
        self.assertEqual((self.root / "etc/default/grub").read_text().count("splash"), 0)

    def test_regenerating_grub_cfg_fails(self):
        self.machine("ubuntu")
        before = snapshot(self.root)
        r = self.apply(regen_grub=lambda: (False, "grub-mkconfig exploded"))
        self.assert_untouched(before, r)
        self.assertIn("regenerate grub.cfg", r.messages[0])

    def test_the_old_images_come_back_byte_for_byte(self):
        self.machine("fedora", fail=True)
        old = self.images_text()
        self.apply()
        self.assertEqual(self.images_text(), old)

    def test_an_existing_theme_directory_is_put_back(self):
        self.machine("fedora")
        (self.root / THEME).mkdir(parents=True)
        (self.root / THEME / "mine.txt").write_text("a theme of my own")
        self.fs.tools["dracut"] = fakes.builder(fail=True)
        before = snapshot(self.root)
        self.assert_untouched(before, self.apply())
        self.assertEqual((self.root / THEME / "mine.txt").read_text(), "a theme of my own")

    def test_a_failed_remove_puts_everything_back_as_it_was(self):
        self.machine("fedora")
        self.assertEqual(self.apply().status, "applied")
        before = snapshot(self.root)
        self.fs.tools["dracut"] = fakes.builder(fail=True)
        r = self.remove()
        self.assertEqual(r.status, "rolled-back")
        self.assertEqual(snapshot(self.root), before, "still installed, exactly as it was")
        self.assertIsNotNone(apply.read_state(self.fs))

    def test_a_failed_undo_step_is_reported_and_the_others_still_run(self):
        self.machine("fedora", fail=True)
        real = self.fs.tools["plymouth-set-default-theme"]
        calls = []

        def flaky(fs, cmd):
            calls.append(cmd)
            if len(cmd) > 1 and cmd[1] == "bgrt":  # the undo (back to the previous theme) fails
                return 1, "cannot"
            return real(fs, cmd)

        self.fs.tools["plymouth-set-default-theme"] = flaky
        r = self.apply()
        self.assertEqual(r.status, "rolled-back")
        self.assertTrue(any("could not put back the default theme" in m for m in r.messages[2:]), r.messages)
        self.assertFalse((self.root / THEME).exists(), "the other undo steps still ran")


class Refusals(Base):
    def test_no_script_plugin(self):
        self.machine("fedora")
        (self.root / "usr/lib64/plymouth/script.so").unlink()
        before = snapshot(self.root)
        r = self.apply()
        self.assertEqual(r.status, "refused")
        self.assertIn("script plugin", r.messages[0])
        self.assertEqual(snapshot(self.root), before)

    def test_no_initramfs_tool(self):
        self.machine("fedora")
        del self.fs.tools["dracut"]
        self.assertEqual(self.apply().status, "refused")

    def test_not_enough_room_for_the_backups(self):
        self.machine("fedora")
        self.fs._free = 1000
        before = snapshot(self.root)
        r = self.apply()
        self.assertEqual(r.status, "refused")
        self.assertIn("not enough room", r.messages[0])
        self.assertEqual(snapshot(self.root), before)


class Ubuntu(Base):
    def test_apply_with_alternatives_and_the_grub_default_file(self):
        self.machine("ubuntu")
        regen = []
        r = self.apply(regen_grub=lambda: (regen.append(1) or True, ""))
        self.assertEqual(r.status, "applied", r.messages)
        self.assertEqual((self.root / "etc/alternatives/default.plymouth").read_text(), f"/{THEME}/material.plymouth")
        self.assertIn('GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"', (self.root / "etc/default/grub").read_text())
        self.assertEqual(regen, [1], "grub.cfg was regenerated for the new command line")
        self.assertEqual(
            apply.read_state(self.fs)["default_before"], "/usr/share/plymouth/themes/spinner/spinner.plymouth"
        )

    def test_a_failed_second_apply_keeps_the_theme_it_already_had_as_the_default(self):
        # found by the real-initramfs tier on Ubuntu: rolling back used to remove our alternative, so Plymouth fell back to bgrt while the image still held ours
        self.machine("ubuntu")
        self.assertEqual(self.apply(regen_grub=lambda: (True, "")).status, "applied")
        self.fs.tools["update-initramfs"] = fakes.builder(fail=True)
        before = snapshot(self.root)
        r = self.apply(conf=dict(self.conf, STYLE="split"), regen_grub=lambda: (True, ""))
        self.assertEqual(r.status, "rolled-back", r.messages)
        self.assertEqual((self.root / "etc/alternatives/default.plymouth").read_text(), f"/{THEME}/material.plymouth")
        self.assertEqual(snapshot(self.root), before)

    def test_remove_goes_back_to_the_previous_alternative(self):
        self.machine("ubuntu")
        self.apply(regen_grub=lambda: (True, ""))
        self.assertEqual(self.remove().status, "removed")
        self.assertEqual(
            (self.root / "etc/alternatives/default.plymouth").read_text(),
            "/usr/share/plymouth/themes/spinner/spinner.plymouth",
        )
        self.assertEqual((self.root / "etc/default/grub").read_text().count("splash"), 0)
        self.assertIn('"quiet"', (self.root / "etc/default/grub").read_text(), "the user's own `quiet` stays")


class Arch(Base):
    def test_the_mkinitcpio_hook_is_what_puts_the_theme_in_the_image(self):
        self.machine("arch")
        r = self.apply(regen_grub=lambda: (True, ""))
        self.assertEqual(r.status, "applied", r.messages)
        self.assertIn("HOOKS=(base udev plymouth autodetect", (self.root / "etc/mkinitcpio.conf").read_text())
        for name, text in self.images_text().items():
            self.assertIn("themes/material", text, name)
        self.assertEqual(
            sorted(apply.read_state(self.fs)["images"]), ["initramfs-linux-fallback.img", "initramfs-linux.img"]
        )

    def test_remove_takes_the_hook_out_again(self):
        self.machine("arch")
        self.apply(regen_grub=lambda: (True, ""))
        self.assertEqual(self.remove().status, "removed")
        self.assertNotIn("plymouth", (self.root / "etc/mkinitcpio.conf").read_text())

    def test_a_mkinitcpio_conf_without_the_hook_gets_it_and_then_the_images_have_the_theme(self):
        self.machine("arch")
        (self.root / "etc/mkinitcpio.conf").write_text("HOOKS=(base udev filesystems)\n")
        before = snapshot(self.root)
        r = self.apply(regen_grub=lambda: (True, ""), no_cmdline=True)
        self.assertEqual(r.status, "applied", r.messages)
        self.assertNotEqual(snapshot(self.root), before)
        self.assertIn("plymouth", (self.root / "etc/mkinitcpio.conf").read_text())


class Resolution(Base):
    def test_fallbacks(self):
        fs = self.machine("fedora")
        (self.root / "sys/class/drm/card0-eDP-1/status").write_text("disconnected\n")
        (self.root / "etc/default/grub").write_text('GRUB_GFXMODE="1600x900,auto"\n')
        self.assertEqual(apply.detect_resolution(fs), (1600, 900))
        (self.root / "etc/default/grub").unlink()
        self.assertEqual(apply.detect_resolution(fs), (1920, 1080))

    def test_the_first_connected_display_wins(self):
        fs = self.machine("fedora")
        d = self.root / "sys/class/drm/card0-DP-2"
        d.mkdir()
        (d / "status").write_text("connected\n")
        (d / "modes").write_text("2560x1440\n")
        self.assertEqual(apply.detect_resolution(fs), (2560, 1440), "sorted by name: card0-DP-2 before card0-eDP-1")


class Backups(Base):
    def test_only_the_newest_few_are_kept(self):
        self.machine("fedora")
        for i in range(5):
            self.apply(
                conf=dict(self.conf, STYLE=("rail", "list", "split")[i % 3], PLYMOUTH_MOTION=("full", "calm")[i % 2])
            )
        kept = sorted(p.name for p in (self.root / "var/backups/material-plymouth").iterdir())
        self.assertEqual(len(kept), apply.KEEP_BACKUPS)
        self.assertEqual(kept[-1], "t5")


if __name__ == "__main__":
    unittest.main()
