#!/bin/sh
# Builds the package of one format from this checkout in a fresh distro container, installs it, and exercises its scriptlets. Run in a throw-away container:
#   docker run --rm -v "$PWD:/w:ro" IMAGE sh /w/ci/package-test.sh rpm|deb|arch
# What it proves: the package builds; it holds the code, the hook and the plugin manifest where material-grub looks; installing it changes NOTHING about how
# the system boots (no state file, no call to material-grub); an upgrade re-applies only a theme that was applied before (--if-changed --no-cmdline, never
# the kernel command line); removing the package takes the theme out first, and leaves no file of ours. A fake `material-grub` logs what the scriptlets call.
set -eu
kind=${1:?rpm, deb or arch}
ver=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' /w/material_plymouth/__init__.py)
work=/tmp/pkgbuild; mkdir -p "$work"
fail=0
ok() { echo "PASS  $*"; }
bad() { echo "FAIL  $*"; fail=1; }
check() { desc=$1; shift; if "$@"; then ok "$desc"; else bad "$desc"; fi; }

# a copy of the checkout as the source tarball a release would be (material-plymouth-VERSION/ at the top)
mkdir -p /tmp/src && cp -r /w /tmp/src/material-plymouth-"$ver" && rm -rf /tmp/src/material-plymouth-"$ver"/.git
tar -C /tmp/src -czf "$work/material-plymouth-$ver.tar.gz" material-plymouth-"$ver"

# a fake material-grub: records every call; `plymouth remove`/`apply` pretend to work
cat >/usr/local/bin/material-grub <<'FAKE'
#!/bin/sh
echo "$*" >> /tmp/material-grub.calls
exit 0
FAKE
chmod +x /usr/local/bin/material-grub
: >/tmp/material-grub.calls
calls() { cat /tmp/material-grub.calls; }

case $kind in
  rpm)
    dnf -y install rpm-build python3 python3-pillow >/dev/null
    mkdir -p /root/rpmbuild/SOURCES && cp "$work/material-plymouth-$ver.tar.gz" /root/rpmbuild/SOURCES/
    rpmbuild -ba --define "_topdir /root/rpmbuild" /w/packaging/rpm/material-plymouth.spec >"$work/build.log" 2>&1 || { tail -30 "$work/build.log"; exit 1; }
    pkg=$(ls /root/rpmbuild/RPMS/noarch/material-plymouth-*.rpm)
    echo "built $pkg"; rpm -qp --requires "$pkg" | sed 's/^/  requires /'
    list() { rpm -qpl "$pkg"; }
    install() { rpm -i --nodeps --nosignature "$pkg"; }
    upgrade() { rpm -U --nodeps --nosignature --replacepkgs "$pkg"; }
    remove() { rpm -e --nodeps material-plymouth; }
    ;;
  deb)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update >/dev/null && apt-get install -y --no-install-recommends debhelper dpkg-dev fakeroot build-essential python3 python3-pil >/dev/null
    rm -rf /tmp/debsrc && mkdir /tmp/debsrc && tar -C /tmp/debsrc -xzf "$work/material-plymouth-$ver.tar.gz"
    cd "/tmp/debsrc/material-plymouth-$ver" && cp -r packaging/debian/debian debian
    dpkg-buildpackage -us -uc -b >"$work/build.log" 2>&1 || { tail -30 "$work/build.log"; exit 1; }
    pkg=$(ls /tmp/debsrc/material-plymouth_*_all.deb)
    echo "built $pkg"; dpkg-deb -f "$pkg" Depends | sed 's/^/  depends /'
    list() { dpkg-deb -c "$pkg" | awk '{print $NF}'; }
    install() { dpkg -i --force-depends "$pkg" >/dev/null; }
    upgrade() { dpkg -i --force-depends "$pkg" >/dev/null; }
    remove() { dpkg -r material-plymouth >/dev/null; }
    ;;
  arch)
    pacman -Syu --noconfirm --needed base-devel python python-pillow plymouth mkinitcpio >/dev/null 2>&1 || pacman -Syu --noconfirm --needed base-devel python python-pillow plymouth mkinitcpio
    id builder >/dev/null 2>&1 || useradd -m builder
    install -d -o builder /tmp/arch && cp /w/packaging/arch/PKGBUILD /w/packaging/arch/material-plymouth.install /tmp/arch/ && cp "$work/material-plymouth-$ver.tar.gz" /tmp/arch/
    chown -R builder /tmp/arch
    su builder -c "cd /tmp/arch && MP_SOURCE=file:///tmp/arch/material-plymouth-$ver.tar.gz makepkg -f --nodeps --noconfirm" >"$work/build.log" 2>&1 || { tail -30 "$work/build.log"; exit 1; }
    pkg=$(ls /tmp/arch/material-plymouth-*.pkg.tar.*)
    echo "built $pkg"; pacman -Qpi "$pkg" | grep -E "^(Depends On)" | sed 's/^/  /'
    list() { pacman -Qpl "$pkg" | awk '{print $2}'; }
    install() { pacman -U --noconfirm --assume-installed material-grub=0.8.0 "$pkg" >"$work/pacman.log" 2>&1 || { tail -20 "$work/pacman.log"; return 1; }; }
    upgrade() { install; }
    remove() { pacman -R --noconfirm material-plymouth >"$work/pacman.log" 2>&1 || { tail -20 "$work/pacman.log"; return 1; }; }
    ;;
  *) echo "unknown kind $kind"; exit 2 ;;
esac

listing=$(list)
check "the package holds the plugin manifest where material-grub looks" sh -c "echo '$listing' | grep -q 'share/material-boot/plugins.d/plymouth.json'"
check "the package holds the code, the entry file and the hook" sh -c "echo '$listing' | grep -q 'material-plymouth/material_plymouth/apply.py' && echo '$listing' | grep -q 'material-plymouth/bin/mgplugin.py' && echo '$listing' | grep -q 'material-plymouth/bin/package-hook.sh'"
check "the package holds no prebuilt theme or image" sh -c "! echo '$listing' | grep -qE '\\.(png|plymouth|img)\$'"

# ---- install: nothing about booting changes
install
check "installed: the manifest names this version and a file that exists" sh -c "
  v=\$(sed -n 's/.*\"version\": \"\\(.*\\)\".*/\\1/p' /usr/share/material-boot/plugins.d/plymouth.json); [ \"\$v\" = '$ver' ] &&
  e=\$(sed -n 's/.*\"entry\": \"\\(.*\\)\".*/\\1/p' /usr/share/material-boot/plugins.d/plymouth.json) && [ -f \"\$e\" ]"
check "installed: the scriptlet made no call to material-grub (no first-time change)" sh -c "[ ! -s /tmp/material-grub.calls ]"
check "installed: no state file, no theme directory" sh -c "[ ! -e /var/lib/material-plymouth/state.json ] && [ ! -e /usr/share/plymouth/themes/material ]"
check "installed: the code imports" python3 -c "import sys; sys.path.insert(0, '/usr/share/material-plymouth'); import material_plymouth; assert material_plymouth.__version__ == '$ver'"

# ---- upgrade of a theme that was never applied: still nothing
upgrade
check "upgraded, never applied: still no call" sh -c "[ ! -s /tmp/material-grub.calls ]"

# ---- upgrade of a theme that WAS applied: it is rendered again, without touching the kernel command line
mkdir -p /var/lib/material-plymouth && echo '{}' >/var/lib/material-plymouth/state.json
upgrade
check "upgraded, applied before: re-applied with --if-changed --no-cmdline and nothing else" sh -c "[ \"\$(cat /tmp/material-grub.calls)\" = 'plymouth apply --if-changed --no-cmdline' ]"
: >/tmp/material-grub.calls

# ---- remove: the theme is taken out first, our files are gone
remove
check "removed: the theme was taken out first (plymouth remove --yes)" sh -c "grep -qx 'plymouth remove --yes' /tmp/material-grub.calls"
check "removed: no file of ours is left" sh -c "[ ! -e /usr/share/material-plymouth ] && [ ! -e /usr/share/material-boot/plugins.d/plymouth.json ]"
rm -f /var/lib/material-plymouth/state.json

echo
[ "$fail" = 0 ] && echo "RESULT: all checks passed" || { echo "RESULT: FAIL"; exit 1; }
