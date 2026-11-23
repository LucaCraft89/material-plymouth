"""`material-grub plymouth ...`: the command-line front end of this part, run by material-grub's plugin dispatcher (docs/plugins.md in material-grub).

    apply [--yes] [--dry-run] [--if-changed] [--no-cmdline]   render the theme, install it, make it the default, rebuild the initramfs (undone on any failure)
    remove [--yes] [--dry-run]                                 take it all out again
    status [--json]                                            what is installed
    preview SCREEN FILE.png [--style S] [--motion M] [--bar B] [--size WxH]  a still of the boot, password or shutdown screen (nothing is installed)
    build DIR [--style S] [--motion M] [--bar B] [--size WxH]  render the theme into DIR only (to look at it; nothing is installed)

Settings come from /etc/material-grub.conf and overrides.json, shared with the GRUB theme. `--root DIR` works on a staged tree (tests, packaging).
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from . import __version__, adapter, apply, theme
from .system import System


def _parser():
    p = argparse.ArgumentParser(prog="material-grub plymouth", description="The Material Plymouth boot splash.")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("apply", help="render, install and enable the theme")
    a.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="do not ask before changing the kernel command line or the mkinitcpio hooks",
    )
    a.add_argument("--dry-run", action="store_true", help="say what would be done, change nothing")
    a.add_argument(
        "--if-changed",
        action="store_true",
        help="do nothing (and rebuild nothing) when the look is the one already installed",
    )
    a.add_argument(
        "--no-cmdline", action="store_true", help="never edit the kernel command line (you add 'splash' yourself)"
    )
    r = sub.add_parser("remove", help="take the theme out again")
    r.add_argument("--yes", "-y", action="store_true")
    r.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("status", help="what is installed")
    s.add_argument("--json", action="store_true")
    b = sub.add_parser("build", help="render the theme into a directory, install nothing")
    b.add_argument("dir")
    b.add_argument("--style", choices=("rail", "clean", "list", "split"))
    b.add_argument("--motion", choices=("full", "calm", "off"))
    b.add_argument("--bar", choices=("indeterminate", "progress"))
    b.add_argument("--size", help="WxH of the screen (default: the display's)")
    pv = sub.add_parser("preview", help="a still picture of what the theme shows (boot, password or shutdown)")
    pv.add_argument("screen", choices=("boot", "password", "shutdown"))
    pv.add_argument("file")
    pv.add_argument("--style", choices=("rail", "clean", "list", "split"))
    pv.add_argument("--motion", choices=("full", "calm", "off"))
    pv.add_argument("--bar", choices=("indeterminate", "progress"))
    pv.add_argument("--size", help="WxH of the picture (default: the display's)")
    pv.add_argument("--root", default="", help=argparse.SUPPRESS)
    for x in (a, r, s):
        x.add_argument("--root", default="", help=argparse.SUPPRESS)
    b.add_argument("--root", default="", help=argparse.SUPPRESS)
    return p


def _settings(core, root):
    c = adapter.core()
    conf_path = core.conf_path() if root == "" else str(Path(root) / "etc/material-grub.conf")
    conf = c.mgrub.load_conf(conf_path)
    ov_path = Path(root) / "etc/material-grub/overrides.json" if root else None
    overrides, problems = c.mgoverrides.load(ov_path)
    for pr in problems:
        print(f"material-grub: overrides: {pr}", file=sys.stderr)
    text = (Path(root or "/") / "etc/os-release").read_text() if (Path(root or "/") / "etc/os-release").exists() else ""
    return conf, overrides, adapter.parse_os_release(text)


def _ask(text):
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    try:
        return input(text + " [Y/n] ").strip().lower() not in ("n", "no")
    except EOFError:
        return False


def _print(res, say):
    for m in res.messages:
        say(("  " if res.ok else "  ! ") + m)
    if res.plan and res.status == "dry-run":
        say("Would:")
        for p in res.plan:
            say("  - " + p)


def main(argv, core):
    args = _parser().parse_args(argv)
    say = core.say
    root = getattr(args, "root", "")
    system = System(root)
    if args.cmd == "status":
        st = apply.status(system)
        if args.json:
            say(json.dumps(st, indent=2, default=str))
        else:
            say(f"material-plymouth {__version__}: " + ("installed" if st["installed"] else "not installed"))
            say(f"  default theme : {st['default_theme']}")
            say(f"  script plugin : {st['script_plugin'] or 'NOT FOUND'}")
            say(f"  initramfs tool: {st['initramfs_tool'] or 'NOT FOUND'}")
            if st["state"]:
                say(
                    f"  applied       : {st['state'].get('applied_at')} ({st['state'].get('style')} style, {st['state'].get('size')})"
                )
        return 0
    conf, overrides, osrel = _settings(core, root)
    if args.cmd == "build":
        if args.style:
            conf["STYLE"] = args.style
        size = tuple(int(v) for v in args.size.lower().split("x")) if args.size else apply.detect_resolution(system)
        look = adapter.look(conf, overrides, osrel, height=size[1])
        out = theme.build(
            look,
            size[0],
            size[1],
            args.dir,
            motion=args.motion or conf["PLYMOUTH_MOTION"],
            bar=args.bar or conf["PLYMOUTH_BAR"],
        )
        say(
            f"theme for {look.title} ({out['style']} style, {size[0]}x{size[1]}): {len(out['files'])} files, {out['size'] // 1024} KiB in {args.dir}"
        )
        return 0
    if args.cmd == "preview":
        if args.style:
            conf["STYLE"] = args.style
        size = tuple(int(v) for v in args.size.lower().split("x")) if args.size else apply.detect_resolution(system)
        look = adapter.look(conf, overrides, osrel, height=size[1])
        im = theme.preview(
            look,
            size[0],
            size[1],
            args.screen,
            motion=args.motion or conf["PLYMOUTH_MOTION"],
            bar=args.bar or conf["PLYMOUTH_BAR"],
        )
        im.save(args.file)
        say(f"{args.screen} preview for {look.title} ({size[0]}x{size[1]}) written to {args.file}")
        return 0
    if os.geteuid() != 0 and not root and not getattr(args, "dry_run", False):
        core.elevate(["plymouth", *argv], [f"/{apply.THEMES}", "/var/lib"])
    if args.cmd == "apply":
        regen = (lambda: tuple(_run_ok(system, ["material-grub", "apply"]))) if shutil.which("material-grub") else None
        res = apply.apply(
            system,
            conf,
            overrides,
            osrel,
            yes=args.yes,
            dry_run=args.dry_run,
            if_changed=args.if_changed,
            no_cmdline=args.no_cmdline,
            ask=_ask,
            log=say,
            regen_grub=regen,
        )
    else:
        res = apply.remove(system, yes=args.yes, ask=_ask, log=say, dry_run=args.dry_run)
    _print(res, say)
    if res.status == "rolled-back":
        _report(res)
    return 0 if res.ok else 1


def _run_ok(system, cmd):
    rc, out = system.run(cmd)
    return rc == 0, out.strip()[-500:]


def _report(res):
    """The same box, journal line and `wall` as material-grub's own rollbacks, and last-error for `material-grub doctor`."""
    try:
        c = adapter.core()
        sys.path.insert(0, str(c.bin))
        import mgsafe

        mgsafe.report_failure("the Plymouth theme could not be applied; everything was put back", res.messages[:3])
    except Exception:
        pass
