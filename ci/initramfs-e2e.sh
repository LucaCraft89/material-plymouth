#!/bin/sh
# Tier 3: installs Plymouth, the distro's initramfs tool, a real kernel and Pillow in a fresh distro container, then runs ci/initramfs_e2e.py, which applies and
# removes the theme against a REAL initramfs. Run inside a throw-away container: it installs packages, writes /boot and /etc.
# usage: docker run --rm -v "$PWD:/w:ro" -v "$MATERIAL_GRUB_DIR:/mg:ro" IMAGE sh /w/ci/initramfs-e2e.sh
#   /w   this repository, /mg   a material-grub checkout with a built package (dist/material-grub)
set -eu
export MATERIAL_GRUB=/mg
# shellcheck disable=SC1091
. /etc/os-release
echo "== ${PRETTY_NAME:-$ID}"

# Only for running behind a TLS-intercepting proxy (a sandbox): MG_CA names a CA certificate (mounted into the container) to trust. GitHub's runners do not need it.
if [ -n "${MG_CA:-}" ] && [ -f "$MG_CA" ]; then
  if [ -d /etc/pki/ca-trust/source/anchors ]; then cp "$MG_CA" /etc/pki/ca-trust/source/anchors/mg-ca.crt && update-ca-trust
  elif [ -d /etc/ca-certificates/trust-source/anchors ]; then cp "$MG_CA" /etc/ca-certificates/trust-source/anchors/mg-ca.crt && update-ca-trust
  elif [ -d /usr/share/pki/trust/anchors ]; then cp "$MG_CA" /usr/share/pki/trust/anchors/mg-ca.crt && update-ca-certificates
  else mkdir -p /usr/local/share/ca-certificates && cp "$MG_CA" /usr/local/share/ca-certificates/mg-ca.crt && { command -v update-ca-certificates >/dev/null && update-ca-certificates || true; }
  fi
fi

if command -v dnf >/dev/null 2>&1; then
  # the kernel's own scriptlets would build an initramfs through kernel-install; we build it ourselves, so they are skipped
  dnf -y install --setopt=tsflags=noscripts kernel-core >/dev/null
  dnf -y install findutils plymouth plymouth-plugin-script plymouth-plugin-label plymouth-scripts dracut python3 python3-pillow kmod >/dev/null
elif command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive INITRD=No
  apt-get update >/dev/null
  case $ID in ubuntu) kernel=linux-image-virtual ;; *) kernel=linux-image-amd64 ;; esac
  apt-get install -y --no-install-recommends initramfs-tools plymouth plymouth-label plymouth-themes python3 python3-pil kmod "$kernel" >/dev/null
elif command -v pacman >/dev/null 2>&1; then
  # the container has no real disk: no space check; the kernel package's hooks would run mkinitcpio, so only the files are wanted
  pacman -Syu --noconfirm --needed --disable-sandbox >/dev/null 2>&1 || pacman -Syu --noconfirm --needed >/dev/null
  pacman -S --noconfirm --needed plymouth mkinitcpio python python-pillow kmod linux >/dev/null 2>&1 || pacman -S --noconfirm --needed plymouth mkinitcpio python python-pillow kmod linux
elif command -v zypper >/dev/null 2>&1; then
  zypper --non-interactive --gpg-auto-import-keys refresh >/dev/null
  zypper --non-interactive install --no-recommends findutils plymouth plymouth-plugin-script plymouth-plugin-label plymouth-plugin-label-ft plymouth-scripts plymouth-dracut dracut python3 python3-Pillow kmod kernel-default-base >/dev/null
else
  echo "no known package manager"; exit 1
fi

# the kernel packages' own scriptlets (depmod, the initramfs) are skipped or fail in a container: depmod is what dracut and mkinitcpio need from them
for k in /lib/modules/*; do [ -d "$k" ] && depmod -a "$(basename "$k")" 2>/dev/null || true; done
[ -s /etc/machine-id ] || { command -v systemd-machine-id-setup >/dev/null && systemd-machine-id-setup >/dev/null 2>&1 || true; }

ls /lib/modules /boot 2>&1 | sed 's/^/  /'
cd /w
unset INITRD  # set above to keep the kernel package from building an image; update-initramfs would build nothing with it
exec python3 ci/initramfs_e2e.py
