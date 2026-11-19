"""The static pictures of a Plymouth scene, drawn with material-grub's own Renderer so they are the GRUB pixels, split into the layers the script moves.

A layer is (RGBA image, x, y): the top-left corner on a W x H screen. Layers that only move (the hero card pulses, the title and the pills sit still) are
cropped to their content; shapes that ROTATE keep their square so the script can turn them about their centre. At rest (no animation) the layers
composite to exactly what GRUB shows (tests/test_layers.py checks it pixel by pixel), so the hand-over from GRUB to Plymouth does not jump.
"""

from PIL import Image, ImageDraw

TITLE_Y, PILLS_Y = 590, 672  # 1080-high design values of mgscenes.Renderer.hero (the card is drawn by hero() itself)


def _blank(W, H):
    return Image.new("RGBA", (W, H), (0, 0, 0, 0))


def _crop(im):
    """(image cropped to its non-transparent part, x, y), or None for an empty picture."""
    box = im.getchannel("A").getbbox()
    return None if box is None else (im.crop(box), box[0], box[1])


def card(look, W, H):
    """The hero card (the rounded container holding the distro's glyph or logo): the part that pulses."""
    R = look.R
    cv = _blank(W, H)
    # Renderer.hero minus its title and pills: a plain entry with a blank name and no info fields
    R.hero(cv, dict(look.entry, kind="plain", name=" ", os=None, osver=None, edition=None, where=None), look.palette)
    return _crop(cv)


def title(look, W, H):
    """The title under the card, set exactly as Renderer.hero sets it."""
    R, p = look.R, look.palette
    u = R.u
    t = R.title_for(look.entry)
    tsz = u(150)
    while tsz > u(60) and R.font(tsz, 800, 135, 60).getlength(t) > W * 0.62:
        tsz -= u(6)
    cv = _blank(W, H)
    ImageDraw.Draw(cv).text(
        (W // 2, u(TITLE_Y)),
        t,
        font=R.font(tsz, 800, 135, 60),
        fill=look.core.mgscenes.hexc(p["primary"]) + (255,),
        anchor="mm",
    )
    return _crop(cv)


def pills(look, W, H):
    """The info pills (OS, version, edition) under the title."""
    R = look.R
    cv = _blank(W, H)
    R.pill_row(R.info_pills(look.entry), look.palette, W, R.u(PILLS_Y), cv)
    return _crop(cv)


def cookie(look, W, H):
    """The top-right cookie shape (it rotates: kept square). None when COOKIE=off."""
    if not look.cookie:
        return None
    R = look.R
    cv = _blank(W, H)
    R.preview_logo = None
    R.draw_cookie(cv, look.palette)
    box = R.shape("cookie", R.u(230), look.palette["primaryContainer"]).size
    c = cv.getchannel("A").getbbox()
    # keep the full square of the shape (its bounding box is the circle's chord, not the square): centre it on the cookie centre
    cx, cy = W - R.u(150 - R.cookie_off[0]), R.u(140 + R.cookie_off[1])
    x, y = round(cx - box[0] / 2), round(cy - box[1] / 2)
    return cv.crop((x, y, x + box[0], y + box[1])) if c else None, x, y


def logo(look, W, H):
    """The firmware (BGRT) logo, or the Linux penguin where the firmware has none, upright on the cookie. None when COOKIE=off or LOGO=off."""
    if not (look.cookie and look.logo):
        return None
    R = look.R
    im = look.core.mgscenes.machine_logo(look.core.pkg, R.u(120))
    if im is None:
        return None
    return im, round(W - R.u(150 - R.cookie_off[0]) - im.width / 2), round(R.u(140 + R.cookie_off[1]) - im.height / 2)


def background(look, W, H):
    """The three big faint shapes behind the scene, at the places and sizes GRUB's panels draw them (Renderer.panel_scene). They rotate and drift."""
    R, p = look.R, look.palette
    u, cx = R.u, W // 2
    specs = (
        ("bg_cookie", "cookie", u(620), "surfaceContainerHigh", cx - int(W * 0.36), H - u(120)),
        ("bg_sunny", "sunny", u(460), "surfaceContainer", cx + int(W * 0.34), H - u(60)),
        ("bg_clover", "clover", u(300), "surfaceContainer", cx - int(W * 0.29), u(150)),
    )
    out = {}
    for name, shape, size, role, x, y in specs:
        im = R.shape(shape, size, p[role])
        out[name] = (im, int(x - im.width / 2), int(y - im.height / 2))
    return out


def all_layers(look, W, H):
    """{name: (image, x, y)} of every layer this look needs, plus 'surface' (the background colour as '#RRGGBB'). Options that are off have no layer."""
    out = {"surface": look.palette["surface"]}
    out.update(background(look, W, H))
    for name, fn in (("card", card), ("title", title), ("pills", pills), ("cookie", cookie), ("logo", logo)):
        layer = fn(look, W, H)
        if layer is not None and layer[0] is not None:
            out[name] = layer
    return out


def _paste(cv, im, x, y):
    """alpha_composite that tolerates a layer that starts off the screen (the big shapes do)."""
    x0, y0 = max(0, -x), max(0, -y)
    x1, y1 = min(im.width, cv.width - x), min(im.height, cv.height - y)
    if x1 > x0 and y1 > y0:
        cv.alpha_composite(im.crop((x0, y0, x1, y1)), (x + x0, y + y0))


def composite(layers, W, H, only=None):
    """The layers laid over a transparent W x H canvas in drawing order (shapes, card, title, pills, cookie, logo): the scene at rest."""
    cv = _blank(W, H)
    for name in ("bg_cookie", "bg_sunny", "bg_clover", "card", "title", "pills", "cookie", "logo"):
        if name in layers and (only is None or name in only):
            im, x, y = layers[name]
            _paste(cv, im, x, y)
    return cv
