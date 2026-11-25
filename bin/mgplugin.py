"""The entry file named in the plugin manifest: the core imports it and calls main(argv, core) and the hooks of the unified installer. Installed as
<share>/material-plymouth/bin/mgplugin.py, with the material_plymouth package next to it."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from material_plymouth.hooks import (  # noqa: E402,F401
    hook_detect,
    hook_doctor,
    hook_install,
    hook_plan,
    hook_uninstall,
    hook_verify,
)
from material_plymouth.plugin import main  # noqa: E402,F401
