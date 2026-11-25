#!/bin/sh
# Step 1 of the QEMU boot tier, in a fresh distro container: installs Plymouth, the distro's initramfs tool and a real kernel, runs `plymouth apply` for real,
# then builds a TEST initramfs with the same tool (not host-only: it has to find a display under QEMU) with ci/qemu/mgtest-hook.sh added, and copies the kernel
# and that image to /out.   Works on Fedora and openSUSE (dracut), Debian and Ubuntu (initramfs-tools), Arch (mkinitcpio).
#   docker run --rm -v "$PWD:/w:ro" -v "$CORE_DIR:/core:ro" -v "$CORE_DATA_DIR:/core-data:ro" -v "$OUT:/out" IMAGE sh /w/ci/qemu/prepare.sh
set -eu
export MATERIAL_LIB=/core MATERIAL_DATA=/core-data
# shellcheck disable=SC1091
. /etc/os-release
echo "== ${PRETTY_NAME:-$ID}"
# Only behind a TLS-intercepting proxy (a sandbox): MG_CA is a CA certificate to trust. GitHub's runners do not need it.
if [ -n "${MG_CA:-}" ] && [ -f "$MG_CA" ]; then
  if [ -d /etc/pki/ca-trust/source/anchors ]; then cp "$MG_CA" /etc/pki/ca-trust/source/anchors/mg-ca.crt && update-ca-trust
  elif [ -d /etc/ca-certificates/trust-source/anchors ]; then cp "$MG_CA" /etc/ca-certificates/trust-source/anchors/mg-ca.crt && update-ca-trust
  elif [ -d /usr/share/pki/trust/anchors ]; then cp "$MG_CA" /usr/share/pki/trust/anchors/mg-ca.crt && update-ca-certificates
  else mkdir -p /usr/local/share/ca-certificates && cp "$MG_CA" /usr/local/share/ca-certificates/mg-ca.crt && { command -v update-ca-certificates >/dev/null && update-ca-certificates || true; }
  fi
fi

if command -v dnf >/dev/null 2>&1; then
  tool=dracut
  dnf -y install --setopt=tsflags=noscripts kernel-core >/dev/null
  dnf -y install findutils plymouth plymouth-plugin-script plymouth-scripts plymouth-graphics-libs plymouth-plugin-label dejavu-sans-fonts dracut python3 python3-pillow kmod systemd-udev >/dev/null
elif command -v apt-get >/dev/null 2>&1; then
  tool=initramfs-tools
  export DEBIAN_FRONTEND=noninteractive INITRD=No
  apt-get update >/dev/null
  case $ID in ubuntu) kernel=linux-image-generic ;; *) kernel=linux-image-amd64 ;; esac
  apt-get install -y --no-install-recommends initramfs-tools plymouth plymouth-label plymouth-themes fonts-dejavu-core python3 python3-pil kmod "$kernel" >/dev/null
elif command -v pacman >/dev/null 2>&1; then
  tool=mkinitcpio
  pacman -Syu --noconfirm --needed plymouth mkinitcpio python python-pillow kmod linux ttf-dejavu >/dev/null 2>&1 || pacman -Syu --noconfirm --needed plymouth mkinitcpio python python-pillow kmod linux ttf-dejavu
elif command -v zypper >/dev/null 2>&1; then
  tool=dracut
  zypper --non-interactive --gpg-auto-import-keys refresh >/dev/null
  zypper --non-interactive install --no-recommends findutils plymouth plymouth-plugin-script plymouth-plugin-label plymouth-plugin-label-ft plymouth-scripts plymouth-dracut dracut python3 python3-Pillow kmod kernel-default dejavu-fonts >/dev/null
else
  echo "no known package manager"; exit 1
fi
unset INITRD
for k in /lib/modules/*; do depmod -a "$(basename "$k")"; done
systemd-machine-id-setup >/dev/null 2>&1 || true
kver=$(ls /lib/modules | head -n1)
# a real system always has an initramfs for `update-initramfs -u` to update; a fresh container has none (Debian and Ubuntu: the kernel package ran with INITRD=No)
[ "$tool" != initramfs-tools ] || update-initramfs -c -k all >/dev/null

# which Plymouth this is: the matrix covers several generations
{ rpm -q --qf 'plymouth %{VERSION}-%{RELEASE}\n' plymouth 2>/dev/null || dpkg-query -W -f='plymouth ${Version}\n' plymouth 2>/dev/null || { pacman -Q plymouth 2>/dev/null; }; } || true
echo "initramfs tool: $tool"

cd /w
if [ -n "${STOCK_THEME:-}" ]; then
  # an experiment: boot one of the distro's own themes instead of ours, to tell a problem of the theme from one of Plymouth, the kernel or the display
  plymouth-set-default-theme "$STOCK_THEME" 2>/dev/null || { update-alternatives --install /usr/share/plymouth/themes/default.plymouth default.plymouth "/usr/share/plymouth/themes/$STOCK_THEME/$STOCK_THEME.plymouth" 50 && update-alternatives --set default.plymouth "/usr/share/plymouth/themes/$STOCK_THEME/$STOCK_THEME.plymouth"; }
else
python3 - <<'PY'
import sys
sys.path.insert(0, "/w")
from material_plymouth import plugin
class Core:
    say = staticmethod(print)
    conf_path = staticmethod(lambda: "/etc/material-grub.conf")
    elevate = staticmethod(lambda *a: None)
sys.exit(plugin.main(["apply", "--yes"], Core()))
PY
fi

kernel_file=""
for f in "/lib/modules/$kver/vmlinuz" "/boot/vmlinuz-$kver" "/boot/vmlinuz"; do [ -f "$f" ] && kernel_file=$f && break; done
[ -n "$kernel_file" ] || { echo "no kernel image found for $kver"; exit 1; }
cp "$kernel_file" /out/vmlinuz

case $tool in
  dracut)
    dracut -f --no-hostonly --no-hostonly-cmdline --kver "$kver" \
      --add "plymouth" --add-drivers "bochs drm_shmem_helper drm_vram_helper drm_ttm_helper ttm" \
      --include /w/ci/qemu/mgtest-hook.sh /lib/dracut/hooks/pre-trigger/99-mgtest.sh /out/initrd.img
    lsinitrd /out/initrd.img | grep -E "themes/material/material.script|plymouth/script.so|plymouth/label|99-mgtest"
    ;;
  initramfs-tools)
    # the hook runs in init-premount AFTER the distro's own plymouth script there (prereqs) has started plymouthd; MODULES=most so the display driver is in the image
    # it blocks (`wait`): otherwise init fails to mount root=/dev/null, drops to a shell and quits Plymouth before the test is over
    { printf '#!/bin/sh\ncase $1 in prereqs) echo "plymouth"; exit 0 ;; esac\n'; tail -n +2 /w/ci/qemu/mgtest-hook.sh | sed '$d'; echo wait; } >/etc/initramfs-tools/scripts/init-premount/mgtest
    chmod +x /etc/initramfs-tools/scripts/init-premount/mgtest
    sed -i 's/^MODULES=.*/MODULES=most/' /etc/initramfs-tools/initramfs.conf
    mkinitramfs -o /out/initrd.img "$kver"
    lsinitramfs /out/initrd.img | grep -E "themes/material/material.script|plymouth/script.so|plymouth/label|init-premount/mgtest"
    ;;
  mkinitcpio)
    mkdir -p /etc/initcpio/install /etc/initcpio/hooks
    printf '#!/bin/bash\nbuild() { add_runscript; }\nhelp() { echo "test hook"; }\n' >/etc/initcpio/install/mgtest
    # the hook is the body of run_hook: its last line (`exit 0`) is dropped and `wait` blocks instead, so init cannot fail the root mount (root=/dev/null),
    # drop to an emergency shell and quit Plymouth before the test is over
    { echo '#!/usr/bin/ash'; echo 'run_hook() {'; tail -n +2 /w/ci/qemu/mgtest-hook.sh | sed '$d'; echo '  wait'; echo '}'; } >/etc/initcpio/hooks/mgtest
    # no autodetect (it would drop the display driver of a machine that has none), the display driver by name
    sed -e 's/^HOOKS=.*/HOOKS=(base udev plymouth mgtest)/' -e 's/^MODULES=.*/MODULES=(bochs)/' /etc/mkinitcpio.conf >/tmp/mkinitcpio-test.conf
    mkinitcpio -c /tmp/mkinitcpio-test.conf -k "$kver" -g /out/initrd.img
    lsinitcpio /out/initrd.img | grep -E "themes/material/material.script|plymouth/script.so|plymouth/label|hooks/mgtest"
    ;;
esac
cp /etc/os-release /out/os-release  # the GRUB entry of the hand-over test is titled like this system
chmod 644 /out/initrd.img /out/vmlinuz /out/os-release
echo "kernel $kver, initramfs $(stat -c %s /out/initrd.img) bytes"
