#!/bin/sh
# Installs the sources of this part into DESTDIR the way a package does: the code in <share>/material-plymouth and the plugin manifest where material-grub looks.
# usage: packaging/install-tree.sh SRCDIR DESTDIR [PREFIX]      (PREFIX defaults to /usr)
set -eu
src=$1; dest=$2; prefix=${3:-/usr}
share=$prefix/share/material-plymouth
version=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$src/material_plymouth/__init__.py")
install -d "$dest$share/bin" "$dest$share/material_plymouth" "$dest$prefix/share/material-boot/plugins.d"
for f in "$src"/material_plymouth/*.py; do install -m644 "$f" "$dest$share/material_plymouth/"; done
install -m644 "$src/bin/mgplugin.py" "$dest$share/bin/mgplugin.py"
install -m644 "$src/LICENSE" "$dest$share/LICENSE"
sed -e "s|@SHARE@|$share|g" -e "s|@VERSION@|$version|g" "$src/packaging/plymouth.json.in" > "$dest$prefix/share/material-boot/plugins.d/plymouth.json"
