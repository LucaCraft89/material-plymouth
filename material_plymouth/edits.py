"""Pure text edits of the files that decide whether Plymouth runs: the kernel command line and the mkinitcpio hooks. No I/O: text in, (new text, what
was added) out, so each is tested on its own and an undo only ever removes what the edit added."""

import re

WANT = ("quiet", "splash")
SPLASH_ALIASES = {
    "splash": ("splash", "rhgb")
}  # Plymouth starts for either word: Fedora's `rhgb` is as good as `splash`


def _missing(tokens, want=WANT):
    have = set(tokens)
    return [w for w in want if not any(a in have for a in SPLASH_ALIASES.get(w, (w,)))]


def tokens_missing(cmdline, want=WANT):
    """Which of the wanted words a command line lacks."""
    return _missing(cmdline.split(), want)


_VAR = re.compile(
    r"^(?P<pre>\s*GRUB_CMDLINE_LINUX_DEFAULT\s*=\s*)(?P<q>[\"']?)(?P<val>.*?)(?P=q)(?P<post>\s*(?:#.*)?)$", re.M
)


def grub_default(text, want=WANT):
    """/etc/default/grub: add the missing words to GRUB_CMDLINE_LINUX_DEFAULT (the variable is appended when the file has none). Returns (text, added)."""
    m = _VAR.search(text)
    if not m:
        add = list(want)
        return text.rstrip("\n") + f'\nGRUB_CMDLINE_LINUX_DEFAULT="{" ".join(add)}"\n', add
    added = _missing(m.group("val").split(), want)
    if not added:
        return text, []
    val = (m.group("val") + " " + " ".join(added)).strip()
    q = m.group("q") or '"'
    return text[: m.start()] + f"{m.group('pre')}{q}{val}{q}{m.group('post')}" + text[m.end() :], added


def grub_default_undo(text, added):
    """Remove exactly the words an edit added (and only from the variable it edited)."""
    m = _VAR.search(text)
    if not m or not added:
        return text
    drop = list(added)
    kept = []
    for t in m.group("val").split():
        if t in drop:
            drop.remove(t)  # one occurrence per added word: a word the user also had before stays
            continue
        kept.append(t)
    q = m.group("q") or '"'
    return text[: m.start()] + f"{m.group('pre')}{q}{' '.join(kept)}{q}{m.group('post')}" + text[m.end() :]


def one_line(text, want=WANT):
    """/etc/kernel/cmdline: one line of words. Returns (text, added)."""
    added = _missing(text.split(), want)
    if not added:
        return text, []
    return text.rstrip("\n") + " " + " ".join(added) + "\n", added


def one_line_undo(text, added):
    drop, kept = list(added), []
    for t in text.split():
        if t in drop:
            drop.remove(t)
            continue
        kept.append(t)
    return " ".join(kept) + "\n"


_GRUBBY_ARGS = re.compile(r'^args="(.*)"$', re.M)


def grubby_missing(info, want=WANT):
    """From `grubby --info=ALL`: the words missing from at least one entry (grubby adds them to every entry; an entry that has them is left alone)."""
    miss = []
    for m in _GRUBBY_ARGS.finditer(info):
        for w in _missing(m.group(1).split(), want):
            if w not in miss:
                miss.append(w)
    return miss


_HOOKS = re.compile(r"^(?P<pre>\s*HOOKS\s*=\s*[(\"'])(?P<val>[^)\"']*)(?P<post>[)\"'].*)$", re.M)


def mkinitcpio_hooks(text):
    """/etc/mkinitcpio.conf: put `plymouth` after udev (after systemd in a systemd-based hook list, after base without either), before any encrypt hook.
    Returns (text, added)."""
    m = _HOOKS.search(text)
    if not m:
        return text, False
    hooks = m.group("val").split()
    if "plymouth" in hooks:
        return text, False
    for anchor in ("udev", "systemd", "base"):
        if anchor in hooks:
            hooks.insert(hooks.index(anchor) + 1, "plymouth")
            break
    else:
        hooks.insert(0, "plymouth")
    return text[: m.start()] + m.group("pre") + " ".join(hooks) + m.group("post") + text[m.end() :], True


def mkinitcpio_hooks_undo(text):
    m = _HOOKS.search(text)
    if not m:
        return text
    hooks = [h for h in m.group("val").split() if h != "plymouth"]
    return text[: m.start()] + m.group("pre") + " ".join(hooks) + m.group("post") + text[m.end() :]
