"""The contract with material-boot-core: the plugin API this part is written for, the shared conf keys it reads, and that the manifest it ships is accepted.
Needs a checkout (or an install) of the core: MATERIAL_LIB (default ../material-boot-core); in CI REQUIRE_CONTRACT=1 makes a missing or incompatible one a
failure, not a skip. usage: python3 tests/test_contract.py"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_CORE_API = 2  # the plugin API this part is written for (material_boot.CORE_API)
LIB = Path(os.environ.get("MATERIAL_LIB") or ROOT.parent / "material-boot-core")
REQUIRED = os.environ.get("REQUIRE_CONTRACT") == "1"


class Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (LIB / "material_boot/plugins.py").is_file():
            msg = f"no material-boot-core at {LIB} (set MATERIAL_LIB to the directory that holds the material_boot package)"
            if REQUIRED:
                raise AssertionError(msg)
            raise unittest.SkipTest(msg)
        sys.path.insert(0, str(LIB))
        import material_boot
        from material_boot import conf, plugins

        cls.material_boot, cls.conf, cls.plugins = material_boot, conf, plugins

    def test_the_plugin_api_is_the_one_this_part_is_written_for(self):
        self.assertEqual(
            self.material_boot.CORE_API,
            EXPECTED_CORE_API,
            "the core changed its plugin API: update this part (and EXPECTED_CORE_API) before it can be installed next to it",
        )

    def test_the_shared_conf_keys_exist_with_these_choices(self):
        d, ch = self.conf.CONF_DEFAULTS, self.conf.CONF_CHOICES
        self.assertEqual((d["PLYMOUTH"], d["PLYMOUTH_BAR"], d["PLYMOUTH_MOTION"]), ("on", "indeterminate", "full"))
        self.assertEqual(ch["PLYMOUTH_BAR"], ("indeterminate", "progress"))
        self.assertEqual(ch["PLYMOUTH_MOTION"], ("full", "calm", "off"))

    def render(self, d):
        """packaging/plymouth.json.in as install-tree.sh writes it, with `entry` pointing at a real file."""
        text = (ROOT / "packaging/plymouth.json.in").read_text()
        entry = Path(d) / "mgplugin.py"
        entry.write_text("def main(argv, core):\n    return 0\n")
        m = Path(d) / "plymouth.json"
        m.write_text(text.replace("@VERSION@", "1.0.0").replace("@SHARE@/bin/mgplugin.py", str(entry)))
        return m

    def test_the_manifest_this_part_ships_is_accepted(self):
        with tempfile.TemporaryDirectory() as t:
            rec = self.plugins.read_manifest(self.render(t))
        self.assertIsNone(rec.problem)
        self.assertEqual(rec.name, "plymouth")
        self.assertEqual(rec.warnings, [])
        self.assertFalse(rec.default, "the splash changes how the machine boots: it is never installed unasked")
        self.assertEqual(rec.needs, [], "Plymouth needs only the core")
        self.assertEqual(rec.layouts, ["normal"])

    def test_its_commands_and_menu_are_its_own(self):
        with tempfile.TemporaryDirectory() as t:
            rec = self.plugins.read_manifest(self.render(t))
        self.assertEqual(sorted(rec.commands), ["apply", "build", "preview", "remove", "status"])
        self.assertTrue(rec.menu and all(w[0] == "plymouth" for _t, _d, w in rec.menu))

    def test_a_stale_api_in_the_manifest_would_be_refused(self):
        with tempfile.TemporaryDirectory() as t:
            m = self.render(t)
            data = json.loads(m.read_text())
            data["core_api"] = EXPECTED_CORE_API + 1
            m.write_text(json.dumps(data))
            self.assertIsNotNone(self.plugins.read_manifest(m).problem)

    def test_the_core_runs_without_this_part_and_says_so(self):
        r = subprocess.run(
            [sys.executable, "-m", "material_boot", "core", "parts"],
            capture_output=True,
            text=True,
            env=dict(os.environ, PYTHONPATH=str(LIB), MATERIAL_PLUGIN_PATH="/nonexistent"),
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("plymouth", r.stdout.replace("none installed", ""))


if __name__ == "__main__":
    unittest.main()
