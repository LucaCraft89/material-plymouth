#!/bin/sh
# Step 1 of the QEMU boot tier, in a fresh Fedora container: installs Plymouth, dracut and a real kernel, runs `plymouth apply` for real, then builds a TEST
# initramfs the same way (no host-only: it has to find a display under QEMU) with ci/qemu/mgtest-hook.sh added, and copies the kernel and that image to /out.
#   docker run --rm -v "$PWD:/w:ro" -v "$MG:/mg:ro" -v "$OUT:/out" fedora sh /w/ci/qemu/prepare.sh
set -eu
export MATERIAL_GRUB=/mg
if [ -n "${MG_CA:-}" ] && [ -f "$MG_CA" ]; then cp "$MG_CA" /etc/pki/ca-trust/source/anchors/mg-ca.crt && update-ca-trust; fi
dnf -y install --setopt=tsflags=noscripts kernel-core >/dev/null
dnf -y install findutils plymouth plymouth-plugin-script plymouth-scripts plymouth-graphics-libs plymouth-plugin-label plymouth-theme-spinner dejavu-sans-fonts dracut python3 python3-pillow kmod systemd-udev >/dev/null
for k in /lib/modules/*; do depmod -a "$(basename "$k")"; done
systemd-machine-id-setup >/dev/null 2>&1 || true
kver=$(ls /lib/modules | head -n1)
cd /w
if [ -n "${STOCK_THEME:-}" ]; then
  # an experiment: boot one of the distro's own themes instead of ours, to tell a problem of the theme from one of Plymouth
  dnf -y install "plymouth-theme-$STOCK_THEME" >/dev/null
  plymouth-set-default-theme "$STOCK_THEME"
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
cp "/lib/modules/$kver/vmlinuz" /out/vmlinuz
dracut -f --no-hostonly --no-hostonly-cmdline --kver "$kver" \
  --add "plymouth" --add-drivers "bochs drm_shmem_helper drm_vram_helper drm_ttm_helper ttm" \
  --include /w/ci/qemu/mgtest-hook.sh /lib/dracut/hooks/pre-trigger/99-mgtest.sh /out/initrd.img
chmod 644 /out/initrd.img /out/vmlinuz
lsinitrd /out/initrd.img | grep -E "themes/material/material.script|plymouth/script.so|99-mgtest" 
echo "kernel $kver, initramfs $(stat -c %s /out/initrd.img) bytes"
