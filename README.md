# Material Plymouth

[![CI](https://github.com/LucaCraft89/material-plymouth/actions/workflows/ci.yml/badge.svg)](https://github.com/LucaCraft89/material-plymouth/actions/workflows/ci.yml)

A Material 3 Expressive Plymouth boot splash that continues the [Material GRUB](https://github.com/LucaCraft89/material-grub) theme: the same style, colours, per-distro customisation and animated shapes, with the wavy progress bar, managed from Material GRUB's settings and GUI.

**Status: under construction, nothing released.** The plan lives in [material-grub/docs/plans/plymouth.md](https://github.com/LucaCraft89/material-grub/blob/ccr-d8df62d1-7vgvjn/docs/plans/plymouth.md). Nothing here is usable yet.

Code: MIT, see [LICENSE](LICENSE).

CI: see [ci/README.md](ci/README.md).

## What it does

- The theme is drawn with Material GRUB's own renderer, so it is the GRUB scene continued: the same distro, colours, names, icons, one-seed colour, `COOKIE` and `LOGO`, with animated shapes and cookie, a Material 3 Expressive wavy progress bar, a disk-password prompt and shutdown and update messages. Four styles (rail and clean, list, split), motion levels `full`, `calm` and `off`.
- It is fitted to the screen it runs on: built for the display's native size, and scaled to fit and centred (never a small scene in a corner) when the screen turns out to be another size.
- `material-grub plymouth apply` renders it, installs it, makes it the default, makes sure Plymouth starts (asks before touching the kernel command line or the mkinitcpio hooks), rebuilds every initramfs and checks each one. **Any failure puts everything back**; `remove` undoes exactly what `apply` did. `status` and `build DIR` (render only, to look at it) complete the command.

## Install

Not published yet (it comes out together with material-grub 0.8.0, which it needs: the plugin API). The three package definitions are in `packaging/` (rpm, deb, Arch) and are built and tested in CI. **Installing the package does not change how your system boots**: it puts the code and the plugin manifest in place and nothing else. Turning the splash on rebuilds the initramfs and may edit the kernel command line, so it is your own step: `material-grub plymouth apply` (or the Boot splash page of the GUI). Upgrading re-applies a theme that was applied before (never touching the kernel command line); removing the package takes the theme out first.

From a checkout, without a package: `sudo sh packaging/install-tree.sh . / /usr/local`, then `material-grub plymouth apply`.
- Fedora and openSUSE (dracut), Debian and Ubuntu (initramfs-tools) and Arch (mkinitcpio) are the targets. So far only fake machines and Docker probes have been used: **no real boot has been tested.**

