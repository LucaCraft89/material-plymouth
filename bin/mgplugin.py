"""The entry file named in the plugin manifest: material-grub imports it and calls main(argv, core). Installed as <share>/material-plymouth/bin/mgplugin.py,
with the material_plymouth package next to it."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from material_plymouth.plugin import main  # noqa: E402,F401
