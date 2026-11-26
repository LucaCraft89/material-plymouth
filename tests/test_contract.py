"""The contract with material-grub: the plugin API this part is written for, and the shared conf keys it reads. Needs a checkout of material-grub
(MATERIAL_GRUB=path, else ../material-grub); in CI REQUIRE_CONTRACT=1 makes a missing or incompatible one a failure, not a skip.
usage: python3 tests/test_contract.py"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_CORE_API = 1  # the plugin API this part is written for (material-grub install/bin/mgplugins.py CORE_API)
MG = Path(os.environ.get("MATERIAL_GRUB") or ROOT.parent / "material-grub")
REQUIRED = os.environ.get("REQUIRE_CONTRACT") == "1"


class Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bindir = MG / "install/bin"
        if not (bindir / "mgplugins.py").is_file():
            msg = f"no material-grub with the plugin API at {MG} (set MATERIAL_GRUB to a checkout of a ref that has install/bin/mgplugins.py)"
            if REQUIRED:
                raise AssertionError(msg)
            raise unittest.SkipTest(msg)
        sys.path.insert(0, str(bindir))
        import mgplugins
        import mgrub

        cls.mgplugins, cls.mgrub = mgplugins, mgrub

    def test_the_plugin_api_is_the_one_this_part_is_written_for(self):
        self.assertEqual(
            self.mgplugins.CORE_API,
            EXPECTED_CORE_API,
            "material-grub changed its plugin API: update this part (and EXPECTED_CORE_API) before it can be installed next to it",
        )

    def test_the_shared_conf_keys_exist_with_these_choices(self):
        d, ch = self.mgrub.CONF_DEFAULTS, self.mgrub.CONF_CHOICES
        self.assertEqual((d["PLYMOUTH"], d["PLYMOUTH_BAR"], d["PLYMOUTH_MOTION"]), ("on", "indeterminate", "full"))
        self.assertEqual(ch["PLYMOUTH_BAR"], ("indeterminate", "progress"))
        self.assertEqual(ch["PLYMOUTH_MOTION"], ("full", "calm", "off"))

    def test_a_manifest_like_the_one_this_part_will_ship_is_accepted(self):
        with tempfile.TemporaryDirectory() as t:
            entry = Path(t) / "mgplugin.py"
            entry.write_text("def main(argv, core):\n    return 0\n")
            m = Path(t) / "plymouth.json"
            m.write_text(
                json.dumps(
                    {
                        "manifest": 1,
                        "name": "plymouth",
                        "title": "Plymouth boot splash",
                        "version": "0.0.0",
                        "core_api": EXPECTED_CORE_API,
                        "entry": str(entry),
                    }
                )
            )
            rec = self.mgplugins.read_manifest(m, reserved=("apply", "doctor"))
            self.assertIsNone(rec.problem)
            self.assertEqual(rec.name, "plymouth")


if __name__ == "__main__":
    unittest.main()
