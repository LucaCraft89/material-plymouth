#!/bin/sh
# Plays a Plymouth theme with the X11 renderer under Xvfb and takes screenshots, so a theme can be looked at (and checked) without a VM.
# usage: ci/xvfb_play.sh THEME OUTPREFIX [SECONDS] [WxH]
#   THEME       the name of an installed theme (/usr/share/plymouth/themes/NAME) or the path of a theme directory (NAME/NAME.plymouth inside)
#   OUTPREFIX   writes OUTPREFIX-1.png ... (one per second), OUTPREFIX.log (plymouthd's debug log) and OUTPREFIX.cpu
# Needs: plymouth, plymouth-x11 (the renderer), Xvfb, ImageMagick (import), bc. Root or sudo: the theme is linked into /usr/share/plymouth/themes and
# the daemon's config is written to /etc/plymouth. Meant for a CI runner or a throw-away container, not for a machine you boot from.
set -eu
theme=$1; out=$2; secs=${3:-6}; size=${4:-1920x1080}
SUDO=""; [ "$(id -u)" = 0 ] || SUDO=sudo
display=${XVFB_DISPLAY:-:99}

if [ -d "$theme" ]; then
  name=$(basename "$theme")
  [ -f "$theme/$name.plymouth" ] || { echo "xvfb_play: $theme/$name.plymouth is missing" >&2; exit 2; }
  $SUDO ln -sfn "$(cd "$theme" && pwd)" "/usr/share/plymouth/themes/$name"
else
  name=$theme
  [ -f "/usr/share/plymouth/themes/$name/$name.plymouth" ] || { echo "xvfb_play: theme '$name' is not installed" >&2; exit 2; }
fi
$SUDO mkdir -p /etc/plymouth
printf '[Daemon]\nTheme=%s\nShowDelay=0\nDeviceTimeout=1\n' "$name" | $SUDO tee /etc/plymouth/plymouthd.conf >/dev/null
mkdir -p "$(dirname "$out")"

pd=""; xv=""
cleanup() {
  plymouth quit 2>/dev/null || true
  [ -n "$pd" ] && $SUDO kill "$pd" 2>/dev/null || true
  [ -n "$xv" ] && kill "$xv" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

Xvfb "$display" -ac -screen 0 "${size}x24" >/dev/null 2>&1 &
xv=$!
sleep 1
export DISPLAY=$display
$SUDO env DISPLAY="$display" plymouthd --no-daemon --debug --debug-file="$out.log" --mode=boot --graphical-boot \
  --kernel-command-line=splash >"$out.stdout" 2>&1 &
pd=$!
sleep 2
$SUDO env DISPLAY="$display" plymouth show-splash
sleep "${SETTLE:-3}"

# the daemon runs as root (a child of sudo, when there is one): measure the process that really is plymouthd
real=$(pgrep -x plymouthd | head -n1 || true)
c0=$(awk '{print $14+$15}' "/proc/${real:-$pd}/stat" 2>/dev/null || echo 0); t0=$(date +%s.%N)
i=1
while [ "$i" -le "$secs" ]; do
  import -window root "$out-$i.png"
  [ "$i" -lt "$secs" ] && sleep 1
  i=$((i + 1))
done
c1=$(awk '{print $14+$15}' "/proc/${real:-$pd}/stat" 2>/dev/null || echo 0); t1=$(date +%s.%N)
echo "$(echo "scale=1; ($c1-$c0)/($t1-$t0)" | bc)" >"$out.cpu"
echo "theme $name, $secs frames, plymouthd used $(cat "$out.cpu")% of one core (software X11 path: compares setups, does not predict a real boot)"
