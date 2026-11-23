#!/bin/sh
# Runs inside the test initramfs (a dracut pre-trigger hook). It returns at once (the boot must go on: udev has to find the display) and does its work in the
# background: waits for plymouthd (started by the distro's own boot chain, not by us), then tells the host what is on screen through the serial port (the
# host takes the screenshots and types the password through QEMU). Nothing here is part of the product.
(
  exec >/dev/ttyS0 2>&1
  say() { echo "MGTEST $*"; }
  n=0
  until pidof plymouthd >/dev/null 2>&1 && plymouth --ping 2>/dev/null; do
    n=$((n + 1))
    [ "$n" -gt 240 ] && { say "ready plymouthd=none"; exit 0; }
    sleep 0.5
  done
  say ready "plymouthd=$(pidof plymouthd | cut -d' ' -f1)"
  sleep 8
  say splash "plymouthd=$(pidof plymouthd | cut -d" " -f1)" # host: frames of the boot splash
  sleep 8
  (plymouth ask-for-password --prompt=Password --command=cat >/run/mgtest-answer 2>&1) &
  sleep 3
  say prompt "plymouthd=$(pidof plymouthd | cut -d" " -f1)" # host: empty field, types hunter2, photographs, backspaces, types xx, Enter
  sleep 14
  say "answer=$(cat /run/mgtest-answer 2>/dev/null)"
  plymouth update --status="message from the test" 2>/dev/null
  plymouth quit 2>/dev/null
  sleep 1
  plymouthd --mode=shutdown --attach-to-session --pid-file=/run/plymouth/pid
  plymouth show-splash
  sleep 4
  say shutdown "plymouthd=$(pidof plymouthd | cut -d" " -f1)" # host: photographs the shutdown screen
  sleep 8
  say "done"
  poweroff -f
) &
exit 0
