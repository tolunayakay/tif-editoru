"""Test için örnek UYAP benzeri TIFF dosyaları üretir (samples/ klasörüne)."""
import os
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(__file__), "..", "samples")
os.makedirs(OUT, exist_ok=True)


def font(size):
    for name in ("arial.ttf", "DejaVuSans.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def text_page(lines, size=(2480, 3508), mode="1", ink=0, bg=255):
    im = Image.new("L", size, bg)
    d = ImageDraw.Draw(im)
    f = font(int(size[0] / 40))
    y = int(size[1] * 0.08)
    for ln in lines:
        d.text((int(size[0] * 0.1), y), ln, fill=ink, font=f)
        y += int(f.size * 1.8)
    d.ellipse((1700, 2900, 2200, 3300), outline=ink, width=8)
    d.text((1780, 3060), "MÜHÜR", fill=ink, font=f)
    return im.convert("1") if mode == "1" else im


body = ["T.C. İSTANBUL CUMHURİYET BAŞSAVCILIĞI", "Soruşturma No: 2026/14523",
        "İFADE TUTANAĞI", "", "Şüpheli: Ahmet Yılmaz", "Müdafi: Av. Ayşe Kaya",
        "Olay tarihi: 12.03.2026", "Şüpheliye haklarının hatırlatıldığı görüldü.",
        "İmza altına alındı."]
pages = [text_page(body),
         text_page(["EK-1 OLAY YERİ TESPİT TUTANAĞI"] + body[1:]).rotate(180),
         Image.new("1", (2480, 3508), 1),
         text_page(["FAKS İLE GELEN EVRAK", "Çözünürlük 204x98 dpi"] + body[4:], size=(1728, 1100)),
         text_page(["SOLUK KARBON KOPYA"] + body[1:], mode="L", ink=170, bg=235)]
pages[0].save(os.path.join(OUT, "uyap_ornek.tif"), save_all=True, append_images=pages[1:4],
              compression="group4", dpi=(300, 300))
# 4. sayfa faks çözünürlüğünde: ayrı dosya olarak yaz ve gri sayfayı ekle
pages[3].save(os.path.join(OUT, "faks_204x98.tif"), compression="group4", dpi=(204, 98))
pages[4].save(os.path.join(OUT, "soluk_gri.tif"), compression="tiff_lzw", dpi=(300, 300))
print("Örnekler:", os.path.abspath(OUT))
