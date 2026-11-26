#!/bin/sh
# Plays a Plymouth theme with the X11 renderer under Xvfb and records what the screen shows as an animated GIF (the real animation: the script runs in real
# Plymouth, nothing is simulated). usage: ci/record_gif.sh THEME OUT.gif [SECONDS] [WxH] [OUTWIDTH]
#   THEME  the path of a theme directory (NAME/NAME.plymouth inside) or the name of an installed one      env: FPS (default 10), PLY_MODE (boot, shutdown)
# Needs: plymouth, plymouth-x11 (the renderer), Xvfb, ffmpeg with x11grab. Root or sudo (the theme is linked into /usr/share/plymouth/themes). A throw-away
# container or a CI runner, not a machine you boot from.
set -eu
theme=$1; out=$2; secs=${3:-6}; size=${4:-1280x720}; width=${5:-640}
SUDO=""; [ "$(id -u)" = 0 ] || SUDO=sudo
display=${XVFB_DISPLAY:-:98}
if [ -d "$theme" ]; then
  name=$(basename "$theme")
  [ -f "$theme/$name.plymouth" ] || { echo "record_gif: $theme/$name.plymouth is missing" >&2; exit 2; }
  $SUDO ln -sfn "$(cd "$theme" && pwd)" "/usr/share/plymouth/themes/$name"
else
  name=$theme
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
$SUDO env DISPLAY="$display" plymouthd --no-daemon --mode="${PLY_MODE:-boot}" --graphical-boot --kernel-command-line=splash >"$out.plymouthd" 2>&1 &
pd=$!
sleep 2
$SUDO env DISPLAY="$display" plymouth show-splash
sleep "${SETTLE:-3}"
# record losslessly for the length asked (-t BEFORE -i: it bounds the capture), then make the GIF from the file with one palette for the whole clip so the
# colours stay steady; the frames are what the screen really showed
raw="$out.raw.mkv"
ffmpeg -hide_banner -loglevel error -y -f x11grab -draw_mouse 0 -framerate "${FPS:-10}" -video_size "$size" -t "$secs" -i "$display" -c:v ffv1 "$raw"
ffmpeg -hide_banner -loglevel error -y -i "$raw" \
  -vf "scale=$width:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4" -loop 0 "$out"
rm -f "$raw"
rm -f "$out.plymouthd"
echo "recorded $out ($(wc -c <"$out") bytes)"
