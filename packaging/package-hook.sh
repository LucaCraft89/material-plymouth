#!/bin/sh
# Called by the package scriptlets of every format (rpm %posttrans/%preun, deb postinst/prerm, pacman post_install/post_upgrade/pre_remove). It NEVER fails the
# package transaction and it never makes a first-time change to how the system boots: it asks the unified installer, which runs this part's install hook
# (material_plymouth/hooks.py) as a package install:
#   configure  (install and upgrade) record the part; if the theme was applied before, render it again with the new code (only if the look changed; never the
#              kernel command line). A first install applies nothing: turning the boot splash on is the person's own act (`material-boot plymouth apply`, or the
#              GUI), because it rebuilds the initramfs and may edit the kernel command line.
#   remove     the package is going away: take the theme out again the way apply put it in (restores the previous default theme, rebuilds the initramfs) and
#              forget the part
here=$(cd "$(dirname "$0")/.." && pwd)   # /usr/share/material-plymouth
# where the core puts its command (a package and a source install differ); a scriptlet's PATH is not always the login PATH
mb=""
for c in /usr/bin/material-boot /usr/local/bin/material-boot; do
  [ -x "$c" ] && { mb=$c; break; }
done
[ -n "$mb" ] || mb=$(command -v material-boot 2>/dev/null || true)
cleanup() { rm -rf "$here/material_plymouth/__pycache__" "$here/bin/__pycache__"; }   # Python ran as root on the installed code: the byte-code is not owned by the package and would keep the directory alive
if [ -z "$mb" ]; then  # the core is already gone (removed first): nothing can be undone by it
  [ "${1:-}" = remove ] && cleanup
  exit 0
fi
case ${1:-} in
  configure | upgrade) "$mb" core install --from-package --only plymouth --yes || echo "material-plymouth: could not finish the install or the update of the part (run: material-boot core install --only plymouth)" ;;
  remove) "$mb" core install --uninstall --from-package --only plymouth --yes || echo "material-plymouth: could not take the theme out (run: material-boot plymouth remove)"
          cleanup ;;
esac
exit 0
