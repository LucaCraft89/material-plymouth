#!/bin/sh
# Runs inside the test initramfs (dracut, initramfs-tools or mkinitcpio, whichever the distro uses: ci/qemu/prepare.sh wraps it). It returns at once (the boot
# must go on: udev has to find the display) and does its work in the background: waits for plymouthd (started by the distro's own boot chain, not by us),
# then tells the host what is on screen through the serial port (the host takes the screenshots and types the password through QEMU). Not part of the product.
# Plain POSIX sh and the barest busybox (initramfs-tools has no pidof and no cut) only.
(
  exec >/dev/ttyS0 2>&1
  say() { echo "MGTEST $*"; }
  # pure sh: the busybox of initramfs-tools has neither pidof nor cut
  ply_pid() {
    for d in /proc/[0-9]*; do
      read -r c <"$d/comm" 2>/dev/null || continue
      [ "$c" = plymouthd ] && { echo "${d#/proc/}"; return; }
    done
  }
  n=0
  until [ -n "$(ply_pid)" ] && plymouth --ping 2>/dev/null; do
    n=$((n + 1))
    [ "$n" -gt 180 ] && { say "ready plymouthd=none"; exit 0; }
    sleep 1
  done
  say ready "plymouthd=$(ply_pid)"
  sleep 8
  say splash "plymouthd=$(ply_pid)" # host: frames of the boot splash
  sleep 8
  (plymouth ask-for-password --prompt=Password --command=cat >/run/mgtest-answer 2>&1) &
  sleep 3
  say prompt "plymouthd=$(ply_pid)" # host: empty field, types hunter2, photographs, backspaces, types xx, Enter
  sleep 14
  say "answer=$(cat /run/mgtest-answer 2>/dev/null)"
  plymouth update --status="message from the test" 2>/dev/null
  plymouth quit 2>/dev/null
  sleep 1
  plymouthd --mode=shutdown --attach-to-session --pid-file=/run/plymouth/pid
  plymouth show-splash
  sleep 4
  say shutdown "plymouthd=$(ply_pid)" # host: photographs the shutdown screen
  sleep 8
  say "done"
  echo o >/proc/sysrq-trigger
) &
exit 0
