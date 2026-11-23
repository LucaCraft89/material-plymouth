#!/bin/sh
# Called by the package scriptlets of every format (rpm %posttrans/%preun, deb postinst/prerm, pacman post_upgrade/pre_remove). It NEVER fails the package
# transaction and it never makes a first-time change: installing the package only installs the part; turning the boot splash on is the person's own act
# (`material-grub plymouth apply`, or the GUI), because it rebuilds the initramfs and may edit the kernel command line.
#   upgrade   the theme was applied before: render it again with the new code (only if the look changed; never the kernel command line)
#   remove    the package is going away: take the theme out again the way apply put it in (restores the previous default theme, rebuilds the initramfs)
state=/var/lib/material-plymouth/state.json
here=$(cd "$(dirname "$0")/.." && pwd)   # /usr/share/material-plymouth
# where material-grub puts its command (a source install and a package both use /usr/local/bin); a scriptlet's PATH is not always the login PATH
mg=""
for c in /usr/local/bin/material-grub /usr/bin/material-grub; do
  [ -x "$c" ] && { mg=$c; break; }
done
[ -n "$mg" ] || mg=$(command -v material-grub 2>/dev/null || true)
if [ -z "$mg" ]; then  # material-grub is already gone (removed first): nothing can be undone by it
  [ "${1:-}" = remove ] && rm -rf "$here/material_plymouth/__pycache__" "$here/bin/__pycache__"
  exit 0
fi
case ${1:-} in
  upgrade) [ -f "$state" ] && { "$mg" plymouth apply --if-changed --no-cmdline || echo "material-plymouth: could not re-apply the theme after the update (run: material-grub plymouth apply)"; } ;;
  remove)  [ -f "$state" ] && { "$mg" plymouth remove --yes || echo "material-plymouth: could not take the theme out (run: material-grub plymouth remove)"; }
           # Python ran as root on the installed code (apply does): the byte-code it wrote is not owned by the package and would keep the directory alive
           rm -rf "$here/material_plymouth/__pycache__" "$here/bin/__pycache__" ;;
esac
exit 0
