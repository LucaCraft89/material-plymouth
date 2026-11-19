"""PHASE 0 SPIKE (throw-away): render the assets of a Plymouth script theme and the script, to measure what the engine can do.
usage: make_theme.py OUTDIR [--wave dots|crop] [--bar indeterminate|progress] [--rot live|frames] [--debug]
Reads material-grub's code from a checkout (MG=/home/user/material-grub): palettes, shapes, font axes. 1920x1080 only."""

import math
import os
import subprocess
import sys
from pathlib import Path

MG = Path(os.environ.get("MG", "/home/user/material-grub"))
sys.path.insert(0, str(MG / "install/bin"))
import mgpalette  # noqa: E402
import mgscenes  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

args = sys.argv[1:]
out = Path(args[0])


def opt(n, d):
    return args[args.index(n) + 1] if n in args else d


SKIP = set(opt("--skip", "").split(","))
RATE = int(opt("--rate", "1"))  # update the slow shapes only every RATE-th frame, staggered
WAVE, BAR, ROT, DEBUG = opt("--wave", "dots"), opt("--bar", "indeterminate"), opt("--rot", "live"), "--debug" in args
W, H = 1920, 1080
p = mgpalette.scheme(opt("--seed", "#294172"), dark=True)  # Fedora blue, dark
hexc = mgscenes.hexc
out.mkdir(parents=True, exist_ok=True)


def font(size, wght=800, wdth=135, rond=60):
    f = ImageFont.truetype(str(MG / "fonts/GoogleSansFlex-VF.ttf"), size)
    want = {"optical": min(144, size * 0.75), "width": wdth, "weight": wght, "roundness": rond, "grade": 0, "slant": 0}
    vals = []
    for ax in f.get_variation_axes():
        n = ax["name"].decode() if isinstance(ax["name"], bytes) else ax["name"]
        v = next((want[k] for k in want if k in n.lower()), ax["default"])
        vals.append(min(max(v, ax["minimum"]), ax["maximum"]))
    f.set_variation_by_axes(vals)
    return f


def save(im, name):
    im.save(out / name, optimize=True)
    return im


def shape(name, n, color):
    im = Image.new("RGBA", (n, n), hexc(color) + (255,))
    im.putalpha(mgscenes.poly_mask(n, mgscenes.SHAPES[name]))
    return im


def rrect(w, h, r, color, ss=4):
    im = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle([0, 0, w * ss - 1, h * ss - 1], radius=r * ss, fill=color)
    return im.resize((w, h), Image.LANCZOS)


def svg_glyph(path, size, color):
    png = subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size), "-a", str(path)], capture_output=True, check=True).stdout
    import io

    a = Image.open(io.BytesIO(png)).convert("RGBA").getchannel("A")
    im = Image.new("RGBA", a.size, color)
    im.putalpha(a)
    return im


# ---- static assets (design px at 1080 high) ----
save(shape("cookie", 620, p["surfaceContainerHigh"]), "bg_cookie.png")
save(shape("sunny", 460, p["surfaceContainer"]), "bg_sunny.png")
save(shape("clover", 300, p["surfaceContainer"]), "bg_clover.png")
save(shape("cookie", 230, p["primaryContainer"]), "cookie.png")
tux = svg_glyph(MG / "vendor/font-logos/src/vectors/tux.svg", 120, (0x14, 0x14, 0x18, 255))
save(tux, "logo.png")
hero = Image.new("RGBA", (600, 320), (0, 0, 0, 0))
hero.alpha_composite(rrect(600, 320, 160, hexc(p["surfaceContainerHigh"]) + (255,)))
hero.alpha_composite(rrect(560, 280, 140, hexc(p["primaryContainer"]) + (255,)), (20, 20))
g = svg_glyph(MG / "vendor/font-logos/src/vectors/fedora.svg", 230, hexc(p["onPrimaryContainer"]) + (255,))
hero.alpha_composite(g, ((600 - g.width) // 2, (320 - g.height) // 2))
save(hero, "hero.png")
f = font(150)
tw = int(f.getlength("Fedora Linux")) + 40
t = Image.new("RGBA", (tw, 200), (0, 0, 0, 0))
ImageDraw.Draw(t).text((tw // 2, 100), "Fedora Linux", font=f, fill=hexc(p["primary"]) + (255,), anchor="mm")
save(t, "title.png")
fp = font(28, 560, 104, 0)
pills = []
for txt, acc in (("Fedora Linux 44", True), ("Workstation", False)):
    w = int(fp.getlength(txt)) + 56
    im = rrect(w, 58, 29, hexc(p["primaryContainer" if acc else "surfaceContainerHigh"]) + (255,))
    ImageDraw.Draw(im).text((w // 2, 30), txt, font=fp, fill=hexc(p["onPrimaryContainer" if acc else "onSurface"]) + (255,), anchor="mm")
    pills.append(im)
row = Image.new("RGBA", (sum(i.width for i in pills) + 14, 58), (0, 0, 0, 0))
x = 0
for i in pills:
    row.alpha_composite(i, (x, 0))
    x += i.width + 14
save(row, "pills.png")

# ---- the wavy bar: 560 wide, stroke 10, amplitude 6, wavelength 44 ----
BW, STROKE, AMP, LAM, STEP = 560, 10, 6, 44, 2
dot = rrect(STROKE, STROKE, STROKE // 2, hexc(p["primary"]) + (255,))
save(dot, "dot.png")
save(rrect(BW, STROKE, STROKE // 2, hexc(p["surfaceContainerHighest"] if "surfaceContainerHighest" in p else p["surfaceContainerHigh"]) + (255,)), "track.png")
save(rrect(STROKE, STROKE, STROKE // 2, hexc(p["primary"]) + (255,)), "stop.png")
if WAVE == "crop":  # one long wave, drawn with supersampling; the script crops it at an offset (the phase) and a length (the progress)
    SS, Hs = 4, 2 * AMP + STROKE + 4
    L = BW + LAM
    im = Image.new("RGBA", (L * SS, Hs * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pts = [(x * SS, (Hs / 2 + AMP * math.sin(2 * math.pi * x / LAM)) * SS) for x in range(0, L + 1)]
    d.line(pts, fill=hexc(p["primary"]) + (255,), width=STROKE * SS, joint="curve")
    save(im.resize((L, Hs), Image.LANCZOS), "wave.png")

# ---- extras under test: morph frames and a password prompt ----
MORPH = int(opt("--morph", "0"))  # number of frames per shape-to-shape transition (0 = off)
if MORPH:
    names = ["cookie", "flower", "sunny", "clover"]
    k = 0
    for a, b in zip(names, names[1:] + names[:1]):
        for i in range(MORPH):
            u = i / MORPH
            u = u * u * (3 - 2 * u)
            fn = (lambda fa, fb, uu: (lambda t: (1 - uu) * fa(t) + uu * fb(t)))(mgscenes.SHAPES[a], mgscenes.SHAPES[b], u)
            im = Image.new("RGBA", (400, 400), hexc(p["primaryContainer"]) + (255,))
            im.putalpha(mgscenes.poly_mask(400, fn))
            save(im, f"morph{k}.png")
            k += 1
    NMORPH = k
PW = "--password" in args
if PW:
    save(rrect(560, 72, 36, hexc(p["surfaceContainerHigh"]) + (255,)), "pw_field.png")
    save(rrect(20, 20, 10, hexc(p["onSurface"]) + (255,)), "pw_dot.png")
    ft = font(28, 520, 105, 0)
    im = Image.new("RGBA", (560, 50), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((280, 25), "Enter the disk password", font=ft, fill=hexc(p["onSurfaceVariant"]) + (255,), anchor="mm")
    save(im, "pw_label.png")

# ---- script ----
col = lambda c: ", ".join(f"{v / 255:.4f}" for v in hexc(c))  # noqa: E731
cx = W // 2
script = f'''# spike: wave={WAVE} bar={BAR} rot={ROT}
Window.SetBackgroundTopColor({col(p["surface"])});
Window.SetBackgroundBottomColor({col(p["surface"])});
W = Window.GetWidth(); H = Window.GetHeight();
img.cookie_bg = Image("bg_cookie.png");  img.sunny = Image("bg_sunny.png"); img.clover = Image("bg_clover.png");
img.cookie = Image("cookie.png"); img.hero = Image("hero.png"); img.logo = Image("logo.png");
s_cookie_bg = Sprite(img.cookie_bg); s_sunny = Sprite(img.sunny); s_clover = Sprite(img.clover);
s_cookie = Sprite(img.cookie); s_logo = Sprite(img.logo); s_hero = Sprite(img.hero);
s_title = Sprite(Image("title.png")); s_pills = Sprite(Image("pills.png"));
s_cookie_bg.SetZ(1); s_sunny.SetZ(1); s_clover.SetZ(1); s_hero.SetZ(5); s_title.SetZ(6); s_pills.SetZ(6); s_cookie.SetZ(7); s_logo.SetZ(8);
s_logo.SetPosition({W - 150 - 60}, {140 - 60}, 8);
s_title.SetPosition({cx} - s_title.GetImage().GetWidth() / 2, 590 - 100, 6);
s_pills.SetPosition({cx} - s_pills.GetImage().GetWidth() / 2, 672, 6);
BX = {cx - BW // 2}; BY = 755; BW = {BW}; STEP = {STEP}; NDOT = {BW // STEP}; AMP = {AMP}; LAM = {LAM}; STROKE = {STROKE};
img.track = Image("track.png"); s_track = Sprite(img.track); s_track.SetPosition(BX, BY + 6, 5);
img.dot = Image("dot.png");
img.stop = Image("stop.png"); s_stop = Sprite(img.stop); s_stop.SetPosition(BX + BW - STROKE, BY + 6, 6);
'''
if WAVE == "dots":
    script += '''for (i = 0; i < NDOT; i++) {{ dots[i] = Sprite(img.dot); dots[i].SetZ(6); dots[i].SetOpacity(0); }}
'''.replace("{{", "{").replace("}}", "}")
else:
    script += 'img.wave = Image("wave.png"); s_wave = Sprite(); s_wave.SetZ(6);\n'
script += '''frame = 0; fps_text = Sprite(); fps_text.SetZ(20);
fun bar(t) {
  if ("''' + BAR + '''" == "progress") { s = 0; e = (t % 12) / 12 * BW; }
  else { u = (t % 2.4) / 2.4; s = Math.Max(0, (u * 1.38 - 0.38)) * BW; e = Math.Min(1, u * 1.38) * BW; }
  phase = t * 2 * Math.Pi * 1.1;
'''
if WAVE == "dots":
    script += '''  for (i = 0; i < NDOT; i++) {
    x = i * STEP;
    if (x >= s && x <= e) { dots[i].SetPosition(BX + x, BY + 6 + AMP * Math.Sin(2 * Math.Pi * x / LAM - phase), 6); dots[i].SetOpacity(1); }
    else dots[i].SetOpacity(0);
  }
'''
else:
    script += '''  off = Math.Int((phase / (2 * Math.Pi) % 1) * LAM);
  w = Math.Max(1, Math.Int(e - s));
  s_wave.SetImage(img.wave.Crop(LAM - off, 0, Math.Min(w, BW), img.wave.GetHeight()));
  s_wave.SetPosition(BX + s, BY, 6);
'''
script += '''}
fun refresh() {
  frame++;
  t = frame / 50;
'''
R = RATE
BARR = int(opt("--barrate", "2"))
script += f'''  if (frame % {R} == 0) {{ s_cookie_bg.SetImage(img.cookie_bg.Rotate(t * 0.12)); s_cookie_bg.SetPosition({cx} - {int(W * 0.36)} - 310 + 14 * Math.Sin(t * 0.4), {H - 120} - 310 + 10 * Math.Cos(t * 0.33), 1); }}
  if (frame % {R} == {1 % R}) {{ s_sunny.SetImage(img.sunny.Rotate(-t * 0.18)); s_sunny.SetPosition({cx} + {int(W * 0.34)} - 230 + 12 * Math.Cos(t * 0.31), {H - 60} - 230 + 14 * Math.Sin(t * 0.37), 1); }}
  if (frame % {R} == {2 % R}) {{ s_clover.SetImage(img.clover.Rotate(t * 0.25)); s_clover.SetPosition({cx} - {int(W * 0.29)} - 150 + 10 * Math.Sin(t * 0.5), 150 - 150 + 8 * Math.Cos(t * 0.45), 1); }}
  if (frame % {R} == {3 % R}) {{ s_cookie.SetImage(img.cookie.Rotate(t * 0.5)); s_cookie.SetPosition({W - 150} - 115, 140 - 115, 7); }}
'''
if "hero" not in SKIP:
    script += f'''  if (frame % {2 * R} == {R // 2}) {{ k = 1 + 0.02 * Math.Sin(t * 1.6);
    s_hero.SetImage(img.hero.Scale(Math.Int(600 * k), Math.Int(320 * k)));
    s_hero.SetPosition({cx} - Math.Int(300 * k), 360 - Math.Int(160 * k), 5); }}
'''
if "bar" not in SKIP:
    script += f'  if (frame % {BARR} == 0) bar(t);\n'
if MORPH:
    script += f'''  if (frame % 3 == 0) {{ s_morph.SetImage(morph[(frame / 3) % {NMORPH}]); }}
'''
script += '}\n'
if MORPH:
    pre = f'for (i = 0; i < {NMORPH}; i++) morph[i] = Image("morph" + i + ".png");\ns_morph = Sprite(morph[0]); s_morph.SetPosition(40, 300, 3);\n'
    script = script.replace("frame = 0; fps_text", pre + "frame = 0; fps_text", 1)
if PW:
    script += f'''
img.pwf = Image("pw_field.png"); img.pwd = Image("pw_dot.png"); img.pwl = Image("pw_label.png");
s_pwf = Sprite(img.pwf); s_pwl = Sprite(img.pwl); s_pwf.SetOpacity(0); s_pwl.SetOpacity(0);
s_pwf.SetPosition({cx - 280}, 755 - 20, 9); s_pwl.SetPosition({cx - 280}, 755 - 70, 9);
for (i = 0; i < 40; i++) {{ pwdots[i] = Sprite(img.pwd); pwdots[i].SetOpacity(0); pwdots[i].SetZ(10); }}
fun pw_show(prompt, bullets) {{
  s_pwf.SetOpacity(1); s_pwl.SetOpacity(1);
  for (i = 0; i < 40; i++) {{ if (i < bullets) {{ pwdots[i].SetPosition({cx - 280} + 36 + i * 30, 755 - 20 + 26, 10); pwdots[i].SetOpacity(1); }} else pwdots[i].SetOpacity(0); }}
}}
fun pw_hide() {{ s_pwf.SetOpacity(0); s_pwl.SetOpacity(0); for (i = 0; i < 40; i++) pwdots[i].SetOpacity(0); }}
Plymouth.SetDisplayPasswordFunction(pw_show);
Plymouth.SetDisplayNormalFunction(pw_hide);
'''
script += 'Plymouth.SetRefreshFunction(refresh);\n'
(out / "material.script").write_text(script)
(out / "material.plymouth").write_text(
    f"[Plymouth Theme]\nName=Material spike\nModuleName=script\n\n[script]\nImageDir={out}\nScriptFile={out}/material.script\n"
)
print("theme in", out, "size", sum(f.stat().st_size for f in out.iterdir()) // 1024, "KiB")
