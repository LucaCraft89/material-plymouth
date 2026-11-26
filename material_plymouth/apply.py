"""Apply and remove the theme: render it, install it, make it the default, make sure Plymouth runs, rebuild every initramfs and check them.

The initramfs is on the boot path, so every step is undoable and the order is: back everything up first, change, verify, and on ANY failure put it all back
(the files, the default theme, the images). A failed apply leaves the machine as it was; a successful one records what it changed so `remove` undoes exactly that.
All access to the machine goes through `system.System` (a fake one in the tests), all text edits through `edits`.
"""

import hashlib
import json
import re
import shutil
import time
from pathlib import Path

from . import __version__, adapter, edits, theme
from .system import THEME_NAME, THEMES

STATE = "var/lib/material-plymouth/state.json"
BACKUPS = "var/backups/material-plymouth"
THEME_DIR = f"/{THEMES}/{THEME_NAME}"
THEME_FILE = f"{THEME_DIR}/{THEME_NAME}.plymouth"
GRUB_DEFAULT, KERNEL_CMDLINE, MKINITCPIO = "/etc/default/grub", "/etc/kernel/cmdline", "/etc/mkinitcpio.conf"
KEEP_BACKUPS = 3


def must(result):
    """A (ok, message) answer of a system helper as an exception when it failed, so an undo step that fails is reported instead of passing silently."""
    ok, msg = result
    if not ok:
        raise RuntimeError(msg or "failed")
    return msg


class Result:
    def __init__(self, status, messages=None, plan=None, state=None):
        self.status, self.messages, self.plan, self.state = status, list(messages or []), list(plan or []), state

    @property
    def ok(self):
        return self.status in ("applied", "unchanged", "dry-run", "removed", "nothing-to-do")

    def __repr__(self):
        return f"Result({self.status!r}, {self.messages!r})"


# ---------------------------------------------------------------- state and backups
def read_state(system):
    try:
        d = json.loads(system.read(STATE) or "")
        return d if isinstance(d, dict) else None
    except ValueError:
        return None


def write_state(system, data):
    system.write(STATE, json.dumps(data, indent=2, sort_keys=True) + "\n")


class Backup:
    """A directory with copies of what a run is about to change: files (the original is restored on a rollback; a file that did not exist is removed)
    and the initramfs images."""

    def __init__(self, system, stamp):
        self.sys = system
        self.dir = system.p(f"{BACKUPS}/{stamp}")
        self.files = {}  # path -> saved copy, or None when it did not exist

    def make(self):
        (self.dir / "files").mkdir(parents=True, exist_ok=True)
        (self.dir / "images").mkdir(parents=True, exist_ok=True)

    def save(self, path):
        path = str(path)
        if path in self.files:
            return
        src = self.sys.p(path)
        if src.is_file():
            dst = self.dir / "files" / path.lstrip("/").replace("/", "__")
            shutil.copy2(src, dst)
            self.files[path] = dst
        else:
            self.files[path] = None

    def restore_files(self):
        failed = []
        for path, saved in self.files.items():
            dst = self.sys.p(path)
            try:
                if saved is None:
                    dst.unlink(missing_ok=True) if hasattr(dst, "unlink") else None
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(saved, dst)
            except OSError as e:
                failed.append(f"{path}: {e}")
        return failed

    def save_images(self, images):
        for img in images:
            shutil.copy2(img, self.dir / "images" / Path(img).name)

    def restore_images(self, images):
        failed = []
        for img in images:
            try:
                shutil.copy2(self.dir / "images" / Path(img).name, img)
            except OSError as e:
                failed.append(f"{img}: {e}")
        return failed


def prune(system):
    base = system.p(BACKUPS)
    if base.is_dir():
        for old in sorted(d for d in base.iterdir() if d.is_dir())[:-KEEP_BACKUPS]:
            shutil.rmtree(old, ignore_errors=True)


# ---------------------------------------------------------------- what to build for
def detect_resolution(system):
    """The native size of the first connected display (the kernel's own list), else GRUB_GFXMODE, else 1920x1080."""
    base = system.p("sys/class/drm")
    try:
        for c in sorted(base.iterdir()):
            if (c / "status").read_text().strip() == "connected":
                m = re.match(r"(\d+)x(\d+)", (c / "modes").read_text().strip().splitlines()[0])
                if m:
                    return int(m[1]), int(m[2])
    except (OSError, IndexError):
        pass
    m = re.search(r"^GRUB_GFXMODE=\"?(\d+)x(\d+)", system.read(GRUB_DEFAULT, ""), re.M)
    return (int(m[1]), int(m[2])) if m else (1920, 1080)


def tree_hash(path):
    """A fingerprint of a theme directory: names and contents, in order."""
    h = hashlib.sha256()
    for f in sorted(Path(path).rglob("*")):
        if f.is_file():
            h.update(str(f.relative_to(path)).encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


def render(system, conf, overrides, osrel, W, H, out):
    """Render the theme for these settings into `out` (its .plymouth file points at the installed place). Returns (look, build info)."""
    look = adapter.look(conf, overrides, osrel, height=H)
    info = theme.build(look, W, H, out, motion=conf["PLYMOUTH_MOTION"], bar=conf["PLYMOUTH_BAR"], install_dir=THEME_DIR)
    return look, info


# ---------------------------------------------------------------- the config edits that make Plymouth run
def plan_edits(system, no_cmdline=False, tool=None):
    """[(kind, words/flag)] of what has to change: the kernel command line (grubby, /etc/kernel/cmdline or /etc/default/grub) and the mkinitcpio hook."""
    plan = []
    if not no_cmdline:
        if system.which("grubby"):
            rc, info = system.run(["grubby", "--info=ALL"])
            miss = edits.grubby_missing(info) if rc == 0 else []
            if miss:
                plan.append(("grubby", miss))
            kc = system.read(KERNEL_CMDLINE)
            if kc is not None:
                _t, added = edits.one_line(kc)
                if added:
                    plan.append(("kernel-cmdline", added))
        elif system.exists(GRUB_DEFAULT):
            _t, added = edits.grub_default(system.read(GRUB_DEFAULT))
            if added:
                plan.append(("grub-default", added))
    if tool == "mkinitcpio" and system.exists(MKINITCPIO):
        _t, added = edits.mkinitcpio_hooks(system.read(MKINITCPIO))
        if added:
            plan.append(("mkinitcpio-hook", ["plymouth"]))
    return plan


def apply_edits(system, plan, backup):
    """Do the planned edits. Returns the record of what was added (for the undo). Raises on a failure: the caller rolls back."""
    done = {}
    for kind, words in plan:
        if kind == "grubby":
            for e in sorted(system.p("boot/loader/entries").glob("*.conf")):
                backup.save("/" + str(e.relative_to(system.root)))
            rc, out = system.run(["grubby", "--update-kernel=ALL", "--args", " ".join(words)])
            if rc != 0:
                raise RuntimeError(f"grubby failed: {out.strip()}")
        elif kind == "kernel-cmdline":
            backup.save(KERNEL_CMDLINE)
            system.write(KERNEL_CMDLINE, edits.one_line(system.read(KERNEL_CMDLINE))[0])
        elif kind == "grub-default":
            backup.save(GRUB_DEFAULT)
            system.write(GRUB_DEFAULT, edits.grub_default(system.read(GRUB_DEFAULT))[0])
        elif kind == "mkinitcpio-hook":
            backup.save(MKINITCPIO)
            system.write(MKINITCPIO, edits.mkinitcpio_hooks(system.read(MKINITCPIO))[0])
        done[kind] = list(words)
    return done


def undo_edits(system, done):
    """Take back what a previous apply added, and only that. Returns a list of problems."""
    problems = []
    for kind, words in done.items():
        try:
            if kind == "grubby":
                rc, out = system.run(["grubby", "--update-kernel=ALL", "--remove-args", " ".join(words)])
                if rc != 0:
                    problems.append(f"grubby: {out.strip()}")
            elif kind == "kernel-cmdline" and system.exists(KERNEL_CMDLINE):
                system.write(KERNEL_CMDLINE, edits.one_line_undo(system.read(KERNEL_CMDLINE), words))
            elif kind == "grub-default" and system.exists(GRUB_DEFAULT):
                system.write(GRUB_DEFAULT, edits.grub_default_undo(system.read(GRUB_DEFAULT), words))
            elif kind == "mkinitcpio-hook" and system.exists(MKINITCPIO):
                system.write(MKINITCPIO, edits.mkinitcpio_hooks_undo(system.read(MKINITCPIO)))
        except OSError as e:
            problems.append(f"{kind}: {e}")
    return problems


# ---------------------------------------------------------------- the initramfs
def rebuild(system, tool):
    """Rebuild every initramfs. Returns (ok, output)."""
    cmd, _lister = __import__("material_plymouth.system", fromlist=["TOOLS"]).TOOLS[tool]
    rc, out = system.run(cmd)
    return rc == 0, out.strip()[-2000:]


def verify_images(system, tool, since):
    """Check the images the rebuild wrote (newer than `since`): each must hold the theme, the script plugin and its pictures. Returns (problems, checked, unverified)."""
    from .system import TOOLS

    lister = TOOLS[tool][1]
    problems, checked, unverified = [], [], []
    for img in system.images():
        if img.stat().st_mtime < since:
            continue  # an image of a kernel that is gone: not rebuilt, not ours
        if img.stat().st_size < 1024:
            problems.append(f"{img.name}: empty")
            continue
        rc, out = system.run(lister + [str(img)])
        if rc == 127:
            unverified.append(img.name)
            continue
        if rc != 0:
            problems.append(f"{img.name}: cannot list its contents ({out.strip()[:200]})")
            continue
        missing = [
            what
            for what, ok in (
                ("the theme script", f"themes/{THEME_NAME}/{THEME_NAME}.script" in out),
                ("the script plugin", "script.so" in out),
                ("its pictures", len(re.findall(rf"themes/{THEME_NAME}/\S+\.png", out)) >= 5),
            )
            if not ok
        ]
        (problems if missing else checked).append(f"{img.name}: missing {', '.join(missing)}" if missing else img.name)
    if not checked and not problems and not unverified:
        problems.append("the rebuild wrote no initramfs image")
    return problems, checked, unverified


# ---------------------------------------------------------------- apply
def free_space_problem(system, images):
    need = sum(i.stat().st_size for i in images) * 12 // 10 + 5_000_000
    base = system.p(BACKUPS)
    base.mkdir(parents=True, exist_ok=True)
    free = system.free_bytes(BACKUPS)
    return (
        None
        if free >= need
        else f"not enough room for the backups in /{BACKUPS}: {need // 1_000_000} MB needed, {free // 1_000_000} MB free"
    )


def apply(
    system,
    conf,
    overrides,
    osrel,
    *,
    yes=False,
    dry_run=False,
    if_changed=False,
    no_cmdline=False,
    ask=None,
    log=print,
    regen_grub=None,
    size=None,
    stamp=None,
):
    """Render, install and enable the theme. Returns a Result; on any failure everything is put back (status 'rolled-back') or nothing was touched ('refused')."""
    say = log
    if conf.get("PLYMOUTH") == "off":
        return remove(system, yes=yes, ask=ask, log=log, dry_run=dry_run, why="PLYMOUTH=off")
    plugin, tool = system.script_plugin(), system.initramfs_tool()
    if not plugin:
        return Result(
            "refused",
            [
                "Plymouth's script plugin is not installed (Fedora, openSUSE: plymouth-plugin-script; Debian, Ubuntu: plymouth; Arch: plymouth)"
            ],
        )
    if not tool:
        return Result("refused", ["no initramfs tool found (dracut, update-initramfs or mkinitcpio)"])
    W, H = size or detect_resolution(system)
    themes = system.p(THEMES)
    themes.mkdir(parents=True, exist_ok=True)
    stage = themes / f".{THEME_NAME}.new"
    shutil.rmtree(stage, ignore_errors=True)
    try:
        look, info = render(system, conf, overrides, osrel, W, H, stage)
    except Exception as e:
        shutil.rmtree(stage, ignore_errors=True)
        return Result("refused", [f"could not render the theme: {type(e).__name__}: {e}"])
    digest = tree_hash(stage)
    old = read_state(system)
    if if_changed and old and old.get("hash") == digest and system.p(THEME_DIR).is_dir():
        shutil.rmtree(stage, ignore_errors=True)
        return Result("unchanged", ["the look has not changed: nothing to do"], state=old)
    plan = [
        f"install the theme ({info['style']} style, {W}x{H}, {info['size'] // 1024} KiB) in {THEME_DIR}",
        "make it the default Plymouth theme",
    ]
    ed = plan_edits(system, no_cmdline, tool)
    for kind, words in ed:
        plan.append(
            f"add {' '.join(words)} to the kernel command line ({kind})"
            if kind != "mkinitcpio-hook"
            else "add the plymouth hook to /etc/mkinitcpio.conf"
        )
    plan.append(f"rebuild every initramfs with {tool} and check each one")
    if dry_run:
        shutil.rmtree(stage, ignore_errors=True)
        return Result("dry-run", plan=plan)
    if ed and not yes:
        answer = ask(plan_text(plan[2:-1])) if ask else False
        if not answer:
            say(
                "the command line and hook edits were declined: the theme is installed, but Plymouth will not start until the kernel is told to (add 'splash')"
            )
            ed = []
    images = system.images()
    problem = free_space_problem(system, images)
    if problem:
        shutil.rmtree(stage, ignore_errors=True)
        return Result("refused", [problem])

    # ---- the change, with an undo for every step
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    bk = Backup(system, stamp)
    bk.make()
    bk.save_images(images)
    undo = []
    t0 = time.time()
    done_edits = {}
    prev_default = system.default_theme()
    failure = None
    try:
        # 1. the theme directory: the old one is moved aside, the new one renamed in
        final, aside = system.p(THEME_DIR), system.p(f"{BACKUPS}/{stamp}/previous-theme")
        had = final.exists()
        if had:
            shutil.move(str(final), str(aside))
        stage.rename(final)
        undo.append(
            (
                "the theme directory",
                lambda: (shutil.rmtree(final, ignore_errors=True), had and shutil.move(str(aside), str(final))),
            )
        )
        # 2. the default theme
        ok, msg = system.set_default_theme(THEME_NAME, THEME_FILE)
        if not ok:
            raise RuntimeError(f"could not make it the default theme: {msg}")
        undo.append(("the default theme", lambda: must(system.reset_default_theme(prev_default, THEME_FILE))))
        # 3. the command line and the hook
        if ed:
            done_edits = apply_edits(system, ed, bk)
            undo.append(
                (
                    "the command line and hook edits",
                    lambda: (
                        bk.restore_files(),
                        "grubby" in done_edits and undo_edits(system, {"grubby": done_edits["grubby"]}),
                    ),
                )
            )
            if "grub-default" in done_edits and regen_grub:
                ok, msg = regen_grub()
                if not ok:
                    raise RuntimeError(f"could not regenerate grub.cfg: {msg}")
        # 4. the initramfs
        undo.append(("the initramfs images", lambda: bk.restore_images(images)))
        ok, out = rebuild(system, tool)
        if not ok:
            raise RuntimeError(f"{tool} failed: {out}")
        problems, checked, unverified = verify_images(system, tool, t0 - 2)
        if problems:
            raise RuntimeError("the rebuilt initramfs is not right: " + "; ".join(problems))
    except Exception as e:
        failure = f"{type(e).__name__}: {e}" if not isinstance(e, RuntimeError) else str(e)
    if failure:
        notes = []
        for name, fn in reversed(undo):
            try:
                fn()
            except Exception as e:  # keep going: a failed undo must not stop the others
                notes.append(f"could not put back {name}: {e}")
        shutil.rmtree(stage, ignore_errors=True)
        return Result("rolled-back", [failure, "everything was put back as it was"] + notes)
    state = {
        "version": __version__,
        "hash": digest,
        "applied_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "tool": tool,
        "style": info["style"],
        "size": [W, H],
        "default_before": prev_default,
        "edits": {**(old or {}).get("edits", {}), **done_edits},
        "backup": f"/{BACKUPS}/{stamp}",
        "images": checked,
        "unverified": unverified,
    }
    write_state(system, state)
    prune(system)
    msgs = [f"the theme is installed and every initramfs was rebuilt and checked ({len(checked)} image(s))"]
    if unverified:
        msgs.append(f"could not list the contents of: {', '.join(unverified)} (the lister is not installed)")
    return Result("applied", msgs, plan=plan, state=state)


def plan_text(items):
    return "To make Plymouth start, this will:\n  - " + "\n  - ".join(items) + "\nContinue?"


# ---------------------------------------------------------------- remove
def remove(system, *, yes=False, ask=None, log=print, dry_run=False, why="requested", stamp=None):
    """Undo apply: the default theme, the edits it added, the theme directory; rebuild the initramfs (and check it no longer has the theme)."""
    state = read_state(system)
    if not state and not system.p(THEME_DIR).exists():
        return Result("nothing-to-do", ["the Material Plymouth theme is not installed"])
    tool = system.initramfs_tool()
    plan = [
        "go back to the previous default theme",
        "take out what was added for Plymouth ("
        + (", ".join(f"{k}: {' '.join(v)}" for k, v in (state or {}).get("edits", {}).items()) or "nothing")
        + ")",
        f"remove {THEME_DIR}",
        "rebuild every initramfs",
    ]
    if dry_run:
        return Result("dry-run", plan=plan)
    images = system.images()
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S") + "-remove"
    bk = Backup(system, stamp)
    bk.make()
    bk.save_images(images)
    undo = []
    failure = None
    prev = (state or {}).get("default_before")
    final = system.p(THEME_DIR)
    aside = system.p(f"{BACKUPS}/{stamp}/previous-theme")
    try:
        ok, msg = system.reset_default_theme(prev, THEME_FILE)
        undo.append(("the default theme", lambda: must(system.set_default_theme(THEME_NAME, THEME_FILE))))
        if not ok:
            raise RuntimeError(f"could not restore the previous default theme: {msg}")
        edits_done = (state or {}).get("edits", {})
        for path in (GRUB_DEFAULT, KERNEL_CMDLINE, MKINITCPIO):
            bk.save(path)
        for e in sorted(system.p("boot/loader/entries").glob("*.conf")):
            bk.save("/" + str(e.relative_to(system.root)))
        probs = undo_edits(system, edits_done)
        undo.append(("the config edits", bk.restore_files))
        if probs:
            raise RuntimeError("; ".join(probs))
        if final.exists():
            shutil.move(str(final), str(aside))
            undo.append(
                (
                    "the theme directory",
                    lambda: (shutil.rmtree(final, ignore_errors=True), shutil.move(str(aside), str(final))),
                )
            )
        if tool:
            undo.append(("the initramfs images", lambda: bk.restore_images(images)))
            ok, out = rebuild(system, tool)
            if not ok:
                raise RuntimeError(f"{tool} failed: {out}")
    except Exception as e:
        failure = str(e) if isinstance(e, RuntimeError) else f"{type(e).__name__}: {e}"
    if failure:
        notes = []
        for name, fn in reversed(undo):
            try:
                fn()
            except Exception as e:
                notes.append(f"could not put back {name}: {e}")
        return Result("rolled-back", [failure, "everything was put back as it was"] + notes)
    system.p(STATE).unlink(missing_ok=True)
    prune(system)
    return Result("removed", [f"the theme is removed ({why}); the initramfs images were rebuilt without it"])


def status(system):
    """What is installed, as a dict (for `status` and `status --json`)."""
    st = read_state(system)
    tool = system.initramfs_tool()
    return {
        "installed": system.p(THEME_DIR).is_dir(),
        "recorded": bool(st),
        "state": st,
        "default_theme": system.default_theme(),
        "script_plugin": system.script_plugin(),
        "initramfs_tool": tool,
        "images": [i.name for i in system.images()],
    }
