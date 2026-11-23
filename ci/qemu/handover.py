#!/usr/bin/env python3
"""The hand-over: GRUB (the Material theme) -> the kernel -> Plymouth (the Material theme), under UEFI firmware (OVMF), the way a real machine boots.

  usage: handover.py MATERIAL_GRUB_CHECKOUT KERNEL INITRD OS_RELEASE OUTDIR [--size 1280x720]
  needs: qemu-system-x86_64, OVMF, grub-mkimage (with the x86_64-efi modules), Pillow; a material-grub package built with --res <size>.

It builds an ESP directory with GRUB's EFI image, material-grub's own theme for the size, a menu entry titled like the system the initramfs came from, and the
kernel and the test initramfs of ci/qemu/prepare.sh. Then: boot to the GRUB menu (photographed), press Enter, wait for the test hook to report that plymouthd
runs, photograph the splash. Checks: the GRUB menu is the theme at the screen's size; the Plymouth splash is the same size (the mode survived the hand-over:
`gfxpayload=keep`), is the theme and not a text screen, animates, and its background is the GRUB menu's background colour (it is the same scheme on the same
distro: the splash must continue the menu, which is the point of this project). Screenshots and the serial log go to OUTDIR."""

import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import boot  # noqa: E402
import check_frames  # noqa: E402

MODULES = (
    "normal configfile gfxterm gfxmenu png all_video efi_gop video video_fb fat part_gpt part_msdos font echo test true search reboot halt terminal gettext "
    "regexp sleep linux boot"
).split()
OVMF = (
    "/usr/share/OVMF/OVMF_CODE_4M.fd",
    "/usr/share/OVMF/OVMF_CODE.fd",
    "/usr/share/edk2/ovmf/OVMF_CODE.fd",
    "/usr/share/edk2/x64/OVMF_CODE.4m.fd",
    "/usr/share/qemu/OVMF.fd",
)


def have_module(name):
    for d in (
        "/usr/lib/grub/x86_64-efi",
        "/usr/lib64/grub/x86_64-efi",
        "/usr/share/grub2/x86_64-efi",
        "/usr/lib/grub2/x86_64-efi",
    ):
        if os.path.isdir(d):
            return os.path.exists(f"{d}/{name}.mod")
    return True


def osrel(path):
    out = {}
    for line in Path(path).read_text().splitlines():
        m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
        if m:
            out[m[1]] = m[2].strip().strip("\"'")
    return out


def build_tree(mg, kernel, initrd, os_release, size, tree):
    pkg = Path(mg) / "dist/material-grub"
    binp = pkg / "bin"
    title = os_release.get("PRETTY_NAME") or os_release.get("NAME") or "Linux"
    cls = (os_release.get("ID") or "linux").lower()
    (tree / "boot/grub").mkdir(parents=True)
    cfg = f"""set timeout=120
set gfxmode={size}
set gfxpayload=keep
insmod all_video
insmod gfxterm
insmod gfxmenu
insmod png
terminal_output gfxterm
loadfont /boot/grub/themes/material/MG-Label.pf2
loadfont /boot/grub/themes/material/MG-Raw.pf2
set theme=/boot/grub/themes/material/theme.txt
menuentry '{title}' --class {cls} --class gnu-linux --class gnu --class os {{
  linux /vmlinuz console=tty0 quiet splash plymouth.enable=1 rd.plymouth=1 panic=-1 rd.retry=1 root=/dev/null
  initrd /initrd.img
}}
menuentry 'Restart' --class restart --id material-reboot {{ reboot }}
"""
    (tree / "boot/grub/grub.cfg").write_text(cfg)
    th, state = tree / "boot/grub/themes/material", tree / "state/entries.json"
    # hermetic: neither this machine's /etc/material-grub.conf and overrides.json nor its firmware logo may reach the picture; the container the initramfs was
    # built in has none of them either, so both sides draw the defaults
    (tree / "empty.conf").write_text("")
    env = {
        **os.environ,
        "MATERIAL_CONF": str(tree / "empty.conf"),
        "MATERIAL_OVERRIDES": "/nonexistent/overrides.json",
        "MG_BGRT_IMAGE": "/nonexistent/bgrt",
    }
    run = lambda *a: subprocess.run([sys.executable, *map(str, a)], check=True, stdout=subprocess.DEVNULL, env=env)  # noqa: E731
    run(binp / "material-grub-assemble", "--mode", size, "--pkg", pkg, "--out", th)
    run(binp / "material-grub-classes", tree / "boot/grub/grub.cfg", "--pkg", pkg, "--state", state)
    run(binp / "material-grub-scenes", "--theme", th, "--state", state, "--pkg", pkg)
    (tree / "EFI/BOOT").mkdir(parents=True)
    mkimage = shutil.which("grub-mkimage") or shutil.which("grub2-mkimage")
    subprocess.run(
        [
            mkimage,
            "-O",
            "x86_64-efi",
            "-o",
            str(tree / "EFI/BOOT/BOOTX64.EFI"),
            "-p",
            "/boot/grub",
            *[m for m in MODULES if have_module(m)],
        ],
        check=True,
    )
    shutil.copy(kernel, tree / "vmlinuz")
    shutil.copy(initrd, tree / "initrd.img")
    return title


def card(im):
    """The most common bright colour: the hero card (primary container), the second thing the two screens must agree on."""
    return Counter(p for p in im.convert("RGB").getdata() if sum(p) > 450).most_common(1)[0][0]


def background(im):
    """The most common colour of a frame: the scheme's background (the shapes and the card cover less)."""
    return Counter(im.convert("RGB").getdata()).most_common(1)[0][0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mg")
    ap.add_argument("kernel")
    ap.add_argument("initrd")
    ap.add_argument("os_release")
    ap.add_argument("out")
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="mgh-"))
    tree = work / "esp"
    title = build_tree(a.mg, a.kernel, a.initrd, osrel(a.os_release), a.size, tree)
    ovmf = next((c for c in (os.environ.get("OVMF_CODE", ""), *OVMF) if c and os.path.exists(c)), None)
    if not ovmf:
        sys.exit("OVMF not found (install ovmf, or set OVMF_CODE)")
    w, h = a.size.split("x")
    kvm = os.access("/dev/kvm", os.W_OK)
    qmp_path, ser_path = str(work / "qmp"), str(work / "ser")
    cmd = [
        "qemu-system-x86_64",
        "-machine",
        "q35",
        *(["-enable-kvm", "-cpu", "host"] if kvm else ["-cpu", "max"]),
        "-smp",
        "2",
        "-m",
        "2048",
        "-display",
        "none",
        "-vga",
        "none",
        "-device",
        f"VGA,vgamem_mb=64,xres={w},yres={h}",
        "-drive",
        f"if=pflash,format=raw,readonly=on,file={ovmf}",
        "-drive",
        f"format=raw,file=fat:rw:{tree}",
        "-qmp",
        f"unix:{qmp_path},server=on,wait=off",
        "-chardev",
        f"socket,id=ser,path={ser_path},server=on,wait=off",
        "-serial",
        "chardev:ser",
        "-no-reboot",
    ]
    print("accelerator:", "kvm" if kvm else "tcg", "| entry:", title, flush=True)
    qemu = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    log = open(out / "serial.log", "w")
    frames, seen = {}, {}
    try:
        q = boot.Qmp(qmp_path)
        start = time.time()
        # ---- 1. the GRUB menu
        menu = None
        while time.time() - start < a.timeout / 2:
            time.sleep(6)
            im = q.shot(out / "grub-menu.png")
            bright = sum(1 for p in im.getdata() if sum(p) > 600)
            if bright > 2000 and im.size == (int(w), int(h)):
                menu = im
                break
        print(f"  [{time.time() - start:5.0f}s] GRUB menu {'drawn' if menu else 'NOT seen'}", flush=True)
        boot.check(menu is not None, f"GRUB shows the themed menu at {a.size} (bright pixels, the screen's size)")
        if menu is None:
            return finish(out)
        corners = {
            menu.getpixel(p)
            for p in ((2, 2), (menu.width - 3, 2), (2, menu.height - 3), (menu.width - 3, menu.height - 3))
        }
        boot.check(
            len(corners) == 1 and corners != {(0, 0, 0)},
            "the GRUB theme fills the screen (all four corners are one background colour)",
            str(corners),
        )
        # ---- 2. boot the entry
        ser = socket.socket(socket.AF_UNIX)
        for _ in range(100):
            try:
                ser.connect(ser_path)
                break
            except OSError:
                time.sleep(0.2)
        ser.settimeout(5)
        q.key("ret")
        buf, t1 = "", time.time()
        while time.time() - t1 < a.timeout and "splash" not in seen and qemu.poll() is None:
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
                if line.startswith("MGTEST "):
                    word = line.split()[1]
                    seen[word.split("=")[0]] = line
                    print(f"  [{time.time() - start:5.0f}s] {line}", flush=True)
                    if word == "splash":
                        for i in range(3):
                            frames[i] = q.shot(out / f"plymouth-{i + 1}.png")
                            time.sleep(1)
        try:
            q.shot(out / "final.png")
        except Exception as e:
            print("no final screenshot:", e)
    finally:
        qemu.kill()
        log.close()

    boot.check(
        "ready" in seen and re.search(r"plymouthd=\d+", seen.get("ready", "")) is not None,
        "after the menu entry, Plymouth starts in the booted initramfs",
        f"markers {sorted(seen)}",
    )
    if len(frames) == 3:
        sz = (int(w), int(h))
        boot.check(
            all(f.size == sz for f in frames.values()),
            f"the hand-over kept the resolution (GRUB {menu.size[0]}x{menu.size[1]}, Plymouth {frames[0].size[0]}x{frames[0].size[1]})",
        )
        probs = check_frames.check([str(out / f"plymouth-{i}.png") for i in (1, 2, 3)], size=sz, moving=True)
        boot.check(not probs, "the Plymouth splash is drawn and animates", "; ".join(probs))
        black = sum(1 for v in frames[1].getdata() if v == (0, 0, 0)) / (frames[1].width * frames[1].height)
        boot.check(black < 0.3, f"the splash is the theme and not a text screen ({black:.0%} pure black)")
        bg_grub, bg_ply = background(menu), background(frames[1])
        dist = max(abs(x - y) for x, y in zip(bg_grub, bg_ply))
        boot.check(
            dist <= 12,
            f"the splash continues the menu: the background colour is the same (GRUB {bg_grub}, Plymouth {bg_ply})",
        )
    else:
        boot.check(False, "the Plymouth splash was photographed", f"markers {sorted(seen)}")
    return finish(out)


def finish(out):
    print()
    print("RESULT: " + ("FAIL: " + "; ".join(boot.FAILED) if boot.FAILED else "all checks passed"))
    return 1 if boot.FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
