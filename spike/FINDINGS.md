# Phase 0 spike: what Plymouth's script engine can do

Throw-away code (`make_theme.py`, `run_x11.sh`, `run_pw.sh`). Nothing here ships. It renders a 1920x1080 theme with material-grub's own palette, shape and font code, and plays it with Plymouth 24.004.60 (Ubuntu 24.04) using the **X11 renderer under Xvfb** in the cloud sandbox. Plan: `docs/plans/plymouth.md` in material-grub.

## Verdict
The script engine **can** do the design: the hero, title and pills where GRUB has them, the rotating and drifting background shapes, the rotating cookie with an upright logo, the hero pulse, a smooth round-capped wavy bar (indeterminate and progress), shape-morph frames and a working disk-password prompt. The risk is **CPU**, not capability: naive per-frame animation is too expensive, and a cadence budget is needed.

## What was shown (see `shots/`)
| Item | Result |
|---|---|
| `Image.Rotate` | Same output size as the input (620x620 stays 620x620), crisp edges, no visible artefacts. A shape inside its inscribed circle needs no padding. |
| `Image.Crop`, `Image.Tile`, `Image.Scale`, `Image.Text` | Exist in this version (24.004.60); `Sprite.SetOpacity/SetImage/SetPosition/SetZ` too. No clock function: time is a frame counter (about 50 Hz target). |
| Wave, per-dot sprites (`Math.Sin`) | Smooth, round caps, supports a travelling segment (indeterminate) and a growing one (progress). Looks right. |
| Wave, one long strip cropped with `Image.Crop` | Cheap, but **flat cut ends** and tick artefacts. Worse. Idea to try: crop for the body plus two round-cap dot sprites at the ends. |
| Shape morph (24 frames of 400x400) | Works by swapping pre-rendered images; +260 KiB on disk, about +15 MB RAM, no measurable CPU change. |
| Password prompt | `Plymouth.SetDisplayPasswordFunction` gets the bullet count; bullets appear as typed, backspace removes them, Enter delivers the answer (checked: typed `hunter2`, two backspaces, `x`, got `huntex`), `SetDisplayNormalFunction` brings the bar back. The label overlapped the pills only because the spike has no layout. |
| Assets | Whole scene (shapes, hero, title, pills, bar) about 110 KiB of PNG at 1080p; with password prompt and morph about 370 KiB. |
| Memory | plymouthd about 100 MB resident in this setup, mostly the daemon and X libraries; the theme adds about 2 MB (more with morph frames). |

## CPU (plymouthd, one core = 100%, 15 s windows after a 6 s settle, X11 renderer under Xvfb)
| Configuration | CPU |
|---|---|
| Everything animated **every frame** (4 shapes rotating live + drift, hero pulse, wave) | about 93%; frame rate fell to about 40 instead of 50 (measured once, by counting the overlay frames) |
| Same, shapes only, every frame | about 88% |
| Shapes rotate/drift **staggered**, one shape per frame, every 4th frame each; wave every 2nd frame; hero pulse every 8th | **about 39%** |
| Same with shapes every 8th frame | **about 25%** |
| Nothing moving (earlier, shorter run) | about 8% |

Conclusion: **rotation (`Image.Rotate`) and moving large sprites is what costs.** The shapes turn about 7 degrees a second, so updating each only a few times a second is visually enough; stagger the updates so no frame does more than one rotation. This is the motion budget the design needs.

## Caveats (what this does not show)
- **Not real hardware or the DRM path.** The X11 renderer under software Xvfb has different costs from DRM/KMS on a real GPU or a VM framebuffer. The numbers rank options; they do not predict a real boot.
- **1080p only.** Cost grows with the pixels moved; at 2160 expect roughly 4x for the same cadence. Not measured: the generator uses fixed 1080 coordinates. A per-resolution budget (lower cadence, fewer moving shapes) is needed and must be measured.
- **Stills only.** Smoothness of the stepped rotation (a few updates a second) was not judged in motion, only through frame counts and screenshots. It needs looking at on a real display.
- **No initramfs, no real boot, no real BGRT.** The firmware logo is a Tux stand-in; hero glyph and title are Fedora's.
- Frame rate was measured once; the other runs measured CPU only.
- One Plymouth version (24.004.60). Fedora, Arch and openSUSE ship others.

## Decisions this suggests for the plan
1. Wave: per-dot sprites (or crop plus round-cap dots), updated every 2nd frame.
2. Background shapes and the cookie: rotation, drift and pulse on a **staggered, low cadence**, per-resolution budget, a conf level `PLYMOUTH_MOTION=full|calm|off` that changes the cadence.
3. Morph: pre-rendered frames, kept to one or two shapes per scene, within a RAM budget.
4. Password prompt: feasible as designed; layout must hide or move the pills.
5. Validate on a real DRM/VM framebuffer (QEMU tier) before fixing the cadence numbers.
