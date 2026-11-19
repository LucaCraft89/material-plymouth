# CI

`.github/workflows/ci.yml` runs on every pull request and on `main`. The plan behind it (four tiers, all five distros) is `docs/plans/plymouth.md` in [material-grub](https://github.com/LucaCraft89/material-grub); this is what exists so far.

| Job | Tier | What it proves |
|---|---|---|
| Lint | | `ruff` (check and format), `shellcheck` and `actionlint`. |
| Unit tests (Python 3.8 and 3.13) | 1 | The repository's own tests, and the **contract** with material-grub: a checkout of material-grub (`MATERIAL_GRUB_REF`, see the top of the workflow) must have the plugin API this part is written for (`tests/test_contract.py`; a missing or incompatible one fails the job). |
| Consistency with GRUB (built package) | 1 | Builds material-grub's package from the same ref and runs the whole suite with `REQUIRE_CORE=1`: the Plymouth layers are pixel-identical to GRUB's own drawing (hero, title, pills, cookie, logo, background shapes), and every customisation reaches them (distro colours, one seed colour, names, icons, `COOKIE`, `LOGO`, screen sizes). Locally: build the package in a material-grub checkout (`python scripts/package.py --res 1920x1080`) and run the tests with `MATERIAL_GRUB` pointing at it; without a package those tests skip. |
| Plymouth in Xvfb (harness) | 2 | `ci/xvfb_play.sh` plays a theme with Plymouth's X11 renderer under Xvfb and takes a screenshot a second; `ci/check_frames.py` checks they have the right size, are not blank, and (for an animated theme) that something moves. Today it runs on Ubuntu's stock `spinner` theme to prove the harness; the Material theme uses the same script once it exists. |
| Distro probe (Fedora, Ubuntu, Debian, Arch, openSUSE) | 3, first part | `ci/probe-distro.sh` installs Plymouth and the initramfs tooling in a fresh container and writes down what is really there: package names, the script plugin, the initramfs integration (dracut, initramfs-tools or mkinitcpio), how the default theme is chosen, the Python version. It fails when an essential is missing. The report is in the job summary and an artifact. |
| CI passed | | One name for branch protection to require. |

**Not here yet** (they need code that does not exist yet): the install and initramfs tests per distro (build the initramfs, check it lists the theme, rollback on a forced failure), the QEMU boots per distro (GRUB, the hand-over, the splash, the password prompt, shutdown), the consistency matrix against material-grub, and the upgrade matrix.

## Running it locally

```sh
pip install ruff shellcheck-py actionlint-py pillow pyyaml
ruff check . && ruff format --check . && shellcheck -x --severity=warning ci/*.sh && actionlint
MATERIAL_GRUB=../material-grub REQUIRE_CONTRACT=1 python3 -m unittest discover -s tests -v
# the harness (needs plymouth, plymouth-x11, plymouth-theme-spinner, xvfb, imagemagick, bc; it links the theme into /usr/share/plymouth and writes
# /etc/plymouth, so use a throw-away machine or container)
ci/xvfb_play.sh spinner build/xvfb/spinner 6 && python3 ci/check_frames.py --size 1920x1080 --moving build/xvfb/spinner-*.png
```

The material-grub ref: the `material_grub_ref` input of a manual run, else the repository variable `MATERIAL_GRUB_REF`, else the default in the workflow (the branch with the plugin API until it is merged into material-grub's `release/0.8.0`).
