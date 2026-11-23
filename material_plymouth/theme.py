"""Builds the Plymouth theme directory (assets and script) from a resolved look. The pictures are layers.py's; this file lays them out per style and writes the
script that moves them. Everything is drawn here, at apply time: nothing is rendered in the initramfs, and no font is needed there (every string is a picture).

What moves, how often (the Phase 0 spike measured that rotating and moving big sprites is what costs: the cadence is the budget):
  full   shapes and cookies turn and drift one per frame in turn (each every RATE frames), the hero card pulses, the row cookie morphs, the wave runs
  calm   the same, slower and without the pulse and the morph
  off    nothing moves; the wave is a still segment (PLYMOUTH_BAR=progress still fills as the boot progresses)
"""

import math
import re
import shutil
from pathlib import Path

from PIL import Image

from . import layers as Ly

FPS = 50  # Plymouth calls the refresh function about this often
SHAPE_NAMES = ("cookie", "flower", "sunny", "clover")


def cadence(motion, H):
    """Frames between two updates of the same thing. Bigger screens move more pixels: the cadence is halved for them."""
    big = 2 if H >= 1800 else 1
    if motion == "off":
        return {"rate": 0, "bar": 0, "pulse": 0, "morph": 0}
    if motion == "calm":
        return {"rate": 8 * big, "bar": 3 * big, "pulse": 0, "morph": 0}
    return {"rate": 4 * big, "bar": 2 * big, "pulse": 8 * big, "morph": 6}


def morph_frames(look, size, color, per=6):
    """Pre-rendered frames of the cookie turning into the flower, the sunny shape, the clover and back (smoothstep), as M3 Expressive loaders do."""
    sh = look.core.mgscenes
    hexc, poly_mask, shapes = sh.hexc, sh.poly_mask, sh.SHAPES
    out = []
    for a, b in zip(SHAPE_NAMES, SHAPE_NAMES[1:] + SHAPE_NAMES[:1]):
        for i in range(per):
            u = i / per
            u = u * u * (3 - 2 * u)
            fa, fb = shapes[a], shapes[b]
            im = Image.new("RGBA", (size, size), hexc(color) + (255,))
            im.putalpha(poly_mask(size, lambda t, fa=fa, fb=fb, u=u: (1 - u) * fa(t) + u * fb(t)))
            out.append(im)
    return out


def n(v):
    """A number for the script."""
    return repr(round(v, 4)) if isinstance(v, float) else str(int(v))


def plan(look, W, H, motion="full", bar="indeterminate"):
    """The scene as data: static sprites, rotating sprites, the bar's place, the slot for messages. Returns a dict (pictures included) the writers use."""
    R, p = look.R, look.palette
    u = R.u
    style = (
        look.style if look.style in ("list", "split") else "rail"
    )  # clean's neighbouring panels are navigation: in Plymouth it is the rail scene
    cad = cadence(motion, H)
    static, rot, pics = [], [], {}  # static: (name, z); rot: dicts; pics: name -> (image, x, y)
    cx = W // 2

    def put(name, layer, z, group=None):
        if layer is None or layer[0] is None:
            return
        pics[name] = layer
        static.append((name, z, group))

    def spin(name, layer, speed, z, drift=(0, 0, 0, 0), morph_color=None):
        im, x, y = layer
        pics[name] = layer
        item = {
            "name": name,
            "cx": x + im.width / 2,
            "cy": y + im.height / 2,
            "half": im.width / 2,
            "sp": speed,
            "z": z,
            "d": drift,
            "nm": 0,
        }
        if morph_color and cad["morph"]:
            frames = morph_frames(look, im.width, morph_color, 6)
            for i, f in enumerate(frames):
                pics[f"{name}_m{i}"] = (f, x, y)
            item["nm"] = len(frames)
        rot.append(item)

    for name, speed, drift in (
        ("bg_cookie", 0.12, (14, 10, 0.4, 0.33)),
        ("bg_sunny", -0.18, (12, 14, 0.31, 0.37)),
        ("bg_clover", 0.25, (10, 8, 0.5, 0.45)),
    ):
        spin(
            name, Ly.background(look, W, H)[name], speed, 1, tuple(v * R.S if i < 2 else v for i, v in enumerate(drift))
        )
    if look.cookie:
        spin("cookie", Ly.cookie(look, W, H), 0.5, 7)
        put("logo", Ly.logo(look, W, H), 8)

    if style == "rail":
        put("card", Ly.card(look, W, H), 5)
        put("title", Ly.title(look, W, H), 6)
        put("pills", Ly.pills(look, W, H), 6, "pills")
        bx, by = cx - u(Ly.BAR_W) // 2, u(755)
        slot = (cx, u(701))
    else:
        x0 = None if style == "list" else R.split_x(W)
        r = Ly.row(look, W, H, x0)
        g = r["geometry"]
        spin("row_cookie", r["row_cookie"], 0.5, 3, morph_color=p["primary"])
        put("row_glyph", r["row_glyph"], 4)
        put("row_pill", r["row_pill"], 4)
        mid = g["x0"] + g["col"] // 2
        bx, by = mid - u(Ly.BAR_W) // 2, g["top"] + g["row"] + u(60)
        if style == "list":
            put("pills", Ly.list_pills(look, W, H, y=u(846), h=u(46)), 6, "pills")
            slot = (cx, u(846 + 23))
        else:
            sh = Ly.side_hero(look, W, H)
            if "side_cookie" in sh:
                spin("side_cookie", sh["side_cookie"], 0.2, 3, morph_color=p["primaryContainer"])
                put("side_glyph", sh["side_glyph"], 4)
            else:
                put("side_card", sh["side_card"], 4)
            put("side_title", sh["side_title"], 6)
            put("pills", Ly.list_pills(look, W, H, cx=round(W * 0.25), y=u(818), maxw=W * 0.42), 6, "pills")
            slot = (round(W * 0.25), u(818 + 29))
    return {
        "style": style, "cad": cad, "static": static, "rot": rot, "pics": pics, "bar": (bx, by), "slot": slot,
        "bar_mode": bar, "motion": motion, "W": W, "H": H,
    }  # fmt: skip


def script(look, pl):
    """The Plymouth script. Plain statements only (what the engine of Plymouth 22 to 26 runs); the numbers come from the plan."""
    R, p = look.R, look.palette
    u = R.u
    hexc = look.core.mgscenes.hexc
    W, H, cad, rot = pl["W"], pl["H"], pl["cad"], pl["rot"]
    bx, by = pl["bar"]
    sc = ", ".join(f"{v / 255:.4f}" for v in hexc(p["surface"]))
    s = []
    a = s.append
    a(f"# Material Plymouth: style {pl['style']}, motion {pl['motion']}, bar {pl['bar_mode']}. Generated; do not edit.")
    a(f"Window.SetBackgroundTopColor({sc});\nWindow.SetBackgroundBottomColor({sc});")
    a(f"W = {W}; H = {H};")
    # The scene is laid out in the pixels it was built for (W x H). On a screen of another size it is scaled to fit and centred (the background colour fills
    # what is left), so a mismatch never leaves a small scene in a corner with bare edges. ZS is 1 for a screen within 2% of the built size.
    a("ZS = Math.Min(Window.GetWidth() / W, Window.GetHeight() / H);")
    a("if (ZS > 0.98 && ZS < 1.02) ZS = 1;")
    a("ox = Math.Int((Window.GetWidth() - W * ZS) / 2); oy = Math.Int((Window.GetHeight() - H * ZS) / 2);")
    a("mode = Plymouth.GetMode();")
    a("frame = 0;")
    a(
        "fun load(file) { im = Image(file); if (ZS != 1) im = im.Scale(Math.Max(1, Math.Int(im.GetWidth() * ZS)), Math.Max(1, Math.Int(im.GetHeight() * ZS))); return im; }"
    )
    a("fun add(file, x, y, z) { sp = Sprite(load(file)); sp.SetPosition(ox + x * ZS, oy + y * ZS, z); return sp; }")
    for name, z, _g in pl["static"]:
        _im, x, y = pl["pics"][name]
        a(f's_{name} = add("{name}.png", {n(x)}, {n(y)}, {z});')
    # ---- turning shapes
    a(f"rot_n = {len(rot)};")
    for i, r in enumerate(rot):
        a(
            f'rot_img[{i}] = load("{r["name"]}.png"); rot_spr[{i}] = Sprite(rot_img[{i}]); rot_cx[{i}] = {n(r["cx"])}; rot_cy[{i}] = {n(r["cy"])}; rot_half[{i}] = {n(r["half"])} * ZS; rot_deco[{i}] = {1 if r["name"].startswith("bg_") else 0};'
        )
        a(
            f"rot_sp[{i}] = {n(r['sp'])}; rot_z[{i}] = {r['z']}; rot_dx[{i}] = {n(r['d'][0])}; rot_dy[{i}] = {n(r['d'][1])}; rot_fx[{i}] = {n(r['d'][2])}; rot_fy[{i}] = {n(r['d'][3])}; rot_nm[{i}] = {r['nm']};"
        )
        for k in range(r["nm"]):
            a(f'rot_morph[{i * 100 + k}] = load("{r["name"]}_m{k}.png");')
    a("""fun place_rot(i, t) {
  if (rot_nm[i] > 0) base = rot_morph[i * 100 + Math.Int(frame / MORPH_EVERY) % rot_nm[i]]; else base = rot_img[i];
  rot_spr[i].SetImage(base.Rotate(t * rot_sp[i]));
  rot_spr[i].SetPosition(ox + ZS * (rot_cx[i] + rot_dx[i] * Math.Sin(t * rot_fx[i])) - rot_half[i], oy + ZS * (rot_cy[i] + rot_dy[i] * Math.Cos(t * rot_fy[i])) - rot_half[i], rot_z[i]);
}""")
    a(
        f"RATE = {max(cad['rate'], len(rot))}; BAR_EVERY = {cad['bar']}; PULSE = {cad['pulse']}; MORPH_EVERY = {cad['morph'] or 1};"
    )
    a("for (i = 0; i < rot_n; i++) place_rot(i, 0);")
    a(
        "if (ZS < 0.5) { for (i = 0; i < rot_n; i++) if (rot_deco[i]) rot_spr[i].SetOpacity(0); }   # a very small screen: no decoration, just the content"
    )
    # ---- the wavy bar
    BW, STROKE, AMP, LAM, STEP = u(Ly.BAR_W), u(Ly.BAR_STROKE), u(Ly.BAR_AMP), u(Ly.BAR_LAM), u(Ly.BAR_STEP)
    ndot = BW // STEP
    a(
        f"BX = {n(bx)}; BY = {n(by)}; BW = {n(BW)}; STROKE = {n(STROKE)}; AMP = {n(AMP)}; LAM = {n(LAM)}; STEP = {n(STEP)}; NDOT = {ndot};"
    )
    a(f"PROGRESS = {1 if pl['bar_mode'] == 'progress' else 0}; shown = 0; target = 0; pw_on = 0;")
    a('img_dot = load("dot.png");')
    a('s_track = add("track.png", BX, BY, 5); s_stop = add("stop.png", BX + BW - STROKE, BY, 6);')
    a("for (i = 0; i < NDOT; i++) { dots[i] = Sprite(img_dot); dots[i].SetZ(6); dots[i].SetOpacity(0); }")
    a("""fun on_progress(duration, progress) { if (progress > target) target = progress; }
Plymouth.SetBootProgressFunction(on_progress);
fun bar(t) {
  if (pw_on) return;
  if (PROGRESS) { if (target > shown) shown = shown + (target - shown) * 0.08; s0 = 0; e0 = shown * BW; }
  else if (BAR_EVERY == 0) { s0 = 0; e0 = 0.38 * BW; }
  else { uu = (t % 2.4) / 2.4; s0 = Math.Max(0, uu * 1.38 - 0.38) * BW; e0 = Math.Min(1, uu * 1.38) * BW; }
  phase = t * 2 * Math.Pi * 1.1;
  for (i = 0; i < NDOT; i++) {
    x = i * STEP;
    if (x >= s0 && x <= e0) { dots[i].SetPosition(ox + ZS * (BX + x), oy + ZS * (BY + AMP * Math.Sin(2 * Math.Pi * x / LAM - phase)), 6); dots[i].SetOpacity(1); }
    else dots[i].SetOpacity(0);
  }
}
bar(0);""")
    # ---- refresh: the staggered animation
    body = ["  frame++; t = frame / " + str(FPS) + ";"]
    # A display that is attached after the first paint (a hand-over from the firmware's framebuffer to a DRM driver) may only get the dirty rectangles after
    # that, so the scene shows on black (seen on Ubuntu 24.04 under UEFI). Setting the background colour makes the script plugin repaint the whole screen:
    # done once a second for the first twenty seconds, then never again.
    body.append(
        "  if (frame <= "
        + str(FPS * 20)
        + " && frame % "
        + str(FPS)
        + " == 0) { Window.SetBackgroundTopColor("
        + sc
        + "); Window.SetBackgroundBottomColor("
        + sc
        + "); }"
    )
    if cad["rate"]:
        body.append("  k = frame % RATE; if (k < rot_n) place_rot(k, t);")
    if cad["pulse"] and "card" in pl["pics"]:
        body += [
            "  if (frame % PULSE == 1) { kk = 1 + 0.02 * Math.Sin(t * 1.6); s_card.SetImage(img_card.Scale(Math.Int(card_w * kk * ZS), Math.Int(card_h * kk * ZS)));",
            "    s_card.SetPosition(ox + ZS * (card_x + (card_w - card_w * kk) / 2), oy + ZS * (card_y + (card_h - card_h * kk) / 2), 5); }",
        ]
        im, x, y = pl["pics"]["card"]
        a(f'img_card = Image("card.png"); card_w = {im.width}; card_h = {im.height}; card_x = {x}; card_y = {y};')
    if cad["bar"]:
        body.append("  if (frame % BAR_EVERY == 0) bar(t);")
    elif pl["bar_mode"] == "progress":
        body.append("  if (frame % 6 == 0) bar(t);  # motion off: the fill still follows the boot, nothing else moves")
    if len(body) > 1:  # always true now: the repaint above is in every refresh
        a("fun refresh() {\n" + "\n".join(body) + "\n}\nPlymouth.SetRefreshFunction(refresh);")
    # ---- messages and the disk password prompt
    sx, sy = pl["slot"]
    a('s_msg_shutdown = Sprite(load("msg_shutdown.png")); s_msg_updates = Sprite(load("msg_updates.png"));')
    a(f"SLOT_X = {n(sx)}; SLOT_Y = {n(sy)};")
    a("""s_msg_shutdown.SetOpacity(0); s_msg_updates.SetOpacity(0);
msg = 0;
if (mode == "shutdown") msg = s_msg_shutdown;
if (mode == "updates" || mode == "system-upgrade" || mode == "firmware-upgrade") msg = s_msg_updates;
if (msg) {
  msg.SetPosition(ox + SLOT_X * ZS - msg.GetImage().GetWidth() / 2, oy + SLOT_Y * ZS - msg.GetImage().GetHeight() / 2, 6); msg.SetOpacity(1);""")
    if any(g == "pills" for _n, _z, g in pl["static"]):
        a("  s_pills.SetOpacity(0);")
    a("}")
    pw, ph = u(560), u(72)
    fx, fy = bx + (BW - pw) // 2, by + STROKE // 2 - ph // 2
    a(f"FX = {n(fx)}; FY = {n(fy)}; PWD = {u(20)}; PW_STEP = {u(30)}; PW_X0 = {u(36)};")
    a(
        's_pw_field = Sprite(load("pw_field.png")); s_pw_field.SetPosition(ox + FX * ZS, oy + FY * ZS, 9); s_pw_field.SetOpacity(0);'
    )
    a(
        f's_pw_label = Sprite(load("pw_label.png")); s_pw_label.SetPosition(ox + FX * ZS + ({pw} * ZS - s_pw_label.GetImage().GetWidth()) / 2, oy + (FY + {ph} + {u(22)}) * ZS, 9); s_pw_label.SetOpacity(0);'
    )
    a(
        'img_pwd = load("pw_dot.png"); for (i = 0; i < 24; i++) { pwd[i] = Sprite(img_pwd); pwd[i].SetZ(10); pwd[i].SetOpacity(0); }'
    )
    pills_hide = "s_pills.SetOpacity(0); " if any(g == "pills" for _n, _z, g in pl["static"]) else ""
    pills_show = "if (!msg) s_pills.SetOpacity(1); " if pills_hide else ""
    a(f"""fun pw_show(prompt, bullets) {{
  pw_on = 1; {pills_hide}s_track.SetOpacity(0); s_stop.SetOpacity(0);
  for (i = 0; i < NDOT; i++) dots[i].SetOpacity(0);
  s_pw_field.SetOpacity(1); s_pw_label.SetOpacity(1);
  for (i = 0; i < 24; i++) {{
    if (i < bullets) {{ pwd[i].SetPosition(ox + (FX + PW_X0 + i * PW_STEP) * ZS, oy + (FY + ({ph} - PWD) / 2) * ZS, 10); pwd[i].SetOpacity(1); }}
    else pwd[i].SetOpacity(0);
  }}
}}
fun pw_hide() {{
  pw_on = 0; {pills_show}s_track.SetOpacity(1); s_stop.SetOpacity(1);
  s_pw_field.SetOpacity(0); s_pw_label.SetOpacity(0);
  for (i = 0; i < 24; i++) pwd[i].SetOpacity(0);
}}
Plymouth.SetDisplayPasswordFunction(pw_show);
Plymouth.SetDisplayQuestionFunction(pw_show);
Plymouth.SetDisplayNormalFunction(pw_hide);""")
    return "\n".join(s) + "\n"


def build(look, W, H, out, motion="full", bar="indeterminate", install_dir=None):
    """Write the theme into `out` (emptied first). Returns {'files': {name: bytes}, 'style': ..., 'size': total bytes}."""
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    pl = plan(look, W, H, motion, bar)
    pics = dict(pl["pics"])
    for k, im in {**Ly.bar_assets(look), **Ly.prompt_assets(look), **Ly.message_assets(look)}.items():
        pics[k] = (im, 0, 0)
    for k, (im, _x, _y) in pics.items():
        im.save(out / f"{k}.png", optimize=True)
    (out / "material.script").write_text(script(look, pl))
    d = Path(install_dir) if install_dir else out
    (out / "material.plymouth").write_text(
        f"[Plymouth Theme]\nName=Material\nDescription=Material 3 Expressive boot splash that continues the Material GRUB theme\nModuleName=script\n\n"
        f"[script]\nImageDir={d}\nScriptFile={d}/material.script\n"
    )
    files = {f.name: f.stat().st_size for f in sorted(out.iterdir())}
    return {"files": files, "style": pl["style"], "size": sum(files.values()), "plan": pl}


def preview(look, W, H, screen="boot", motion="full", bar="indeterminate"):
    """A still of what the theme shows at rest, as a PIL RGB image: `boot` (the scene and the bar), `password` (the disk-password prompt with seven dots) or
    `shutdown` (the shutdown message). It is the real layers at the real positions, and every number that is not in a layer (the bar's geometry, the prompt's
    place, the message slot) is read from the script that build() writes, so the preview cannot drift from the theme. Used by the GUI."""
    if screen not in ("boot", "password", "shutdown"):
        raise ValueError(f"unknown screen {screen!r}")
    pl = plan(look, W, H, motion, bar)
    text = script(look, pl)

    def consts(*names):
        out = {}
        for name in names:
            m = re.search(rf"\b{name} = (-?[\d.]+)", text)
            if not m:
                raise ValueError(f"the script has no {name}")
            out[name] = float(m[1])
        return out

    cv = Image.new("RGBA", (W, H), tuple(look.core.mgscenes.hexc(look.palette["surface"])) + (255,))
    items = []  # (z, image, x, y)
    for name, z, _group in pl["static"]:
        if name == "pills" and screen != "boot":
            continue  # the pills are hidden by the prompt and replaced by the message
        im, x, y = pl["pics"][name]
        items.append((z, im, x, y))
    for r in pl["rot"]:
        im, x, y = pl["pics"][r["name"]]
        items.append((r["z"], im, x, y))
    bars, prompts, msgs = Ly.bar_assets(look), Ly.prompt_assets(look), Ly.message_assets(look)
    if screen != "password":
        bx, by = pl["bar"]
        k = consts("BW", "STROKE", "AMP", "LAM", "STEP")
        items.append((5, bars["track"], bx, by))
        items.append((6, bars["stop"], bx + int(k["BW"] - k["STROKE"]), by))
        end = (0.45 if bar == "progress" else 0.38) * k["BW"]
        x = 0.0
        while x <= end:  # the wave, one dot per STEP pixels, as the script places them
            dy = k["AMP"] * math.sin(2 * math.pi * x / k["LAM"])
            items.append((6, bars["dot"], bx + int(x), by + int(dy)))
            x += k["STEP"]
    if screen == "password":
        k = consts("FX", "FY", "PWD", "PW_STEP", "PW_X0")
        fx, fy = int(k["FX"]), int(k["FY"])
        items.append((9, prompts["pw_field"], fx, fy))
        lw = prompts["pw_label"].width
        fh = prompts["pw_field"].height
        items.append(
            (9, prompts["pw_label"], fx + (prompts["pw_field"].width - lw) // 2, fy + fh + look.R.u(22))
        )  # the script's own offsets
        for i in range(7):
            items.append(
                (10, prompts["pw_dot"], fx + int(k["PW_X0"] + i * k["PW_STEP"]), fy + int((fh - k["PWD"]) / 2))
            )
    if screen == "shutdown":
        sx, sy = pl["slot"]
        im = msgs["msg_shutdown"]
        items.append((6, im, round(sx - im.width / 2), round(sy - im.height / 2)))
    for _z, im, x, y in sorted(items, key=lambda t: t[0]):
        Ly._paste(cv, im, x, y)
    return cv.convert("RGB")
