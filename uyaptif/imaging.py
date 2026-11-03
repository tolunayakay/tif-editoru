"""TIFF sayfası yükleme, döndürme ve görüntü iyileştirme yardımcıları.

Bu modüldeki fonksiyonlar iş parçacığı güvenlidir (her çağrı dosyayı kendisi açar),
bu yüzden arka plan iş parçacıklarından rahatça çağrılabilir.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter
from PySide6.QtGui import QImage, QImageReader

# UYAP taramaları çok büyük olabilir; Pillow'un "decompression bomb" korumasını kapat.
Image.MAX_IMAGE_PIXELS = None

DEFAULT_DPI = 200.0
A4_WIDTH_INCH = 8.27


# --------------------------------------------------------------------------- yükleme

def count_frames(path: str) -> int:
    """Dosyadaki sayfa sayısı (yalnızca IFD'ler okunur, piksel verisi çözülmez)."""
    try:
        with Image.open(path) as im:
            return int(getattr(im, "n_frames", 1))
    except Exception:
        reader = QImageReader(path)
        n = reader.imageCount()
        if n > 0:
            return n
        if reader.canRead():
            return 1
        raise OSError(f"Dosya açılamadı: {path}\n{reader.errorString()}")


def load_frame(path: str, frame: int) -> tuple[Image.Image, float]:
    """Bir sayfayı yükler. Dönen görüntünün modu '1', 'L' veya 'RGB'dir.

    Faks çözünürlüklü (ör. 204x98 dpi) sayfalar kare piksele getirilir, böylece
    yazılar basık görünmez. İkinci değer yatay dpi'dir.
    """
    try:
        with Image.open(path) as im:
            im.seek(frame)
            dpi = im.info.get("dpi")
            im.load()
            img = _normalize_mode(im)
    except Exception:
        img, dpi = _load_with_qt(path, frame)

    xdpi, ydpi = _parse_dpi(dpi, img.width)
    if abs(xdpi - ydpi) / max(xdpi, ydpi) > 0.05:
        new_h = max(1, round(img.height * xdpi / ydpi))
        resample = Image.Resampling.NEAREST if img.mode == "1" else Image.Resampling.BICUBIC
        img = img.resize((img.width, new_h), resample)
    return img, xdpi


def _parse_dpi(dpi, width: int) -> tuple[float, float]:
    try:
        x, y = float(dpi[0]), float(dpi[1])
    except Exception:
        x = y = 0.0
    if x <= 1 or y <= 1:
        x = y = _guess_dpi(width)
    elif x < 100 and width > 1500:
        # Bazı tarayıcılar 72 dpi yazar ama görüntü 300 dpi taramadır.
        g = _guess_dpi(width)
        x, y = g, g * y / x
    return x, y


def _guess_dpi(width: int) -> float:
    return max(100.0, min(600.0, round(width / A4_WIDTH_INCH))) if width else DEFAULT_DPI


def _normalize_mode(im: Image.Image) -> Image.Image:
    mode = im.mode
    if mode in ("1", "L", "RGB"):
        return im.copy()
    if mode.startswith("I") or mode == "F":
        arr = np.asarray(im, dtype=np.float32)
        hi = float(arr.max()) or 1.0
        return Image.fromarray(np.clip(arr * (255.0 / hi), 0, 255).astype(np.uint8), "L")
    if mode in ("LA", "La"):
        return im.convert("L")
    if mode == "P":
        rgb = im.convert("RGB")
        return rgb.convert("L") if _is_gray(rgb) else rgb
    return im.convert("RGB")


def _load_with_qt(path: str, frame: int) -> tuple[Image.Image, tuple[float, float] | None]:
    """Pillow'un okuyamadığı (ör. eski tip JPEG-in-TIFF) dosyalar için Qt yedeği."""
    reader = QImageReader(path)
    if frame and not reader.jumpToImage(frame):
        raise OSError(f"{frame + 1}. sayfaya geçilemedi: {reader.errorString()}")
    q = reader.read()
    if q.isNull():
        raise OSError(f"Sayfa okunamadı: {reader.errorString()}")
    dpi = None
    if q.dotsPerMeterX() > 0 and q.dotsPerMeterY() > 0:
        dpi = (q.dotsPerMeterX() * 0.0254, q.dotsPerMeterY() * 0.0254)
    img = qimage_to_pil(q)
    if img.mode == "RGB" and _is_gray(img):
        img = img.convert("L")
    return img, dpi


def _is_gray(img: Image.Image) -> bool:
    small = img.copy()
    small.thumbnail((256, 256))
    a = np.asarray(small, dtype=np.int16)
    if a.ndim != 3:
        return True
    return int(np.abs(a[..., 0] - a[..., 1]).max()) < 12 and int(np.abs(a[..., 1] - a[..., 2]).max()) < 12


# --------------------------------------------------------------------------- dönüşümler

_TRANSPOSE = {
    90: Image.Transpose.ROTATE_270,   # saat yönünde 90
    180: Image.Transpose.ROTATE_180,
    270: Image.Transpose.ROTATE_90,
}


def rotate_image(img: Image.Image, degrees_cw: int) -> Image.Image:
    degrees_cw %= 360
    if degrees_cw == 0:
        return img
    return img.transpose(_TRANSPOSE[degrees_cw])


@dataclass(frozen=True)
class Enhancement:
    """Okunabilirlik ayarları. Değerler -100..100 aralığındadır.

    threshold: 0 = kapalı, -1 = otomatik (Otsu), 1..254 = elle eşik.
    """
    brightness: int = 0
    contrast: int = 0
    darken: int = 0
    threshold: int = 0
    despeckle: bool = False

    def is_identity(self) -> bool:
        return self == Enhancement()


def _build_lut(enh: Enhancement) -> list[int]:
    v = np.arange(256, dtype=np.float64) / 255.0
    if enh.darken:
        v = v ** (2.0 ** (enh.darken / 50.0))
    if enh.contrast:
        c = enh.contrast / 100.0
        factor = 1.0 + 3.0 * c if c > 0 else 1.0 + c
        v = (v - 0.5) * factor + 0.5
    if enh.brightness:
        v = v + enh.brightness / 100.0 * 0.5
    return np.clip(np.round(v * 255.0), 0, 255).astype(np.uint8).tolist()


def apply_enhancement(img: Image.Image, enh: Enhancement) -> Image.Image:
    if enh.is_identity():
        return img
    if img.mode == "1":
        img = img.convert("L")
    if enh.despeckle:
        img = img.filter(ImageFilter.MedianFilter(3))
    if enh.brightness or enh.contrast or enh.darken:
        lut = _build_lut(enh)
        img = img.point(lut * (3 if img.mode == "RGB" else 1))
    if enh.threshold:
        img = to_bitonal(img, None if enh.threshold < 0 else enh.threshold)
    return img


def otsu_threshold(gray: Image.Image) -> int:
    hist = np.asarray(gray.histogram()[:256], dtype=np.float64)
    total = hist.sum()
    if total == 0:
        return 128
    bins = np.arange(256)
    w0 = np.cumsum(hist)
    w1 = total - w0
    m0 = np.cumsum(hist * bins)
    mt = m0[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (mt * w0 / total - m0) ** 2 / (w0 * w1)
    between = np.nan_to_num(between)
    return int(np.argmax(between))


def to_bitonal(img: Image.Image, threshold: int | None = None) -> Image.Image:
    if img.mode == "1":
        return img
    gray = img.convert("L") if img.mode != "L" else img
    t = otsu_threshold(gray) if threshold is None else threshold
    lut = [255 if i > t else 0 for i in range(256)]
    return gray.point(lut).convert("1", dither=Image.Dither.NONE)


def process_page(path: str, frame: int, rotation: int, enh: Enhancement | None) -> tuple[Image.Image, float]:
    img, dpi = load_frame(path, frame)
    img = rotate_image(img, rotation)
    if enh is not None:
        img = apply_enhancement(img, enh)
    return img, dpi


def ink_ratio(img: Image.Image) -> float:
    """Kenar boşlukları hariç koyu piksel oranı (boş sayfa tespiti için)."""
    gray = img.convert("L")
    gray.thumbnail((500, 500), Image.Resampling.BOX)
    w, h = gray.size
    mx, my = int(w * 0.06), int(h * 0.06)
    a = np.asarray(gray.crop((mx, my, w - mx, h - my)))
    if a.size == 0:
        return 0.0
    # Kağıt rengine göre göreli eşik: soluk/karbon kopyalar boş sanılmasın.
    paper = float(np.percentile(a, 90))
    return float((a < paper - 40).mean())


def make_thumbnail(path: str, frame: int, max_w: int, max_h: int) -> Image.Image:
    img, _ = load_frame(path, frame)
    if img.mode == "1":
        img = img.convert("L")
    img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS, reducing_gap=3.0)
    return img


# --------------------------------------------------------------------------- Qt köprüsü

def pil_to_qimage(img: Image.Image) -> QImage:
    if img.mode == "1":
        img = img.convert("L")
    w, h = img.size
    if img.mode == "L":
        return QImage(img.tobytes(), w, h, w, QImage.Format.Format_Grayscale8).copy()
    if img.mode != "RGB":
        img = img.convert("RGB")
    return QImage(img.tobytes(), w, h, w * 3, QImage.Format.Format_RGB888).copy()


def qimage_to_pil(q: QImage) -> Image.Image:
    q = q.convertToFormat(QImage.Format.Format_RGB888)
    w, h, bpl = q.width(), q.height(), q.bytesPerLine()
    buf = np.frombuffer(q.constBits(), dtype=np.uint8, count=q.sizeInBytes())
    arr = buf.reshape(h, bpl)[:, : w * 3].reshape(h, w, 3)
    return Image.fromarray(arr.copy(), "RGB")
