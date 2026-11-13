#!/usr/bin/env python3
"""Draw the StackChan mint face stills from the same parameters as mint.cpp (320x240 panel, 1.35 scale).

Every number below is a number in firmware/main/stackchan/avatar/skins/mint/mint.cpp (patches 013, 110, 112).
The Wi-Fi glyph is decoded from the unit's own icon_wifi_*.bin (20x20 RGB565A8, alpha plane used).
"""
import sys, pathlib, html

K = 1.35
ICON_DIR = pathlib.Path(sys.argv[1])
OUT = pathlib.Path(sys.argv[2])

PAL = {
    "mint": dict(bg="#C4F0DA", ink="#18241F", fill="#3E9E6B", tongue="#8ED6A4", drop=0),
    "offline": dict(bg="#BBC6CE", ink="#26303A", fill="#62788A", tongue="#A5B6C3", drop=5),
}

def px(v): return round(v * K)

def eye_svg(cx, cy, left, face, pal):
    """cx, cy: eye box centre in screen px."""
    ink = pal["ink"]
    cy = cy + pal["drop"]
    if face in ("neutral", "listening", "thinking"):
        r = {"neutral": 8, "listening": 10, "thinking": 8}[face]
        lx, ly = (6, -8) if face == "thinking" else (0, 0)
        return f'<circle cx="{cx + px(lx)}" cy="{cy + px(ly)}" r="{px(r*2)/2:.2f}" fill="{ink}"/>'
    raise ValueError(face)

def quad(x0, y0, cxp, cyp, x1, y1, ox, oy):
    f = lambda x, y: f"{ox + px(x)} {oy + px(y)}"
    return f"M {f(x0,y0)} Q {f(cxp,cyp)} {f(x1,y1)}"

def mouth_svg(face, pal):
    ox, oy = 160, 120 + 39
    ink = pal["ink"]
    if face == "neutral":
        d = quad(-26, -4, 0, 14, 26, -4, ox, oy)
    elif face == "listening":
        d = quad(-16, 0, 0, 7, 16, 0, ox, oy)
    elif face == "thinking":
        d = f"M {ox + px(-4)} {oy + px(3)} L {ox + px(12)} {oy + px(3)}"
    return f'<path d="{d}" fill="none" stroke="{ink}" stroke-width="7" stroke-linecap="round"/>'

def icon(name, x, y, color="#fff", scale=1.0):
    data = (ICON_DIR / name).read_bytes()[12:]
    n = 20 * 20
    alpha = data[n * 2: n * 3]
    rects = []
    for i, a in enumerate(alpha):
        if a > 40:
            rects.append(f'<rect x="{i % 20}" y="{i // 20}" width="1.02" height="1.02" fill="{color}" fill-opacity="{a/255:.2f}"/>')
    return f'<g transform="translate({x} {y}) scale({scale})">' + "".join(rects) + "</g>"

def key(x, y, color="#fff"):
    return (f'<g transform="translate({x} {y})"><circle cx="6" cy="10" r="4.5" fill="none" stroke="{color}" stroke-width="3"/>'
            f'<rect x="11" y="8" width="15" height="3" fill="{color}"/><rect x="18" y="11" width="3" height="5" fill="{color}"/>'
            f'<rect x="23" y="11" width="3" height="4" fill="{color}"/></g>')

def strip(glyph, text, with_key=False):
    # a dark pill, 6 px from the corner: glyph 20 px, optional key 26 px, then the text in 16 px,
    # wrapped at 236 px (two lines for the approval words)
    lines = text.split("\n") if text else []
    textw = max([8.7 * len(l) for l in lines] + [0])
    h = 28 if len(lines) < 2 else 46
    w = 8 + 20 + (4 + 26 if with_key else 0) + (6 + textw if text else 0) + 8
    s = f'<rect x="6" y="6" width="{w:.0f}" height="{h}" rx="12" fill="#000" fill-opacity="0.7"/>'
    s += glyph(14, 6 + (h - 20) // 2)
    x = 14 + 20
    if with_key:
        s += key(x + 4, 6 + (h - 20) // 2); x += 30
    for i, line in enumerate(lines):
        yy = 6 + h / 2 + 5 - (len(lines) - 1) * 9 + i * 18
        s += f'<text x="{x + 6}" y="{yy:.0f}" fill="#fff" font-family="Montserrat, Helvetica, Arial, sans-serif" font-size="14">{html.escape(line)}</text>'
    return s

def face(name, f, pal="mint", extra=""):
    p = PAL[pal]
    body = f'<rect width="320" height="240" fill="{p["bg"]}"/>'
    body += eye_svg(160 - 78, 120 - 23, True, f, p) + eye_svg(160 + 78, 120 - 23, False, f, p)
    body += mouth_svg(f, p) + extra
    return name, body

def link_screen(name, glyph_name, text, with_key=False, cycle=None):
    s = '<rect width="320" height="240" fill="#000"/>'
    gx = 160 - 15 - (24 if with_key else 0)
    s += icon(glyph_name, gx, 53, scale=1.5)
    if with_key:
        s += key(160 + 11, 60)
    lines = text.split("\n")
    for i, line in enumerate(lines):
        s += f'<text x="160" y="{112 + i * 22}" text-anchor="middle" fill="#fff" font-family="Helvetica, Arial, sans-serif" font-size="18">{html.escape(line)}</text>'
    return name, s

panels = [
    face("neutral (today)", "neutral"),
    face("listening (NEW)", "listening"),
    face("thinking (NEW)", "thinking"),
    face("offline: muted palette, strip", "neutral", "offline",
         strip(lambda x, y: icon("icon_wifi_slash.bin", x, y), "Offline")),
    face("connecting: normal palette, glyph cycles", "neutral", "mint",
         strip(lambda x, y: icon("icon_wifi_medium.bin", x, y), "")),
    face("waiting for approval", "neutral", "offline",
         strip(lambda x, y: icon("icon_wifi_slash.bin", x, y), "Waiting for Home\nto approve me", True)),
    link_screen("link screen: Wi-Fi", "icon_wifi_medium.bin", "Connecting to Wi-Fi..."),
    link_screen("link screen: Wi-Fi setup", "icon_wifi_slash.bin", "Wi-Fi setup needed\nHotspot: <name>\nConfig URL: <address>"),
    link_screen("link screen: approval", "icon_wifi_slash.bin", "Waiting for Home to approve me", True),
]
cells = "".join(
    f'<figure><svg viewBox="0 0 320 240" width="320" height="240">{b}</svg><figcaption>{html.escape(n)}</figcaption></figure>'
    for n, b in panels)
page = f'''<!doctype html><meta charset="utf-8"><title>StackChan faces preview</title>
<style>body{{margin:0;padding:16px;background:#e9e9e9;font:14px Helvetica,Arial,sans-serif}}
.g{{display:grid;grid-template-columns:repeat(3,320px);gap:14px}}figure{{margin:0}}svg{{display:block;border-radius:6px}}
figcaption{{margin-top:4px;color:#333}}</style><div class="g">{cells}</div>'''
OUT.write_text(page)
for i, (n, b) in enumerate(panels):
    (OUT.parent / f"still-{i+1:02d}.svg").write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 240" width="320" height="240">{b}</svg>')
