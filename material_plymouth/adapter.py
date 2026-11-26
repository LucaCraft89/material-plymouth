"""The ONLY place material-plymouth reaches into the shared code: material-boot-core (the library material-grub uses as well).

What it uses of the core, and nothing else (the names are the ones material-grub's own modules had, so the rest of this part did not change):
  mgrub        conf (`load_conf`, `CONF_DEFAULTS`, `CONF_CHOICES`), title parsing (`parse_title`), the catalog matching rules (`key_for`, `load_rules`)
  mgoverrides  overrides.json (`load`)
  mgcustom     `apply`: the one function that turns overrides into a colour, name and icon per entry. Plymouth calls the SAME function GRUB does, so the
               two cannot disagree about what the booted distro looks like.
  mgscenes     `Renderer`: palettes, glyphs, fonts and the drawing primitives, so the pixels come from the same code too.
  pkg          the shared data the core built for the configured scheme (palettes.json, classes.json, glyphs/, fonts/, ...)

Finding the core: the dispatcher hands over the running one (`attach`); else $MATERIAL_LIB (the directory that holds the material_boot package; the data is
$MATERIAL_DATA, else `data` next to it), else /usr/share/material-boot (packages, installer) and its two other places.
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


MIN_CORE = (1, 0, 0)
CORE_API = 2
SYSTEM_LIBS = ("/usr/share/material-boot/lib", "/usr/local/share/material-boot/lib", "/var/lib/material-boot/lib")


def candidates():
    """[(lib dir, data dir)] in the order they are tried: $MATERIAL_LIB (the directory that holds the material_boot package) and nothing else when it is set,
    else where the packages and the installer put the core. The data is $MATERIAL_DATA, else `data` next to the library, else where the installer builds it
    (a library that is only a bundle's or a checkout's has no data next to it)."""
    env = os.environ.get("MATERIAL_LIB")
    libs = [Path(env)] if env else [Path(p) for p in SYSTEM_LIBS]
    data = os.environ.get("MATERIAL_DATA")
    out = []
    for lib in libs:
        want = (
            [Path(data)]
            if data
            else [
                lib.parent / "data",
                Path("/usr/share/material-boot/data"),
                Path("/usr/local/share/material-boot/data"),
            ]
        )
        found = next((d for d in want if (d / "palettes.json").is_file()), want[0])
        out.append((lib, found))
    return out


def _version(text):
    return tuple(int(x) for x in re.findall(r"\d+", text)[:3])


def _load(lib, data):
    """The core's modules as one object: .mgrub (conf and title rules) .mgoverrides .mgcustom .mgscenes .pkg (the shared data), .lib, .version."""
    if str(lib) not in sys.path:
        sys.path.insert(0, str(lib))
    import material_boot
    from material_boot import conf, custom, overrides, scenes, titles

    if getattr(material_boot, "CORE_API", None) != CORE_API:
        raise CoreNotFound(
            f"material-boot-core at {lib} has plugin API {getattr(material_boot, 'CORE_API', '?')}, this part is written for {CORE_API}"
        )
    if _version(material_boot.__version__) < MIN_CORE:
        raise CoreNotFound(
            f"material-boot-core {material_boot.__version__} at {lib} is older than {'.'.join(map(str, MIN_CORE))}"
        )
    mgrub = SimpleNamespace(
        load_conf=conf.load_conf,
        CONF_DEFAULTS=conf.CONF_DEFAULTS,
        CONF_CHOICES=conf.CONF_CHOICES,
        load_rules=titles.load_rules,
        key_for=titles.key_for,
        parse_title=titles.parse_title,
    )
    return SimpleNamespace(
        mgrub=mgrub,
        mgoverrides=overrides,
        mgcustom=custom,
        mgscenes=scenes,
        pkg=Path(data),
        lib=Path(lib),
        version=material_boot.__version__,
    )


_core = None


def attach(core_obj):
    """Use the core that is running this command (the dispatcher hands it over: `core.lib`, `core.data`), instead of searching."""
    global _core
    lib, data = getattr(core_obj, "lib", None), getattr(core_obj, "data", None)
    if lib and data and (Path(data) / "palettes.json").is_file():
        _core = _load(lib, data)
    return _core


def core(refresh=False):
    """material-boot-core's modules and shared data as one object: .mgrub .mgoverrides .mgcustom .mgscenes .pkg. Raises CoreNotFound with the reason."""
    global _core
    if _core is not None and not refresh:
        return _core
    tried = []
    for lib, data in candidates():
        if (lib / "material_boot/scenes.py").is_file() and (data / "palettes.json").is_file():
            _core = _load(lib, data)
            return _core
        tried.append(f"{lib} + {data}")
    raise CoreNotFound(
        "material-boot-core is not installed (or its shared data is not built: `material-boot core apply`): looked in "
        + ", ".join(tried or ["nothing (set MATERIAL_LIB)"])
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
