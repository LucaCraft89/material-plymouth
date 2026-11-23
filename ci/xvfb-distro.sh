#!/bin/sh
# Tier 2 on each distro's own Plymouth: installs Plymouth (with its X11 renderer), Xvfb and the tools in a fresh distro container, then plays the stock `spinner`
# theme (the harness) and the Material theme in every style and motion level, as the xvfb job does on Ubuntu. Run in a throw-away container:
#   docker run --rm -v "$PWD:/w:ro" -v "$MATERIAL_GRUB_DIR:/mg:ro" -v "$PWD/build:/out" IMAGE sh /w/ci/xvfb-distro.sh
#   /w   this repository, /mg   a material-grub checkout with a built package, /out   where the screenshots go
set -eu
export MATERIAL_GRUB=/mg
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
  dnf -y install --setopt=tsflags=noscripts plymouth plymouth-plugin-script plymouth-theme-spinner plymouth-graphics-libs xorg-x11-server-Xvfb ImageMagick xdotool bc procps-ng python3 python3-pillow >/dev/null
elif command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive INITRD=No
  apt-get update >/dev/null
  apt-get install -y --no-install-recommends plymouth plymouth-theme-spinner plymouth-x11 xvfb imagemagick bc xdotool procps python3 python3-pil >/dev/null
elif command -v pacman >/dev/null 2>&1; then
  pacman -Syu --noconfirm --needed plymouth xorg-server-xvfb imagemagick xdotool bc procps-ng python python-pillow >/dev/null 2>&1 || pacman -Syu --noconfirm --needed plymouth xorg-server-xvfb imagemagick xdotool bc procps-ng python python-pillow
elif command -v zypper >/dev/null 2>&1; then
  zypper --non-interactive --gpg-auto-import-keys refresh >/dev/null
  zypper --non-interactive install --no-recommends plymouth plymouth-plugin-script plymouth-theme-spinner xorg-x11-server-Xvfb ImageMagick xdotool bc procps python3 python3-Pillow >/dev/null
else
  echo "no known package manager"; exit 1
fi
unset INITRD

echo "plymouthd: $(plymouthd --version 2>&1 | head -n1)"
echo "x11 renderer: $(find /usr/lib /usr/lib64 /usr/libexec -path '*plymouth/renderers/x11.so' 2>/dev/null | head -n1 || true)"
echo "spinner theme: $(ls /usr/share/plymouth/themes/spinner/spinner.plymouth 2>&1)"
cp -r /w /tmp/w && cd /tmp/w
ci/xvfb_play.sh spinner /out/xvfb/spinner 6
python3 ci/check_frames.py --size 1920x1080 --moving /out/xvfb/spinner-*.png
PLAY_SHOTS=/out/play-shots REQUIRE_CORE=1 REQUIRE_PLAY=1 exec python3 -m unittest discover -s tests -p "test_theme_play.py" -v
