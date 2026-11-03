"""Uygulama simgesini (assets/icon.ico, icon.icns, icon.png) üretir."""
import os

from PIL import Image, ImageDraw, ImageFont

ASSETS = os.path.join(os.path.dirname(__file__), "..", "assets")


def draw(size: int = 1024) -> Image.Image:
    s = size / 256
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([40 * s, 16 * s, 216 * s, 240 * s], 14 * s, fill="white", outline=(60, 60, 70), width=int(4 * s))
    for y in (48, 70, 92, 218):
        d.line([70 * s, y * s, 186 * s, y * s], fill=(150, 150, 160), width=int(5 * s))
    d.rounded_rectangle([24 * s, 120 * s, 232 * s, 200 * s], 12 * s, fill=(170, 30, 40))
    font = None
    for name in ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf",
                 "/System/Library/Fonts/Supplemental/Arial Bold.ttf"):
        try:
            font = ImageFont.truetype(name, int(64 * s))
            break
        except OSError:
            pass
    d.text((128 * s, 160 * s), "TIF", fill="white", font=font or ImageFont.load_default(), anchor="mm")
    return im


if __name__ == "__main__":
    os.makedirs(ASSETS, exist_ok=True)
    img = draw()
    img.save(os.path.join(ASSETS, "icon.png"))
    img.save(os.path.join(ASSETS, "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.save(os.path.join(ASSETS, "icon.icns"))
    print("Simgeler:", os.path.abspath(ASSETS))
