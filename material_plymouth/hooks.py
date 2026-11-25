"""The hooks of the unified installer and `material-boot core doctor` (plugin API 2, `hook_<name>(ctx)`; docs/plugins.md in material-boot-core).

They are thin: the work is `apply` and `remove`, which are the same functions `material-boot plymouth apply|remove` run, with their backups, their checks of
every rebuilt initramfs and their rollback on any failure.

What the installer means for a boot splash differs from GRUB's theme: choosing the part (`--with plymouth`) is the person asking for it, so it is applied;
a package install (`how == "package"`) is not: it only puts the code in place, and re-applies a theme that was applied before, without touching the kernel
command line, exactly what packaging/package-hook.sh did for the package scriptlets.
"""

import shutil
import subprocess
from pathlib import Path

from . import adapter, apply
from .system import System

SRC = (
    Path(__file__).resolve().parent.parent
)  # the checkout, or this part's directory in a bundle, or the installed copy
PREFIX = "/usr/local"  # a source or bundle install is not a package's: the code goes where `sh packaging/install-tree.sh . / /usr/local` puts it

make_system = System  # tests put a scripted machine here

NOT_ASKED = (
    "the part is installed; turning the boot splash on is your own step, because it rebuilds the initramfs and may edit the kernel command line: "
    "material-boot plymouth apply"
)


def _system(ctx):
    return make_system(ctx.root)


def _share(ctx):
    return Path(ctx.root or "/") / PREFIX.lstrip("/") / "share/material-plymouth"


def _manifest(ctx):
    return Path(ctx.root or "/") / PREFIX.lstrip("/") / "share/material-boot/plugins.d/plymouth.json"


def lay_down(ctx):
    """Put the code and the plugin manifest in place for a source or bundle install (a package has done it; running from the installed copy needs nothing).
    Returns the lines to tell the person."""
    if not _wants_files(ctx):
        return []
    r = subprocess.run(
        ["sh", str(SRC / "packaging/install-tree.sh"), str(SRC), ctx.root or "", PREFIX], capture_output=True, text=True
    )
    if r.returncode:
        raise RuntimeError("could not install the part's files: " + (r.stderr or r.stdout).strip()[-300:])
    return [f"installed the part in {_share(ctx)} and its manifest in {_manifest(ctx).parent}"]


def _current(ctx):
    """The installed copy is this one: every file the same, the manifest in place (an install that changes nothing says so)."""
    share = _share(ctx)
    pairs = [(f, share / "material_plymouth" / f.name) for f in sorted((SRC / "material_plymouth").glob("*.py"))]
    pairs.append((SRC / "bin/mgplugin.py", share / "bin/mgplugin.py"))
    try:
        return _manifest(ctx).is_file() and all(b.read_bytes() == a.read_bytes() for a, b in pairs)
    except OSError:
        return False


def _wants_files(ctx):
    """A source or bundle install with files to install (a checkout or a bundle has packaging/install-tree.sh; an installed copy, a package's or ours, has not)
    that are not there already."""
    return (
        ctx.how != "package"
        and (SRC / "packaging/install-tree.sh").is_file()
        and SRC.resolve() != _share(ctx).resolve()
        and not _current(ctx)
    )


def _would_lay_down(ctx):
    if not _wants_files(ctx):
        return []
    return [f"install the part's files in {_share(ctx)} and its manifest in {_manifest(ctx).parent}"]


def take_away(ctx):
    """The files lay_down put there (never a package's). Returns True when something was removed."""
    gone = False
    if _share(ctx).exists() and ctx.how != "package":
        shutil.rmtree(_share(ctx), ignore_errors=True)
        gone = True
    if _manifest(ctx).exists() and ctx.how != "package":
        _manifest(ctx).unlink()
        gone = True
    return gone


def _settings(ctx):
    from .plugin import _settings as settings

    adapter.attach(
        ctx.core
    )  # the core that is running the installer, with the data it has installed (a bundle's library has none of its own)
    return settings(ctx.core, ctx.root)


def _ask(text):
    from .plugin import _ask

    return _ask(text)


def hook_detect(ctx):
    system = _system(ctx)
    st = apply.status(system)
    applied = bool(st["installed"] or st["recorded"])
    before = ctx.previous.get("version") if isinstance(ctx.previous, dict) else ctx.previous
    version = (st["state"] or {}).get("version") or before
    details = []
    if st["recorded"]:
        s = st["state"] or {}
        details.append(f"the theme is applied ({s.get('style')} style, {s.get('size')}, {s.get('tool')})")
    elif before:
        details.append("the part is installed and the theme is not applied")
    return {
        "found": bool(applied or before),
        "version": version,
        "how": "unknown",
        "layout": "normal",
        "missing": [],
        "details": details,
    }


def hook_plan(ctx):
    system = _system(ctx)
    if ctx.how == "package" and not apply.read_state(system):
        return [NOT_ASKED]
    try:
        conf, overrides, osrel = _settings(ctx)
    except adapter.CoreNotFound:
        # a dry run on a fresh system: the core's shared data is built by this very run, so the theme cannot be planned yet
        return _would_lay_down(ctx) + [
            "render the theme, install it, make it the default theme and rebuild the initramfs (the plan of that needs the core's shared data, which this run builds first)"
        ]
    res = apply.apply(
        system,
        conf,
        overrides,
        osrel,
        dry_run=True,
        if_changed=True,
        no_cmdline=bool(ctx.options.get("no-cmdline")) or ctx.how == "package",
        log=lambda *_a: None,
    )
    if not res.ok:
        raise RuntimeError("; ".join(res.messages))
    return _would_lay_down(ctx) + (list(res.plan) or list(res.messages))


def hook_install(ctx):
    system = _system(ctx)
    if ctx.dry_run:
        return {"changed": False, "notes": hook_plan(ctx)}
    package = ctx.how == "package"
    notes = lay_down(ctx)
    try:
        if package and not apply.read_state(system):
            return {
                "changed": bool(notes),
                "notes": notes + [NOT_ASKED],
            }  # installed, not applied: the part is still recorded
        conf, overrides, osrel = _settings(ctx)
        res = apply.apply(
            system,
            conf,
            overrides,
            osrel,
            yes=ctx.yes,
            if_changed=True,
            no_cmdline=bool(ctx.options.get("no-cmdline")) or package,
            ask=_ask,
            log=lambda *_a: None,
        )
        if not res.ok:
            _report(res)
            raise RuntimeError("; ".join(res.messages))
    except BaseException:
        if notes:  # a part that failed is not left half installed: what this run put there goes again
            take_away(ctx)
        raise
    return {"changed": res.status == "applied" or bool(notes), "notes": notes + res.messages}


def hook_verify(ctx):
    system = _system(ctx)
    if not apply.read_state(system):
        return []  # not applied: nothing to be right or wrong about
    st = apply.status(system)
    problems = []
    if not st["installed"]:
        problems.append("the theme was applied but its directory is missing")
    if st["default_theme"] != "material":
        problems.append(f"the default Plymouth theme is {st['default_theme']!r}, not 'material'")
    return problems


def hook_uninstall(ctx):
    system = _system(ctx)
    theme = bool(apply.read_state(system) or system.p(apply.THEME_DIR).is_dir())
    if ctx.dry_run:
        return {
            "changed": False,
            "notes": ["the theme would be taken out and the initramfs rebuilt without it"] if theme else [],
        }
    notes = []
    if theme:
        res = apply.remove(system, yes=True, ask=_ask, log=lambda *_a: None)
        if not res.ok:
            raise RuntimeError("; ".join(res.messages))
        notes = res.messages
    return {"changed": take_away(ctx) or theme, "notes": notes}


def hook_doctor(ctx):
    system = _system(ctx)
    st = apply.status(system)
    out = [("ok" if st["script_plugin"] else "fail", f"Plymouth script plugin: {st['script_plugin'] or 'NOT FOUND'}")]
    out.append(
        (
            "ok" if st["label_plugin"] else "warn",
            f"Plymouth label plugin: {st['label_plugin'] or 'not found (the daemon can crash without it on Plymouth 26)'}",
        )
    )
    out.append(("ok" if st["initramfs_tool"] else "fail", f"initramfs tool: {st['initramfs_tool'] or 'NOT FOUND'}"))
    if st["recorded"]:
        s = st["state"] or {}
        out.append(("ok", f"theme applied {s.get('applied_at')} ({s.get('style')} style, {s.get('size')})"))
        if not st["installed"]:
            out.append(("fail", "the theme directory is missing although the theme was applied"))
        if st["default_theme"] != "material":
            out.append(("warn", f"the default theme is {st['default_theme']!r}, not 'material'"))
    else:
        out.append(("info", "the theme is not applied (material-boot plymouth apply)"))
    return out


def _report(res):
    """The same box as material-grub's own rollbacks when it is installed (see plugin._report)."""
    if res.status == "rolled-back":
        from .plugin import _report as report

        report(res)
