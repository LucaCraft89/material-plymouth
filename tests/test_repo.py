"""The repository itself: licence, that the workflow parses and only uses pinned actions, and that the CI scripts are valid and executable.
usage: python3 tests/test_repo.py   (needs PyYAML)"""

import os
import re
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github/workflows").glob("*.yml"))


class Repo(unittest.TestCase):
    def test_licence(self):
        text = (ROOT / "LICENSE").read_text()
        self.assertTrue(text.startswith("MIT License"))

    def test_there_is_a_workflow(self):
        self.assertTrue(WORKFLOWS, "no workflow in .github/workflows")

    def test_workflows_parse_and_every_job_has_a_name_and_a_runner(self):
        for wf in WORKFLOWS:
            with self.subTest(wf=wf.name):
                data = yaml.safe_load(wf.read_text())
                self.assertIn("jobs", data)
                for key, job in data["jobs"].items():
                    self.assertIn("runs-on", job, f"{wf.name}: job {key} has no runs-on")
                    self.assertTrue(job.get("name"), f"{wf.name}: job {key} has no name")

    def test_actions_are_pinned_to_a_version(self):
        for wf in WORKFLOWS:
            for line in wf.read_text().splitlines():
                m = re.match(r"^\s*(?:-\s*)?uses:\s*(\S+)", line)
                if m and not m[1].startswith("./"):
                    self.assertRegex(
                        m[1], r"^[\w.-]+/[\w./-]+@v\d+(\.\d+)*$", f"{wf.name}: '{m[1]}' is not pinned to a version tag"
                    )

    def test_ci_scripts_are_valid_executable_and_strict(self):
        scripts = sorted((ROOT / "ci").glob("*.sh"))
        self.assertTrue(scripts)
        for s in scripts:
            with self.subTest(script=s.name):
                self.assertTrue(os.access(s, os.X_OK), f"{s.name} is not executable")
                self.assertEqual(subprocess.run(["sh", "-n", str(s)]).returncode, 0)
                head = s.read_text().splitlines()
                self.assertTrue(head[0].startswith("#!/bin/sh"))
                self.assertTrue(
                    any(re.match(r"^set -[eu]+", ln) for ln in head), f"{s.name} does not use set -u / set -eu"
                )

    def test_the_workflow_runs_every_ci_script_it_needs(self):
        text = "\n".join(wf.read_text() for wf in WORKFLOWS)
        for name in ("xvfb_play.sh", "probe-distro.sh", "check_frames.py"):
            self.assertIn(name, text, f"{name} exists but no job runs it")


if __name__ == "__main__":
    unittest.main()
