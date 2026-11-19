"""The ONLY place material-plymouth reaches into material-grub (plan: it is written as the future shared-library API, so extracting it later is a move).

What it uses of material-grub, and nothing else:
  mgrub        conf (`load_conf`), title parsing (`parse_title`), the catalog matching rules (`key_for`)
  mgoverrides  overrides.json (`load`)
  mgcustom     `apply`: the one function that turns overrides into a colour, name and icon per entry. Plymouth calls the SAME function GRUB does, so the
               two cannot disagree about what the booted distro looks like.
  mgscenes     `Renderer`: palettes, glyphs, fonts and the drawing primitives, so the pixels come from the same code too.

Finding material-grub: $MATERIAL_GRUB (a checkout: install/bin and dist/material-grub, or $MATERIAL_PKG for the package directory), else an installed one
(/usr/share/material-grub, or /var/lib/material-grub/pkg on an immutable system).
"""

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

DESIGN_ASPECT = "16x9"  # mgcustom wants a scene set; Plymouth draws its own layers and only needs the Renderer's palettes and glyphs


class CoreNotFound(Exception):
    pass


def candidates():
    """[(bin dir, package dir)] in the order they are tried."""
    out = []
    env = os.environ.get("MATERIAL_GRUB")
    if env:
        root = Path(env)
        out.append((root / "install/bin", Path(os.environ.get("MATERIAL_PKG") or root / "dist/material-grub")))
    for p in ("/usr/share/material-grub", "/var/lib/material-grub/pkg"):
        out.append((Path(p) / "bin", Path(p)))
    return out


_core = None


def core(refresh=False):
    """material-grub's modules and package directory as one object: .mgrub .mgoverrides .mgcustom .mgscenes .pkg. Raises CoreNotFound with the reason."""
    global _core
    if _core is not None and not refresh:
        return _core
    tried = []
    for bindir, pkg in candidates():
        if (bindir / "mgscenes.py").is_file() and (pkg / "palettes.json").is_file():
            if str(bindir) not in sys.path:
                sys.path.insert(0, str(bindir))
            import mgcustom
            import mgoverrides
            import mgrub
            import mgscenes

            _core = SimpleNamespace(
                mgrub=mgrub, mgoverrides=mgoverrides, mgcustom=mgcustom, mgscenes=mgscenes, pkg=pkg, bin=bindir
            )
            return _core
        tried.append(f"{bindir} + {pkg}")
    raise CoreNotFound(
        "material-grub is not installed (or no package is built): looked in "
        + ", ".join(tried or ["nothing (set MATERIAL_GRUB)"])
    )


# ---------------------------------------------------------------- who is booting
def parse_os_release(text):
    """os-release text -> dict (KEY=value, quotes removed)."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line.strip())
        if m:
            v = m.group(2).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            out[m.group(1)] = v
    return out


def grub_class(osrel):
    """The --class grub-mkconfig gives this distro's entries: the first word of the distributor name, lowercased, other characters turned into _."""
    name = osrel.get("NAME") or osrel.get("ID") or ""
    first = (name.split() or [""])[0].lower()
    return re.sub(r"[^a-z0-9_]", "_", first)


def identify(osrel, c=None):
    """(catalog key, the entry dict) for the booted system, the way GRUB's cmd_classes names an entry: the catalog's title rules on the title first,
    then the classes, else the Linux penguin. The title is what GRUB would show for it (PRETTY_NAME)."""
    c = c or core()
    title = osrel.get("PRETTY_NAME") or osrel.get("NAME") or "Linux"
    rules = c.mgrub.load_rules(c.pkg)
    classes = json.loads((c.pkg / "classes.json").read_text())
    alias2key = {a: k for k, al in classes.items() for a in al}
    key = c.mgrub.key_for(title, rules)
    if not key:
        for cls in (grub_class(osrel), (osrel.get("ID") or "").lower()):
            if cls in alias2key:
                key = alias2key[cls]
                break
    key = key or "tux"
    e = {"class": "mg_plymouth", "key": key, "kind": "kernel", "level": "top", "title": title}
    # the info pills, from os-release instead of a GRUB title: OS name, version, edition. No kernel-version pill (one theme serves every kernel's initramfs,
    # decision 9 of the plan) and no "on /dev/sdX" (this is the booted system).
    e.update(
        {
            "os": osrel.get("NAME") or None,
            "osver": osrel.get("VERSION_ID") or None,
            "edition": osrel.get("VARIANT") or None,
            "kver": None,
            "where": None,
        }
    )
    return key, e


# ---------------------------------------------------------------- the look
class Look:
    """Everything the Plymouth scenes are drawn from, resolved once. Built only by look()."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def summary(self):
        """The comparable part (no objects): what the consistency tests check against GRUB."""
        return {
            "key": self.key,
            "title": self.title,
            "palette": dict(self.palette),
            "icon": self.icon,
            "cookie": self.cookie,
            "logo": self.logo,
            "style": self.style,
            "dark": self.dark,
        }


def look(conf=None, overrides=None, osrel=None, height=1080, icon_dir=None, c=None, tmp=None):
    """Resolve the look of the booted distro under `conf` (mgrub.load_conf()), `overrides` (mgoverrides.load()[0]) and `osrel` (a dict from
    parse_os_release). It runs GRUB's own mgcustom.apply on a one-entry menu, so colour, name, icon and the one-colour mode are GRUB's answers."""
    c = c or core()
    conf = conf if conf is not None else c.mgrub.load_conf()
    if overrides is None:
        overrides, _ = c.mgoverrides.load()
    if osrel is None:
        try:
            osrel = parse_os_release(Path(os.environ.get("OS_RELEASE", "/etc/os-release")).read_text())
        except OSError:
            osrel = {}
    R = c.mgscenes.Renderer(c.pkg, height)
    classes = json.loads((c.pkg / "classes.json").read_text())
    key, entry = identify(osrel, c)
    own_tmp = tmp is None
    tmp = Path(tmp or tempfile.mkdtemp(prefix="mp-look-"))
    try:
        c.mgcustom.apply(
            R,
            overrides,
            [entry],
            c.pkg,
            DESIGN_ASPECT,
            (round(height * 16 / 9), height),
            classes,
            icon_dir=icon_dir,
            tmp=tmp,
            log=lambda *_a: None,
        )
    finally:
        if own_tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    k = entry["key"]  # 'fedora~1' when the rules customised this entry, else the catalog key
    glyph = R.galias.get(k, k)  # the glyph the renderer draws for this entry
    icon = "file" if k in R.logos else (glyph if glyph != key else None)  # None: the catalog glyph of its own distro
    cookie = conf["COOKIE"] == "on"
    return Look(
        key=k,
        base_key=key,
        entry=entry,
        R=R,
        core=c,
        palette=dict(R.pal[k]),
        title=R.title_for(entry),
        icon=icon,
        cookie=cookie,
        logo=cookie and conf["LOGO"] == "on",
        style=conf["STYLE"] if conf["STYLE"] != "full" else "rail",
        dark=not R.light,
        conf=conf,
        height=height,
    )
