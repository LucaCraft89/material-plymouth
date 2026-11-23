#!/usr/bin/env python3
"""Step 2 of the QEMU boot tier: boots the kernel and the TEST initramfs that ci/qemu/prepare.sh made (the distro's real kernel, its real Plymouth, our theme
as `plymouth apply` installed it) and looks at the screen.

  usage: boot.py KERNEL INITRD OUTDIR [--timeout SECONDS]

The test hook inside the initramfs (ci/qemu/mgtest-hook.sh) prints MGTEST markers on the serial port; this driver reacts to them:
  ready     plymouthd runs in the initramfs
  splash    three screenshots a second apart: not blank, and something moves
  prompt    a disk-password prompt is on screen (photographed empty), then "hunter2" is typed through QEMU's keyboard and photographed (it must differ), then
            Enter: the hook prints answer=hunter2, so the keys really reached Plymouth's asker
  shutdown  Plymouth in shutdown mode shows its screen (not blank, not the boot splash)
Screenshots (PNG) and the serial log are written to OUTDIR. Exit 0 only when every check passed.
Uses KVM when /dev/kvm exists, else TCG (slow: the first marker can take a minute or two)."""

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import check_frames  # noqa: E402

FAILED = []


def check(ok, what, detail=""):
    print(("PASS  " if ok else "FAIL  ") + what + (f"\n        {detail}" if detail and not ok else ""), flush=True)
    if not ok:
        FAILED.append(what)
    return ok


class Qmp:
    def __init__(self, path, timeout=60):
        self.s = socket.socket(socket.AF_UNIX)
        end = time.time() + timeout
        while True:
            try:
                self.s.connect(path)
                break
            except OSError:
                if time.time() > end:
                    raise
                time.sleep(0.3)
        self.f = self.s.makefile("rw")
        self.f.readline()  # greeting
        self.cmd("qmp_capabilities")

    def cmd(self, name, **args):
        self.f.write(json.dumps({"execute": name, "arguments": args}) + "\n")
        self.f.flush()
        while True:
            line = self.f.readline()
            if not line:
                raise RuntimeError("QMP closed")
            msg = json.loads(line)
            if "return" in msg or "error" in msg:
                return msg

    def shot(self, png):
        ppm = tempfile.mktemp(suffix=".ppm")
        r = self.cmd("screendump", filename=ppm)
        if "error" in r:
            raise RuntimeError(r["error"])
        for _ in range(50):
            if os.path.exists(ppm) and os.path.getsize(ppm) > 100:
                break
            time.sleep(0.1)
        time.sleep(0.2)
        Image.open(ppm).convert("RGB").save(png)
        os.unlink(ppm)
        return Image.open(png).convert("RGB")

    def type(self, text):
        for ch in text:
            key = "ret" if ch == "\n" else ch
            self.cmd("send-key", keys=[{"type": "qcode", "data": key}], **{"hold-time": 60})
            time.sleep(0.15)

    def key(self, name):
        self.cmd("send-key", keys=[{"type": "qcode", "data": name}], **{"hold-time": 60})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kernel")
    ap.add_argument("initrd")
    ap.add_argument("out")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--append", default="", help="more kernel command line words (debugging)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    qmp_path, ser_path = str(tmp / "qmp"), str(tmp / "ser")
    w, h = a.size.split("x")
    accel = ["-accel", "kvm", "-cpu", "host"] if os.path.exists("/dev/kvm") else ["-accel", "tcg", "-cpu", "max"]
    cmd = [
        "qemu-system-x86_64",
        *accel,
        "-smp",
        "2",
        "-m",
        "2048",
        "-kernel",
        a.kernel,
        "-initrd",
        a.initrd,
        "-append",
        "console=tty0 quiet splash plymouth.enable=1 rd.plymouth=1 panic=-1 rd.retry=1 root=/dev/null " + a.append,
        "-device",
        f"VGA,xres={w},yres={h}",
        "-display",
        "none",
        "-qmp",
        f"unix:{qmp_path},server=on,wait=off",
        "-chardev",
        f"socket,id=ser,path={ser_path},server=on,wait=off",
        "-serial",
        "chardev:ser",
        "-no-reboot",
    ]
    print("accelerator:", accel[1], flush=True)
    qemu = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    log = open(out / "serial.log", "w")
    try:
        q = Qmp(qmp_path)
        ser = socket.socket(socket.AF_UNIX)
        for _ in range(100):
            try:
                ser.connect(ser_path)
                break
            except OSError:
                time.sleep(0.2)
        ser.settimeout(5)
        buf, seen, frames = "", {}, {}
        end = time.time() + a.timeout
        start = time.time()
        while time.time() < end and "done" not in seen and qemu.poll() is None:
            try:
                data = ser.recv(4096).decode("utf8", "replace")
            except socket.timeout:
                data = ""
            if data:
                log.write(data)
                log.flush()
                buf += data
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line.startswith("MGTEST "):
                    continue
                word = line.split()[1]
                seen[word.split("=")[0]] = line
                print(f"  [{time.time() - start:5.0f}s] {line}", flush=True)
                if word == "ready":
                    check(re.search(r"plymouthd=\d+", line) is not None, "plymouthd runs in the initramfs", line)
                elif word == "splash":
                    for i in range(3):
                        frames[f"splash-{i + 1}"] = q.shot(out / f"splash-{i + 1}.png")
                        time.sleep(1)
                elif word == "prompt":
                    time.sleep(1)
                    frames["prompt-empty"] = q.shot(out / "prompt-1-empty.png")
                    q.type("hunter2")
                    time.sleep(1)
                    frames["prompt-typed"] = q.shot(out / "prompt-2-typed.png")
                    q.key("backspace")
                    q.key("backspace")
                    time.sleep(1)
                    frames["prompt-erased"] = q.shot(out / "prompt-3-erased.png")
                    q.type("xx")
                    q.key("ret")
                elif word == "shutdown":
                    time.sleep(1)
                    frames["shutdown"] = q.shot(out / "shutdown.png")
        try:
            q.shot(out / "final.png")  # whatever is on screen at the end: the first thing to look at when a run fails
        except Exception as e:  # QEMU may already be gone after the test's own power-off
            print("no final screenshot:", e)
        got = len(frames)
        print(f"{got} screenshots, markers: {sorted(seen)}", flush=True)
    finally:
        qemu.kill()
        log.close()

    check(
        "ready" in seen,
        "the test initramfs booted and ran its hook",
        f"markers: {sorted(seen)}; qemu: {(qemu.stderr.read() or '')[-500:]}",
    )
    if "ready" not in seen:
        return 1

    # ---- plymouthd must be the same process all the way to the prompt (a crash prints a backtrace on screen: not blank, and it changes, so the pictures alone
    # would call it a pass; found when a missing label plugin made Plymouth 26 crash on any script theme)
    def pid(word):
        m = re.search(r"plymouthd=(\d+)", seen.get(word, ""))
        return m.group(1) if m else None

    first = pid("ready")
    check(
        bool(first) and pid("splash") == first and pid("prompt") == first,
        "plymouthd did not crash or restart before the prompt",
        f"ready={first} splash={pid('splash')} prompt={pid('prompt')}",
    )
    check(bool(pid("shutdown")), "plymouthd runs in shutdown mode", seen.get("shutdown", "no marker"))
    # ---- what is on screen
    s = [frames.get(f"splash-{i}") for i in (1, 2, 3)]
    if all(s):
        probs = check_frames.check(
            [str(out / f"splash-{i}.png") for i in (1, 2, 3)], size=(int(w), int(h)), moving=True
        )
        check(not probs, "boot splash: right size, drawn, and it moves", "; ".join(probs))
    else:
        check(False, "boot splash screenshots were taken")
    if all(s):
        px = s[1].getdata()
        black = sum(1 for v in px if v == (0, 0, 0)) / (s[1].width * s[1].height)
        check(black < 0.3, f"the splash is the theme's background, not a black text screen ({black:.0%} pure black)")

    def black_share(im):
        return sum(1 for v in im.getdata() if v == (0, 0, 0)) / (im.width * im.height)

    # a text screen (an emergency shell, a crash dump) is nearly all pure black; every themed frame must not be
    for name in ("prompt-empty", "prompt-typed", "prompt-erased", "shutdown"):
        if name in frames:
            check(
                black_share(frames[name]) < 0.3,
                f"{name}: the theme is on screen, not a black text screen ({black_share(frames[name]):.0%} pure black)",
            )
    if "prompt-empty" in frames:
        p0, p1, p2 = frames["prompt-empty"], frames.get("prompt-typed"), frames.get("prompt-erased")
        check(check_frames.changed(s[2] or p0, p0), "the password prompt looks different from the boot splash")
        check(p1 is not None and check_frames.changed(p0, p1), "typing shows dots (the screen changed after 'hunter2')")
        check(
            p2 is not None and p1 is not None and check_frames.changed(p1, p2),
            "backspace removes dots (the screen changed again)",
        )
        check(
            seen.get("answer", "").endswith("answer=huntexx"),
            "the typed password reached the asker (hunter2, two backspaces, xx = huntexx)",
            seen.get("answer", "no answer marker"),
        )
    else:
        check(False, "the password prompt was photographed", f"markers: {sorted(seen)}")
    if "shutdown" in frames:
        probs = check_frames.check([str(out / "shutdown.png")], size=(int(w), int(h)))
        check(not probs, "shutdown mode shows a screen (not blank)", "; ".join(probs))
        check(
            s[0] is not None and check_frames.changed(s[0], frames["shutdown"]),
            "the shutdown screen differs from the boot splash",
        )
    else:
        check(False, "the shutdown screen was photographed", f"markers: {sorted(seen)}")
    print()
    print("RESULT: " + ("FAIL: " + "; ".join(FAILED) if FAILED else "all checks passed"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
