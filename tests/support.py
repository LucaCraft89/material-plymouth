"""Shared by the tests that need material-grub's code and a built package (dist/material-grub): finds them, or skips; in CI REQUIRE_CORE=1 makes
a missing one a failure. A built package: `python scripts/package.py --res 1920x1080` in a material-grub checkout."""

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MATERIAL_GRUB", str(Path(os.environ.get("MATERIAL_GRUB") or ROOT.parent / "material-grub")))
os.environ["MATERIAL_OVERRIDES"] = (
    "/nonexistent/material-grub/overrides.json"  # never the overrides of the machine the tests run on
)
os.environ["MG_BGRT_IMAGE"] = "/nonexistent/bgrt"  # no firmware logo: the penguin, the same on every machine

from material_plymouth import adapter  # noqa: E402

REQUIRED = os.environ.get("REQUIRE_CORE") == "1"


def core():
    """material-grub's modules, or raise SkipTest (AssertionError when REQUIRE_CORE=1)."""
    try:
        return adapter.core()
    except adapter.CoreNotFound as e:
        if REQUIRED:
            raise AssertionError(str(e)) from e
        raise unittest.SkipTest(str(e)) from e


FEDORA = 'NAME="Fedora Linux"\nVERSION_ID=44\nVARIANT="Workstation Edition"\nID=fedora\nPRETTY_NAME="Fedora Linux 44 (Workstation Edition)"\n'
ARCH = 'NAME="Arch Linux"\nPRETTY_NAME="Arch Linux"\nID=arch\n'
UBUNTU = 'NAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\nID_LIKE=debian\nPRETTY_NAME="Ubuntu 24.04.1 LTS"\n'
UNKNOWN = 'NAME="Foo OS"\nID=foo\nID_LIKE="ubuntu debian"\nPRETTY_NAME="Foo OS 3"\n'
