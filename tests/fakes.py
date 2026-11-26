"""A fake machine for apply/remove: a scratch root plus scripted programs (dracut, update-initramfs, mkinitcpio, the image listers, grubby,
plymouth-set-default-theme, update-alternatives) that keep their state in files under the root, so a test can run the real logic, inject a failure at any
step and compare the whole tree before and after. No real boot chain, no root."""

import hashlib
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from material_plymouth.system import System  # noqa: E402


class FakeSystem(System):
    def __init__(self, root, tools, free=10**12):
        super().__init__(str(root))
        self.tools, self._free, self.calls = dict(tools), free, []

    def which(self, name):
        return name if name in self.tools else None

    def run(self, cmd, timeout=900):
        self.calls.append([str(c) for c in cmd])
        fn = self.tools.get(cmd[0])
        return fn(self, [str(c) for c in cmd]) if fn else (127, f"{cmd[0]}: not found")

    def free_bytes(self, path):
        return self._free


def snapshot(root, skip=("var/backups",)):
    """{relative path: sha256} of every file under root (except the backups): two equal snapshots are the same machine."""
    out = {}
    for f in sorted(Path(root).rglob("*")):
        rel = str(f.relative_to(root))
        if f.is_file() and not any(rel.startswith(s) for s in skip):
            out[rel] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


# ---------------------------------------------------------------- the images
def theme_listing(fs, hook_ok=True):
    """What a real initramfs builder would put in: the theme's files (if there is a theme) and the script plugin."""
    lines = ["usr/bin/plymouth", "usr/lib64/plymouth/text.so"]
    theme = fs.p("usr/share/plymouth/themes/material")
    if hook_ok and theme.is_dir():
        lines += ["usr/lib64/plymouth/script.so", "usr/lib64/plymouth/label-freetype.so"] + [
            f"usr/share/plymouth/themes/material/{f.name}" for f in sorted(theme.iterdir()) if f.is_file()
        ]
    return lines


def builder(fail=False, include_theme=True, needs_hook=False, wait_for=None):
    """dracut / update-initramfs / mkinitcpio: rewrite every image."""

    def run(fs, cmd):
        if fail:
            return 1, "error: cannot build the image"
        hook = True
        if needs_hook:
            conf = fs.read("/etc/mkinitcpio.conf", "")
            hook = bool(re.search(r"HOOKS=.*\bplymouth\b", conf))
        for img in fs.images():
            text = "\n".join(theme_listing(fs, include_theme and hook)) + "\n" + "x" * 2000
            img.write_text(text)
        return 0, ""

    return run


def lister(fs, cmd):
    f = Path(cmd[-1])
    return (0, "\n".join(ln for ln in f.read_text().splitlines() if "/" in ln)) if f.exists() else (1, "no such image")


def set_default_theme(fs, cmd):
    f = fs.p("etc/plymouth/default-theme")
    f.parent.mkdir(parents=True, exist_ok=True)
    if len(cmd) == 1:
        return 0, (f.read_text() if f.exists() else "bgrt") + "\n"
    f.write_text("bgrt" if cmd[1] == "--reset" else cmd[1])
    return 0, ""


def alternatives(fs, cmd):
    st = fs.p("etc/alternatives/default.plymouth")
    reg = fs.p("var/lib/dpkg/alternatives-default.plymouth")
    st.parent.mkdir(parents=True, exist_ok=True)
    reg.parent.mkdir(parents=True, exist_ok=True)
    known = reg.read_text().splitlines() if reg.exists() else []
    cur = st.read_text().strip() if st.exists() else ""
    if cmd[1] == "--query":
        return (0, f"Name: default.plymouth\nValue: {cur}\n") if cur else (2, "no alternatives")
    if cmd[1] == "--install":
        if cmd[4] not in known:
            known.append(cmd[4])
            reg.write_text("\n".join(known))
        if not cur:
            st.write_text(cmd[4])
        return 0, ""
    if cmd[1] == "--set":
        st.write_text(cmd[3])
        return 0, ""
    if cmd[1] == "--remove":
        known = [k for k in known if k != cmd[3]]
        reg.write_text("\n".join(known))
        if cur == cmd[3]:
            st.write_text(known[0]) if known else st.unlink()
        return 0, ""
    return 1, "bad call"


def grubby(fs, cmd):
    entries = sorted(fs.p("boot/loader/entries").glob("*.conf"))
    if cmd[1] == "--info=ALL":
        return 0, "".join(
            f'index={i}\nargs="{re.search(r"^options (.*)$", e.read_text(), re.M).group(1)}"\n\n'
            for i, e in enumerate(entries)
        )
    words = cmd[cmd.index("--args") + 1].split() if "--args" in cmd else cmd[cmd.index("--remove-args") + 1].split()
    for e in entries:
        text = e.read_text()
        cur = re.search(r"^options (.*)$", text, re.M).group(1).split()
        new = cur + [w for w in words if w not in cur] if "--args" in cmd else [w for w in cur if w not in words]
        e.write_text(re.sub(r"^options .*$", "options " + " ".join(new), text, flags=re.M))
    return 0, ""


# ---------------------------------------------------------------- whole machines
def base_root(root, kernels=("6.1.0", "6.2.0")):
    root = Path(root)
    (root / "usr/lib64/plymouth").mkdir(parents=True)
    (root / "usr/lib64/plymouth/script.so").write_bytes(b"\x7fELF")
    (root / "usr/lib64/plymouth/label-freetype.so").write_bytes(b"\x7fELF")
    (root / "usr/share/plymouth/themes/spinner").mkdir(parents=True)
    (root / "usr/share/plymouth/themes/spinner/spinner.plymouth").write_text("[Plymouth Theme]\n")
    (root / "boot").mkdir()
    for k in kernels:
        (root / f"boot/initramfs-{k}.img").write_text("old image of " + k + "\n" + "x" * 2000)
    (root / "etc/default").mkdir(parents=True)
    (root / "sys/class/drm/card0-eDP-1").mkdir(parents=True)
    (root / "sys/class/drm/card0-eDP-1/status").write_text("connected\n")
    (root / "sys/class/drm/card0-eDP-1/modes").write_text("1366x768\n1280x720\n")
    return root


def fedora(root, **kw):
    """dracut + grubby + plymouth-set-default-theme, BLS entries."""
    root = base_root(root)
    (root / "boot/loader/entries").mkdir(parents=True)
    for k in ("6.1.0", "6.2.0"):
        (root / f"boot/loader/entries/{k}.conf").write_text(f"title Fedora ({k})\noptions ro root=/dev/sda2\n")
    (root / "etc/plymouth").mkdir(parents=True)
    (root / "etc/plymouth/default-theme").write_text("bgrt")
    tools = {
        "dracut": builder(**kw),
        "lsinitrd": lister,
        "plymouth-set-default-theme": set_default_theme,
        "grubby": grubby,
    }
    return FakeSystem(root, tools)


def ubuntu(root, **kw):
    """initramfs-tools + update-alternatives, /etc/default/grub."""
    root = base_root(root, ("6.8.0-45-generic",))
    for f in (root / "boot").glob("initramfs-*.img"):
        f.rename(root / "boot" / f.name.replace("initramfs-", "initrd.img-").replace(".img", ""))
    (root / "etc/default/grub").write_text(
        'GRUB_TIMEOUT=5\nGRUB_CMDLINE_LINUX_DEFAULT="quiet"\nGRUB_CMDLINE_LINUX=""\n'
    )
    (root / "etc/alternatives").mkdir(parents=True)
    (root / "etc/alternatives/default.plymouth").write_text("/usr/share/plymouth/themes/spinner/spinner.plymouth")
    (root / "var/lib/dpkg").mkdir(parents=True)
    (root / "var/lib/dpkg/alternatives-default.plymouth").write_text(
        "/usr/share/plymouth/themes/spinner/spinner.plymouth"
    )
    tools = {"update-initramfs": builder(**kw), "lsinitramfs": lister, "update-alternatives": alternatives}
    return FakeSystem(root, tools)


def arch(root, **kw):
    """mkinitcpio (the plymouth hook decides whether the image has the theme) + plymouth-set-default-theme."""
    root = base_root(root, ())
    (root / "boot/initramfs-linux.img").write_text("old\n" + "x" * 2000)
    (root / "boot/initramfs-linux-fallback.img").write_text("old fb\n" + "x" * 2000)
    (root / "etc/default/grub").write_text('GRUB_CMDLINE_LINUX_DEFAULT="loglevel=3 quiet"\n')
    (root / "etc/mkinitcpio.conf").write_text(
        "MODULES=()\nHOOKS=(base udev autodetect modconf kms block filesystems fsck)\n"
    )
    (root / "etc/plymouth").mkdir(parents=True)
    (root / "etc/plymouth/default-theme").write_text("bgrt")
    tools = {
        "mkinitcpio": builder(needs_hook=True, **kw),
        "lsinitcpio": lister,
        "plymouth-set-default-theme": set_default_theme,
    }
    return FakeSystem(root, tools)


def age(path, seconds=3600):
    t = os.stat(path).st_mtime - seconds
    os.utime(path, (t, t))
