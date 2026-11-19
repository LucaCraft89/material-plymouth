#!/bin/sh
# usage: run_pw.sh THEMEDIR SHOTPREFIX -- types into Plymouth's password prompt (X11 renderer) and screenshots it
T=$1; P=$2
ln -sfn "$T" /usr/share/plymouth/themes/material
printf '[Daemon]\nTheme=material\nShowDelay=0\nDeviceTimeout=1\n' > /etc/plymouth/plymouthd.conf
pkill plymouthd 2>/dev/null; pkill Xvfb 2>/dev/null; sleep 0.5
Xvfb :99 -screen 0 1920x1080x24 >/dev/null 2>&1 &
sleep 1; export DISPLAY=:99
plymouthd --no-daemon --debug --debug-file="$P.log" --mode=boot --graphical-boot --kernel-command-line="splash" >"$P.out" 2>&1 &
PD=$!; sleep 1.5; plymouth show-splash; sleep 1.5
import -window root "$P-0.png"
(plymouth ask-for-password --prompt="Enter" --command="cat" > "$P.answer" 2>&1 &)
sleep 1.5
import -window root "$P-1.png"
xdotool search --class . 2>/dev/null | head -3 > "$P.wins"
xdotool type --delay 80 "hunter2" 2>>"$P.err"
sleep 1
import -window root "$P-2.png"
xdotool key BackSpace BackSpace; sleep 0.5
import -window root "$P-3.png"
xdotool type "x"; xdotool key Return; sleep 1
import -window root "$P-4.png"
echo "answer: $(cat $P.answer)"
plymouth quit 2>/dev/null; kill $PD 2>/dev/null; pkill Xvfb
