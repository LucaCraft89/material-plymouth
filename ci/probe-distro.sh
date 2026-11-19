#!/bin/sh
# Installs Plymouth and the initramfs tooling in a fresh distro container and writes down what is really there, so the design rests on facts about each
# distro (package names, where the script plugin lives, which initramfs tool, how the default theme is chosen), not on assumptions.
# usage: ci/probe-distro.sh OUTDIR        (run inside the container; writes OUTDIR/<distro id>.txt, prints it, exits 1 when an essential is missing)
# Essentials: plymouthd, the script plugin (script.so), an initramfs integration point, python3 >= 3.8 (what the material-grub tools run on).
set -u
out=${1:-/tmp/probe}
mkdir -p "$out"
# shellcheck disable=SC1091
. /etc/os-release
id=${ID:-unknown}
report=$out/$id.txt
: >"$report"
say() { echo "$*" | tee -a "$report"; }
# the first line a command prints, or "none" when it is missing or prints nothing (a pipe into head hides the command's own failure)
first() { v=$("$@" 2>/dev/null | head -n1); echo "${v:-none}"; }

if command -v dnf >/dev/null 2>&1; then
  pm=dnf; refresh=":"; add() { dnf -y install "$1"; }
  pkgs="findutils plymouth plymouth-plugin-script plymouth-scripts dracut python3"
elif command -v apt-get >/dev/null 2>&1; then
  pm=apt; refresh="apt-get update"; add() { INITRD=No DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$1"; }
  pkgs="plymouth plymouth-themes initramfs-tools python3"
elif command -v pacman >/dev/null 2>&1; then
  pm=pacman; refresh="pacman -Syu --noconfirm"; add() { pacman -S --noconfirm --needed "$1"; }
  pkgs="plymouth mkinitcpio python"
elif command -v zypper >/dev/null 2>&1; then
  pm=zypper; refresh="zypper --non-interactive --gpg-auto-import-keys refresh"; add() { zypper --non-interactive install --no-recommends "$1"; }
  pkgs="findutils plymouth plymouth-plugin-script plymouth-scripts plymouth-dracut dracut python3"
else
  say "FAIL: no known package manager"; exit 1
fi

say "distro=$id ${VERSION_ID:-}"
say "package_manager=$pm"
$refresh >/dev/null 2>&1 || say "note: refreshing the package index failed"
# one package at a time: a name that does not exist on this distro must not hide the others
for p in $pkgs; do
  if add "$p" >"$out/$id-install-$p.log" 2>&1; then say "package $p=installed"; else say "package $p=MISSING (see $id-install-$p.log)"; fi
done

fails=""
need() { fails="$fails $1"; }

pd=$(command -v plymouthd 2>/dev/null || ls /usr/sbin/plymouthd /usr/libexec/plymouth/plymouthd 2>/dev/null | head -n1)
say "plymouthd=${pd:-NOT FOUND}"
[ -n "$pd" ] || need plymouthd
if command -v rpm >/dev/null 2>&1; then ver=$(rpm -q --qf '%{VERSION}-%{RELEASE}' plymouth 2>/dev/null)
elif command -v dpkg-query >/dev/null 2>&1; then ver=$(dpkg-query -W -f='${Version}' plymouth 2>/dev/null)
elif command -v pacman >/dev/null 2>&1; then ver=$(pacman -Q plymouth 2>/dev/null | cut -d' ' -f2)
else ver=""; fi
say "plymouth_version=${ver:-unknown}"
script=$(find /usr/lib /usr/lib64 /usr/libexec -name script.so -path '*plymouth*' 2>/dev/null | head -n1)
say "script_plugin=${script:-NOT FOUND}"
[ -n "$script" ] || need script-plugin
[ -n "$script" ] && say "renderers=$(ls "$(dirname "$script")/renderers" 2>/dev/null | tr '\n' ' ')"
say "theme_dir=$([ -d /usr/share/plymouth/themes ] && echo /usr/share/plymouth/themes || echo NOT FOUND)"
say "themes=$(ls /usr/share/plymouth/themes 2>/dev/null | tr '\n' ' ')"
say "set_default_theme=$(command -v plymouth-set-default-theme 2>/dev/null || echo none)"
say "alternatives_default=$(update-alternatives --list default.plymouth 2>/dev/null | tr '\n' ' ')"
say "plymouthd_defaults=$(ls /usr/share/plymouth/plymouthd.defaults /etc/plymouth/plymouthd.conf 2>/dev/null | tr '\n' ' ')"

integ=""
for f in /usr/lib/dracut/modules.d/*plymouth* /usr/share/initramfs-tools/hooks/plymouth /usr/lib/initcpio/install/plymouth /usr/lib/initcpio/hooks/plymouth; do
  [ -e "$f" ] && integ="$integ $f"
done
say "initramfs_integration=${integ:- NONE}"
[ -n "$integ" ] || need initramfs-integration
say "dracut=$(first dracut --version)"
say "update_initramfs=$(command -v update-initramfs 2>/dev/null || echo none)"
say "mkinitcpio=$(first mkinitcpio -V)"

py=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo none)
say "python3=$py"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null || need python3-3.8

if [ -n "$fails" ]; then say "RESULT: FAIL, missing:$fails"; exit 1; fi
say "RESULT: ok"
