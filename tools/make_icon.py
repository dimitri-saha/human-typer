"""Draws the app icon and writes it as an .icns file: make_icon.py OUT.icns"""
import os
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFilter, ImageFont


def draw(size=1024):
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # Rounded-square background with a vertical gradient.
    bg = Image.new("RGBA", (s, s))
    top, bottom = (58, 72, 112), (24, 28, 48)
    px = bg.load()
    for y in range(s):
        t = y / (s - 1)
        c = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,)
        for x in range(s):
            px[x, y] = c
    mask = Image.new("L", (s, s), 0)
    m = int(s * 0.1)
    ImageDraw.Draw(mask).rounded_rectangle((m, m, s - m, s - m), radius=int(s * 0.18), fill=255)
    img.paste(bg, (0, 0), mask)

    # Keycap with a soft shadow.
    d = ImageDraw.Draw(img)
    k0, k1 = int(s * 0.26), int(s * 0.74)
    shadow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((k0, k0 + s * 0.04, k1, k1 + s * 0.04),
                                             radius=int(s * 0.07), fill=(0, 0, 0, 140))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(s * 0.02)))
    d.rounded_rectangle((k0, k0, k1, k1), radius=int(s * 0.07), fill=(236, 238, 245))
    d.rounded_rectangle((k0 + s * 0.04, k0 + s * 0.03, k1 - s * 0.04, k1 - s * 0.08),
                        radius=int(s * 0.05), fill=(250, 251, 255))

    # Letter plus a text caret.
    font = None
    for path in ["/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc",
                 "/Library/Fonts/Arial.ttf"]:
        if os.path.exists(path):
            font = ImageFont.truetype(path, int(s * 0.26))
            break
    font = font or ImageFont.load_default()
    d.text((s * 0.455, s * 0.47), "Aa", font=font, fill=(36, 42, 66), anchor="mm")
    cx = int(s * 0.64)
    d.rectangle((cx, int(s * 0.36), cx + int(s * 0.018), int(s * 0.58)), fill=(76, 132, 255))
    return img


def main(out):
    base = draw()
    with tempfile.TemporaryDirectory() as tmp:
        iconset = os.path.join(tmp, "AppIcon.iconset")
        os.makedirs(iconset)
        for pt in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = pt * scale
                name = f"icon_{pt}x{pt}{'@2x' if scale == 2 else ''}.png"
                base.resize((px, px), Image.LANCZOS).save(os.path.join(iconset, name))
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", out], check=True)


if __name__ == "__main__":
    main(sys.argv[1])
