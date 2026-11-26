#!/usr/bin/env python3
"""Tier 3: `material-grub plymouth apply` and `remove` against a REAL initramfs tool (dracut, initramfs-tools or mkinitcpio) in a distro container.

Run by ci/initramfs-e2e.sh inside the container, after it has installed Plymouth, the initramfs tool, a kernel and Pillow.
It drives the same entry point the user does (plugin.main) on the real root and checks, with the distro's own lister, what ended up in the images:

  1  baseline        build the initramfs once without our theme; it must not contain it
  2  apply           every image holds the theme, the script plugin and the pictures; the theme script inside is byte-identical to the installed one;
                     the default theme is ours; the state is recorded
  3  apply again     --if-changed rebuilds nothing
  4  failure: tool   the initramfs tool fails -> status rolled-back, images / default theme / theme dir / config all as before
  5  failure: image  the tool "succeeds" but writes broken images -> verification catches it, same rollback
  6  remove          the previous default theme is back and no image holds the theme any more

Exit code 0 only when every check passed. Prints one line per check.
"""

import hashlib
import io
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["MATERIAL_OVERRIDES"] = "/nonexistent/material-grub/overrides.json"
os.environ["MG_BGRT_IMAGE"] = "/nonexistent/bgrt"

from material_plymouth import adapter, plugin  # noqa: E402
from material_plymouth.apply import THEME_DIR, read_state  # noqa: E402
from material_plymouth.system import TOOLS, System  # noqa: E402

FAILED = []
CONF = "/etc/material-grub.conf"


def check(ok, what, detail=""):
    print(("PASS  " if ok else "FAIL  ") + what + (f"\n        {detail}" if detail and not ok else ""), flush=True)
    if not ok:
        FAILED.append(what)
    return ok


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tree(path):
    out = {}
    p = Path(path)
    if p.is_dir():
        for f in sorted(p.rglob("*")):
            if f.is_file():
                out[str(f.relative_to(p))] = sha(f)
    return out


class Machine:
    """The real root, seen the way the checks need it."""

    def __init__(self):
        self.sys = System("")
        self.tool = self.sys.initramfs_tool()
        self.lister = TOOLS[self.tool][1]

    def images(self):
        return self.sys.images()

    def snapshot(self):
        return {
            "images": {i.name: sha(i) for i in self.images()},
            "theme": tree("/" + THEME_DIR.lstrip("/")),
            "default": self.sys.default_theme(),
            "conf": {
                p: Path(p).read_text()
                for p in ("/etc/mkinitcpio.conf", "/etc/default/grub", "/etc/kernel/cmdline")
                if Path(p).exists()
            },
            "state": Path("/var/lib/material-plymouth/state.json").exists(),
        }

    def listing(self, img):
        r = subprocess.run(self.lister + [str(img)], capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    def read_in_image(self, img, inner):
        """The bytes of `inner` (a path without a leading slash) inside the image, or None."""
        if self.tool == "dracut":
            r = subprocess.run(["lsinitrd", str(img), "-f", inner], capture_output=True)
            return r.stdout if r.returncode == 0 and r.stdout else None
        tmp = tempfile.mkdtemp()
        try:
            if self.tool == "mkinitcpio":
                subprocess.run(["lsinitcpio", "-x", str(img)], cwd=tmp, capture_output=True)
            else:  # initramfs-tools: unmkinitramfs handles the early microcode cpio and the compressed main one
                subprocess.run(["unmkinitramfs", str(img), tmp], capture_output=True)
            hits = list(Path(tmp).rglob(Path(inner).name))
            hits = [h for h in hits if str(h).endswith(inner)]
            return hits[0].read_bytes() if hits else None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class Core:
    """What the core's plugin loader hands a plugin, reduced to what material-plymouth uses."""

    @staticmethod
    def say(*a):
        print("        | " + " ".join(str(x) for x in a))

    @staticmethod
    def conf_path():
        return CONF

    @staticmethod
    def elevate(*_a):
        pass


def run(*argv):
    """`material-boot plymouth <argv>` -> (exit code, output)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        try:
            rc = plugin.main(list(argv), Core())
        except SystemExit as e:  # argparse
            rc = e.code or 0
    out = buf.getvalue()
    for line in out.splitlines():
        print("        | " + line)
    return rc, out


def shim(tool, mode):
    """A `tool` in front of PATH that fails (mode 'fail') or runs the real one and then breaks the images it wrote (mode 'corrupt'). Returns the directory."""
    d = Path(tempfile.mkdtemp(prefix="shim-"))
    real = shutil.which(tool if tool != "initramfs-tools" else "update-initramfs")
    name = Path(real).name
    body = (
        "#!/bin/sh\necho 'forced failure' >&2\nexit 1\n"
        if mode == "fail"
        else f'#!/bin/sh\n{real} "$@" || exit $?\nfor f in /boot/initramfs-*.img /boot/initrd.img-* /boot/initrd-*; do [ -f "$f" ] && : > "$f"; done\nexit 0\n'
    )
    f = d / name
    f.write_text(body)
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return d


def main():
    m = Machine()
    print(
        f"initramfs tool: {m.tool}; kernels: {sorted(p.name for p in Path('/lib/modules').glob('*'))}; Plymouth: {shutil.which('plymouthd') or 'plymouthd not on PATH'}"
    )
    if not check(m.tool is not None, "an initramfs tool is installed"):
        return 1
    try:
        adapter.core()
    except adapter.CoreNotFound as e:
        check(False, "material-boot-core is found", str(e))
        return 1

    # ---- 1 baseline: the distro's own initramfs
    cmd, _l = TOOLS[m.tool]
    if m.tool == "initramfs-tools":
        cmd = [
            "update-initramfs",
            "-c",
            "-k",
            "all",
        ]  # -u only updates an image that exists; a fresh container has none (a real system always does)
    r = subprocess.run(cmd, capture_output=True, text=True)
    check(r.returncode == 0, f"the distro's own `{' '.join(cmd)}` works here", (r.stdout + r.stderr)[-1500:])
    imgs = m.images()
    if not check(bool(imgs), "an initramfs image exists to work on", f"images={imgs}"):
        return 1
    for i in imgs:
        rc, out = m.listing(i)
        check(rc == 0, f"{i.name}: the lister can read the distro's image", out[-300:])
        check("themes/material/material.script" not in out, f"{i.name}: baseline has no Material theme")
    before = m.snapshot()
    default_before = before["default"]

    # ---- 2 apply
    rc, out = run("apply", "--yes")
    check(rc == 0, "apply exits 0", out[-800:])
    st = read_state(m.sys)
    check(bool(st) and st.get("tool") == m.tool, "state is recorded with the tool used", str(st)[:300])
    check(
        m.sys.default_theme() == "material" or "material" in str(m.sys.default_theme()),
        f"the default theme is ours (is: {m.sys.default_theme()})",
    )
    imgs = m.images()
    installed_script = Path("/" + THEME_DIR.lstrip("/") + "/material.script").read_bytes()
    for i in imgs:
        rc, out = m.listing(i)
        check(rc == 0 and "themes/material/material.script" in out, f"{i.name}: lists the theme script", out[-300:])
        check("script.so" in out, f"{i.name}: lists the script plugin")
        pngs = len(re.findall(r"themes/material/\S+\.png", out))
        check(pngs >= 5, f"{i.name}: lists the theme's pictures ({pngs})")
        check("plymouthd" in out, f"{i.name}: lists plymouthd")
        inner = m.read_in_image(i, "usr/share/plymouth/themes/material/material.script")
        check(
            inner == installed_script,
            f"{i.name}: the theme script inside is byte-identical to the installed one",
            "differs or could not be extracted" if inner is None else "differs",
        )
    if m.tool == "mkinitcpio":
        conf = Path("/etc/mkinitcpio.conf").read_text()
        check(
            re.search(r"^HOOKS=.*\bplymouth\b", conf, re.M) is not None,
            "the plymouth hook was added to mkinitcpio.conf",
        )
    after_apply = m.snapshot()

    # ---- 3 apply again, nothing changed
    stamps = {i.name: i.stat().st_mtime_ns for i in imgs}
    rc, out = run("apply", "--yes", "--if-changed")
    check(
        rc == 0 and all(i.stat().st_mtime_ns == stamps[i.name] for i in m.images()),
        "--if-changed with the same look rebuilds nothing",
        out[-400:],
    )

    # ---- 4/5 forced failures leave everything as it was
    Path(CONF).write_text("STYLE=split\nPLYMOUTH_MOTION=calm\n")  # a different look, so apply has something to do
    for mode, label in (("fail", "the tool fails"), ("corrupt", "the tool writes broken images")):
        d = shim(m.tool, mode)
        env_path = os.environ["PATH"]
        os.environ["PATH"] = f"{d}:{env_path}"
        try:
            rc, out = run("apply", "--yes")
        finally:
            os.environ["PATH"] = env_path
            shutil.rmtree(d, ignore_errors=True)
        now = m.snapshot()
        check(rc != 0 and "everything was put back" in out, f"failure ({label}): apply reports a rollback", out[-500:])
        check(
            now["images"] == after_apply["images"],
            f"failure ({label}): every initramfs image is byte-identical to before",
            f"{now['images']} != {after_apply['images']}",
        )
        check(now["theme"] == after_apply["theme"], f"failure ({label}): the theme directory is as before")
        check(
            now["default"] == after_apply["default"],
            f"failure ({label}): the default theme is as before ({now['default']})",
        )
        check(now["conf"] == after_apply["conf"], f"failure ({label}): config files are as before")
    Path(CONF).unlink()

    # ---- 6 remove
    rc, out = run("remove", "--yes")
    check(rc == 0, "remove exits 0", out[-600:])
    check(not Path("/" + THEME_DIR.lstrip("/")).exists(), "the theme directory is gone")
    check(
        m.sys.default_theme() == default_before,
        f"the previous default theme is back (was {default_before}, is {m.sys.default_theme()})",
    )
    for i in m.images():
        rc, out = m.listing(i)
        check(
            rc == 0 and "themes/material/material.script" not in out, f"{i.name}: no longer holds the theme", out[-300:]
        )
    if m.tool == "mkinitcpio":
        has = re.search(r"^HOOKS=.*\bplymouth\b", Path("/etc/mkinitcpio.conf").read_text(), re.M)
        was = re.search(r"^HOOKS=.*\bplymouth\b", before["conf"].get("/etc/mkinitcpio.conf", ""), re.M)
        check(bool(has) == bool(was), "mkinitcpio.conf has the plymouth hook only if it had it before")

    print()
    print("RESULT: " + ("FAIL: " + "; ".join(FAILED) if FAILED else "all checks passed"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
