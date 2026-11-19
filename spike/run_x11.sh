#!/bin/sh
# usage: run_x11.sh THEMEDIR SHOTPREFIX [SECONDS]  -- plays a Plymouth theme with the X11 renderer under Xvfb and takes screenshots
set -e
T=$1; P=$2; N=${3:-8}
ln -sfn "$T" /usr/share/plymouth/themes/material
mkdir -p /etc/plymouth
printf '[Daemon]\nTheme=material\nShowDelay=0\nDeviceTimeout=1\n' > /etc/plymouth/plymouthd.conf
pkill plymouthd 2>/dev/null || true; pkill Xvfb 2>/dev/null || true; sleep 0.5
Xvfb :99 -screen 0 1920x1080x24 >/dev/null 2>&1 &
sleep 1
export DISPLAY=:99
plymouthd --no-daemon --debug --debug-file="$P.log" --mode=boot --graphical-boot --kernel-command-line="splash" >"$P.out" 2>&1 &
PD=$!
sleep 1.5
plymouth show-splash
sleep ${SETTLE:-2}
import -window root "$P-1.png"
c0=$(awk '{print $14+$15}' /proc/$PD/stat); t0=$(date +%s.%N)
sleep "$N"
import -window root "$P-2.png"
c1=$(awk '{print $14+$15}' /proc/$PD/stat); t1=$(date +%s.%N)
echo "cpu ticks: $((c1-c0)) in $(echo "$t1 - $t0" | bc) s (100 ticks = 1 cpu-second)  =>  $(echo "scale=1; ($c1-$c0)/($t1-$t0)" | bc)% of one core"
echo "RSS: $(grep VmRSS /proc/$PD/status)"; plymouth quit 2>/dev/null || true; kill $PD 2>/dev/null || true; pkill Xvfb || true
