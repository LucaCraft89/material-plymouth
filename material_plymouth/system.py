"""Everything material-plymouth asks of the machine it runs on, behind one small class, so that the logic of apply and remove can be tested with a fake one
(a scratch root and scripted commands) instead of a real boot chain. `root` is "" for the real system; every path goes through p()."""

import glob
import os
import re
import shutil
import subprocess
from pathlib import Path

THEME_NAME = "material"
THEMES = "usr/share/plymouth/themes"
TOOLS = {  # initramfs tool -> (rebuild everything, list an image)
    "dracut": (["dracut", "-f", "--regenerate-all"], ["lsinitrd"]),
    "initramfs-tools": (["update-initramfs", "-u", "-k", "all"], ["lsinitramfs"]),
    "mkinitcpio": (["mkinitcpio", "-P"], ["lsinitcpio"]),
}
IMAGE_GLOBS = ("boot/initramfs-*.img", "boot/initrd.img-*", "boot/initrd-*")


class System:
    def __init__(self, root="", uname_release=None):
        self.root = Path(root or "/")
        self.real = not root
        self._release = uname_release

    # ---- files
    def p(self, path):
        return self.root / str(path).lstrip("/")

    def exists(self, path):
        return self.p(path).exists()

    def read(self, path, default=None):
        try:
            return self.p(path).read_text()
        except OSError:
            return default

    def write(self, path, text, mode=None):
        """Atomic replace (temp file next to it, then rename); keeps the file's mode unless `mode` is given."""
        f = self.p(path)
        f.parent.mkdir(parents=True, exist_ok=True)
        keep = f.stat().st_mode & 0o7777 if f.exists() else 0o644
        tmp = f.with_name(f.name + ".material-new")
        tmp.write_text(text)
        os.chmod(tmp, mode if mode is not None else keep)
        os.replace(tmp, f)

    # ---- commands
    def which(self, name):
        return shutil.which(name)

    def run(self, cmd, timeout=900):
        """Run a command; returns (returncode, output). Never raises for a failing command (a missing program is returncode 127)."""
        try:
            r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, timeout=timeout, errors="replace")
            return r.returncode, (r.stdout or "") + (r.stderr or "")
        except FileNotFoundError:
            return 127, f"{cmd[0]}: not found"
        except subprocess.TimeoutExpired:
            return 124, f"{cmd[0]}: timed out after {timeout} s"

    # ---- what is installed here
    def release(self):
        return self._release or os.uname().release

    def script_plugin(self):
        """The Plymouth script plugin (script.so), or None."""
        for pat in ("usr/lib*/plymouth/script.so", "usr/lib/*/plymouth/script.so", "usr/libexec/plymouth/script.so"):
            hit = sorted(glob.glob(str(self.p(pat))))
            if hit:
                return hit[0]
        return None

    def label_plugin(self):
        """Plymouth's text-label plugin (label.so, label-ft.so, label-freetype.so, label-pango.so), or None. Plymouth 26's script plugin crashes plymouthd when it
        is missing (it calls the console viewer it did not create), found by the QEMU boot tier; our theme draws no text itself, but the daemon still needs it."""
        for pat in ("usr/lib*/plymouth/label*.so", "usr/lib/*/plymouth/label*.so", "usr/libexec/plymouth/label*.so"):
            hit = sorted(glob.glob(str(self.p(pat))))
            if hit:
                return hit[0]
        return None

    def initramfs_tool(self):
        for tool in ("dracut", "mkinitcpio", "initramfs-tools"):
            probe = {"initramfs-tools": "update-initramfs"}.get(tool, tool)
            if self.which(probe):
                return tool
        return None

    def images(self):
        """The initramfs images that exist (kdump and rescue images are not ours to rebuild)."""
        out = []
        for pat in IMAGE_GLOBS:
            out += [Path(f) for f in sorted(glob.glob(str(self.p(pat)))) if not re.search(r"kdump|rescue", f)]
        return sorted(set(out))

    def default_theme(self):
        """The theme Plymouth would use now, or None."""
        if self.which("plymouth-set-default-theme"):
            rc, out = self.run(["plymouth-set-default-theme"])
            return out.strip().splitlines()[0] if rc == 0 and out.strip() else None
        if self.which("update-alternatives"):
            rc, out = self.run(["update-alternatives", "--query", "default.plymouth"])
            m = re.search(r"^Value:\s*(\S+)", out, re.M)
            return m.group(1) if rc == 0 and m else None
        return None

    def set_default_theme(self, name, theme_file):
        """Make `name` the default theme (not rebuilding the initramfs: that is the caller's step). Returns (ok, message)."""
        if self.which("plymouth-set-default-theme"):
            rc, out = self.run(["plymouth-set-default-theme", name])
            return rc == 0, out.strip()
        if self.which("update-alternatives"):
            link = f"/{THEMES}/default.plymouth"
            rc, out = self.run(["update-alternatives", "--install", link, "default.plymouth", theme_file, "200"])
            if rc == 0:
                rc, out = self.run(["update-alternatives", "--set", "default.plymouth", theme_file])
            return rc == 0, out.strip()
        return False, "neither plymouth-set-default-theme nor update-alternatives is available"

    def reset_default_theme(self, previous, theme_file):
        """Undo set_default_theme: back to `previous` (a name or a path), or to whatever the system picks when there was none."""
        if self.which("plymouth-set-default-theme"):
            rc, out = self.run(
                ["plymouth-set-default-theme", previous] if previous else ["plymouth-set-default-theme", "--reset"]
            )
            return rc == 0, out.strip()
        if self.which("update-alternatives"):
            if previous and previous.endswith(f"/{THEME_NAME}/{THEME_NAME}.plymouth"):
                # a second apply that failed: ours was already the default, and removing the alternative would drop Plymouth back to the distro's theme
                # (found by the real-initramfs tier on Ubuntu)
                rc, out = self.run(["update-alternatives", "--set", "default.plymouth", previous])
                return rc == 0, out.strip()
            rc, out = self.run(["update-alternatives", "--remove", "default.plymouth", theme_file])
            if rc == 0 and previous:
                rc, out = self.run(["update-alternatives", "--set", "default.plymouth", previous])
            return rc == 0, out.strip()
        return False, "no tool to reset the default theme"

    def free_bytes(self, path):
        return shutil.disk_usage(self.p(path)).free
