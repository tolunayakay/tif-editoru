"""TIFF / PDF dışa aktarma ve UYAP'a uygun sıkıştırma profilleri."""
from __future__ import annotations

import io
import os
from dataclasses import dataclass
from typing import Callable

import img2pdf
import numpy as np
from PIL import Image, TiffImagePlugin

from .document import Page
from .imaging import Enhancement, process_page, to_bitonal
from .ocr import OcrEngine

Progress = Callable[[int, int, str], None]


@dataclass(frozen=True)
class Profile:
    key: str
    name: str
    max_dpi: int | None
    jpeg_quality: int
    force_bitonal: bool
    description: str


PROFILES = [
    Profile("orijinal", "Orijinal kalite", None, 90, False,
            "Çözünürlük korunur. Siyah-beyaz sayfalar kayıpsız CCITT G4 ile saklanır."),
    Profile("dengeli", "UYAP – dengeli (200 dpi)", 200, 75, False,
            "Önerilen. 200 dpi üzerindeki sayfalar küçültülür; gri/renkli sayfalar JPEG olur."),
    Profile("kucuk", "UYAP – küçük (150 dpi, siyah-beyaz)", 150, 60, True,
            "En küçük boyut. Tüm sayfalar siyah-beyaza çevrilir; fotoğraflı evraklarda dikkat."),
]
PROFILE_BY_KEY = {p.key: p for p in PROFILES}


def prepare_page(page: Page, enh: Enhancement | None, profile: Profile) -> tuple[Image.Image, float]:
    img, dpi = process_page(page.source, page.frame, page.rotation, enh)
    if profile.max_dpi and dpi > profile.max_dpi * 1.05:
        f = profile.max_dpi / dpi
        size = (max(1, round(img.width * f)), max(1, round(img.height * f)))
        if img.mode == "1":
            img = to_bitonal(img.convert("L").resize(size, Image.Resampling.LANCZOS), 160)
        else:
            img = img.resize(size, Image.Resampling.LANCZOS)
        dpi = float(profile.max_dpi)
    if img.mode == "RGB" and _looks_gray(img):
        img = img.convert("L")
    if profile.force_bitonal and img.mode != "1":
        img = to_bitonal(img)
    return img, dpi


def _looks_gray(img: Image.Image) -> bool:
    small = img.copy()
    small.thumbnail((300, 300))
    a = np.asarray(small, dtype=np.int16)
    return int(np.abs(a[..., 0] - a[..., 1]).max()) < 14 and int(np.abs(a[..., 1] - a[..., 2]).max()) < 14


def encode_for_pdf(img: Image.Image, dpi: float, quality: int) -> bytes:
    buf = io.BytesIO()
    if img.mode == "1":
        # Tek şerit G4: img2pdf veriyi yeniden sıkıştırmadan PDF'e gömer.
        img.save(buf, format="TIFF", compression="group4", dpi=(dpi, dpi), strip_size=2 ** 30)
    else:
        img.save(buf, format="JPEG", quality=quality, optimize=True, dpi=(round(dpi), round(dpi)))
    return buf.getvalue()


def build_pdf(pages: list[Page], enh: Enhancement | None, profile: Profile,
              ocr: OcrEngine | None, progress: Progress, step_offset: int = 0,
              total_steps: int = 0) -> tuple[bytes, int]:
    """(pdf verisi, OCR katmanı eklenemeyen sayfa sayısı)"""
    total = total_steps or len(pages)
    blobs: list[bytes] = []
    layers: list[bytes | None] = []
    for i, page in enumerate(pages):
        progress(step_offset + i, total, f"{i + 1}/{len(pages)}. sayfa işleniyor ({profile.name})")
        img, dpi = prepare_page(page, enh, profile)
        blobs.append(encode_for_pdf(img, dpi, profile.jpeg_quality))
        if ocr is not None:
            try:
                layers.append(ocr.textonly_pdf(img, dpi))
            except Exception:
                layers.append(None)
    pdf = img2pdf.convert(blobs)
    if ocr is not None:
        pdf = _merge_text_layers(pdf, layers)
    return pdf, sum(1 for x in layers if x is None)


def _merge_text_layers(pdf: bytes, layers: list[bytes | None]) -> bytes:
    from pypdf import PdfReader, PdfWriter, Transformation

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf)))
    for page, layer in zip(writer.pages, layers):
        if not layer:
            continue
        tp = PdfReader(io.BytesIO(layer)).pages[0]
        sx = float(page.mediabox.width) / float(tp.mediabox.width)
        sy = float(page.mediabox.height) / float(tp.mediabox.height)
        page.merge_transformed_page(tp, Transformation().scale(sx, sy))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def export_pdf(path: str, pages: list[Page], enh: Enhancement | None, profile: Profile,
               ocr: OcrEngine | None, progress: Progress) -> dict:
    data, ocr_failed = build_pdf(pages, enh, profile, ocr, progress)
    _write_atomic(path, data)
    progress(len(pages), len(pages), "Tamamlandı")
    return {"path": path, "size": len(data), "profile": profile, "pages": len(pages), "ocr_failed": ocr_failed}


def export_pdf_fit(path: str, pages: list[Page], enh: Enhancement | None, max_bytes: int,
                   ocr: OcrEngine | None, progress: Progress) -> dict:
    """Hedef boyuta sığan en yüksek kaliteli profili seçer."""
    n = len(pages)
    total = n * (len(PROFILES) + (1 if ocr else 0))
    chosen, data, ocr_failed = None, b"", 0
    for k, profile in enumerate(PROFILES):
        data, _ = build_pdf(pages, enh, profile, None, progress, k * n, total)
        chosen = profile
        if len(data) <= max_bytes:
            break
    if ocr is not None:
        data, ocr_failed = build_pdf(pages, enh, chosen, ocr, progress, total - n, total)
    _write_atomic(path, data)
    progress(total, total, "Tamamlandı")
    return {"path": path, "size": len(data), "profile": chosen, "pages": n,
            "fits": len(data) <= max_bytes, "limit": max_bytes, "ocr_failed": ocr_failed}


def export_tiff(path: str, pages: list[Page], enh: Enhancement | None, profile: Profile,
                progress: Progress) -> dict:
    tmp = path + ".part"
    n = len(pages)
    with TiffImagePlugin.AppendingTiffWriter(tmp, True) as tf:
        for i, page in enumerate(pages):
            progress(i, n, f"{i + 1}/{n}. sayfa yazılıyor")
            img, dpi = prepare_page(page, enh, profile)
            if img.mode == "1":
                opts = {"compression": "group4"}
            elif profile.key == "orijinal":
                opts = {"compression": "tiff_adobe_deflate"}
            else:
                opts = {"compression": "jpeg", "quality": profile.jpeg_quality}
            img.save(tf, format="TIFF", dpi=(dpi, dpi), **opts)
            tf.newFrame()
    os.replace(tmp, path)
    progress(n, n, "Tamamlandı")
    return {"path": path, "size": os.path.getsize(path), "profile": profile, "pages": n}


def _write_atomic(path: str, data: bytes) -> None:
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def parse_page_ranges(text: str, count: int) -> list[int]:
    """'1-3, 7, 10-' biçimindeki aralığı 0 tabanlı indekslere çevirir."""
    out: list[int] = []
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start = int(a) if a.strip() else 1
            end = int(b) if b.strip() else count
        else:
            start = end = int(part)
        if start < 1 or end > count or start > end:
            raise ValueError(f"Geçersiz aralık: {part}")
        out.extend(range(start - 1, end))
    seen = set()
    return [i for i in out if not (i in seen or seen.add(i))]
