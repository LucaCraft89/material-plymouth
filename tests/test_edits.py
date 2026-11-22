"""edits: the text edits that make Plymouth start (kernel command line, mkinitcpio hooks), each with its undo. Pure text; no material-grub needed.
usage: python3 tests/test_edits.py"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from material_plymouth import edits as E  # noqa: E402


class CommandLine(unittest.TestCase):
    def test_tokens_missing(self):
        self.assertEqual(E.tokens_missing("ro root=/dev/sda2"), ["quiet", "splash"])
        self.assertEqual(E.tokens_missing("ro quiet splash"), [])
        self.assertEqual(E.tokens_missing("ro rhgb quiet"), [], "rhgb starts Plymouth as well as splash does")
        self.assertEqual(E.tokens_missing("splash"), ["quiet"])

    def test_grub_default_adds_only_what_is_missing_in_any_quoting(self):
        for q in ('"', "'", ""):
            with self.subTest(q=q):
                text = f"A=1\nGRUB_CMDLINE_LINUX_DEFAULT={q}loglevel=3 quiet{q}\nB=2\n"
                new, added = E.grub_default(text)
                self.assertEqual(added, ["splash"])
                self.assertIn(f"GRUB_CMDLINE_LINUX_DEFAULT={q or chr(34)}loglevel=3 quiet splash{q or chr(34)}", new)
                self.assertTrue(new.startswith("A=1\n") and new.endswith("B=2\n"), "nothing else is touched")

    def test_grub_default_keeps_a_trailing_comment_and_is_idempotent(self):
        new, added = E.grub_default('GRUB_CMDLINE_LINUX_DEFAULT="quiet" # my words\n')
        self.assertEqual(new, 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash" # my words\n')
        again, more = E.grub_default(new)
        self.assertEqual((again, more), (new, []))

    def test_grub_default_without_the_variable_appends_it(self):
        new, added = E.grub_default("GRUB_TIMEOUT=5\n")
        self.assertEqual(added, ["quiet", "splash"])
        self.assertTrue(new.endswith('GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"\n'))

    def test_grub_default_ignores_the_other_variable(self):
        text = 'GRUB_CMDLINE_LINUX="rhgb"\nGRUB_CMDLINE_LINUX_DEFAULT=""\n'
        new, added = E.grub_default(text)
        self.assertEqual(added, ["quiet", "splash"], "only GRUB_CMDLINE_LINUX_DEFAULT counts")
        self.assertIn('GRUB_CMDLINE_LINUX="rhgb"\n', new)

    def test_undo_removes_exactly_what_was_added(self):
        before = 'GRUB_CMDLINE_LINUX_DEFAULT="quiet loglevel=3"\n'
        new, added = E.grub_default(before)
        self.assertEqual(E.grub_default_undo(new, added), before)
        # the user had `splash` already: nothing was added, so nothing is removed
        own = 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"\n'
        _n, none = E.grub_default(own)
        self.assertEqual(E.grub_default_undo(own, none), own)

    def test_undo_is_safe_on_a_file_that_changed_meanwhile(self):
        self.assertEqual(E.grub_default_undo("GRUB_TIMEOUT=5\n", ["splash"]), "GRUB_TIMEOUT=5\n")
        self.assertEqual(
            E.grub_default_undo('GRUB_CMDLINE_LINUX_DEFAULT="quiet"\n', ["splash"]),
            'GRUB_CMDLINE_LINUX_DEFAULT="quiet"\n',
        )

    def test_one_line_file(self):
        new, added = E.one_line("root=UUID=1 ro\n")
        self.assertEqual((new, added), ("root=UUID=1 ro quiet splash\n", ["quiet", "splash"]))
        self.assertEqual(E.one_line_undo(new, added), "root=UUID=1 ro\n")
        self.assertEqual(E.one_line("ro quiet splash\n"), ("ro quiet splash\n", []))

    def test_grubby_info(self):
        info = 'index=0\nargs="ro quiet"\nroot="/dev/sda2"\n\nindex=1\nargs="ro quiet splash"\n'
        self.assertEqual(E.grubby_missing(info), ["splash"], "missing from at least one entry")
        self.assertEqual(E.grubby_missing('args="ro rhgb quiet"\n'), [])
        self.assertEqual(E.grubby_missing(""), [])


class Hooks(unittest.TestCase):
    def test_after_udev_before_encrypt(self):
        new, added = E.mkinitcpio_hooks("HOOKS=(base udev autodetect modconf block encrypt filesystems fsck)\n")
        self.assertTrue(added)
        self.assertIn("HOOKS=(base udev plymouth autodetect modconf block encrypt filesystems fsck)", new)

    def test_systemd_based_list(self):
        new, _ = E.mkinitcpio_hooks('HOOKS="base systemd sd-encrypt filesystems"\n')
        self.assertIn('HOOKS="base systemd plymouth sd-encrypt filesystems"', new)

    def test_only_base(self):
        new, _ = E.mkinitcpio_hooks("HOOKS=(base)\n")
        self.assertIn("HOOKS=(base plymouth)", new)

    def test_idempotent_and_undo(self):
        text = "MODULES=()\nHOOKS=(base udev filesystems)\nCOMPRESSION=zstd\n"
        new, added = E.mkinitcpio_hooks(text)
        self.assertEqual(E.mkinitcpio_hooks(new), (new, False))
        self.assertEqual(E.mkinitcpio_hooks_undo(new), text)

    def test_no_hooks_line(self):
        self.assertEqual(E.mkinitcpio_hooks("MODULES=()\n"), ("MODULES=()\n", False))


if __name__ == "__main__":
    unittest.main()
