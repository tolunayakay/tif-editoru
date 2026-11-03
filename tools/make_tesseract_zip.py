"""Kurulu bir Windows Tesseract'ından taşınabilir zip üretir (GitHub Releases'a yüklenmek üzere).

Yalnızca tesseract.exe'nin gerçekten ihtiyaç duyduğu DLL'ler (PE import zinciri) ve
tur/eng/osd dil modelleri alınır. Kullanım:

    python tools/make_tesseract_zip.py ["C:\\Program Files\\Tesseract-OCR"]

Çıktı: dist/tesseract-portable-win64.zip ve SHA-256 özeti (uyaptif/tess_install.py'deki
PORTABLE_SHA256 değerine yazılmalıdır).
"""
import hashlib
import os
import sys
import urllib.request
import zipfile

import pefile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from uyaptif.tess_install import LANGS, PORTABLE_NAME, _ssl_context  # noqa: E402

SRC = sys.argv[1] if len(sys.argv) > 1 else r"C:\Program Files\Tesseract-OCR"
OUT = os.path.join(os.path.dirname(__file__), "..", "dist", PORTABLE_NAME)
NOTICE = """Bu klasör UYAP TIFF Görüntüleyici tarafından OCR için kullanılır.

Tesseract OCR - Apache License 2.0 - https://github.com/tesseract-ocr/tesseract
Windows derlemesi: UB Mannheim - https://github.com/UB-Mannheim/tesseract
Leptonica - BSD 2-Clause - http://www.leptonica.org
Dil modelleri - Apache License 2.0 - https://github.com/tesseract-ocr/tessdata
Diğer DLL'ler (libtiff, libpng, zlib, libjpeg, libwebp, libarchive vb.) kendi açık kaynak
lisanslarıyla dağıtılır.
"""


def needed_dlls() -> list[str]:
    avail = {f.lower(): f for f in os.listdir(SRC) if f.lower().endswith(".dll")}
    need: set[str] = set()
    stack = ["tesseract.exe"]
    while stack:
        pe = pefile.PE(os.path.join(SRC, stack.pop()), fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
        for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
            name = entry.dll.decode().lower()
            if name in avail and name not in need:
                need.add(name)
                stack.append(avail[name])
    return sorted(avail[n] for n in need)


def main() -> None:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in ["tesseract.exe"] + needed_dlls():
            z.write(os.path.join(SRC, f), f)
        td = os.path.join(SRC, "tessdata")
        for f in ("eng.traineddata", "osd.traineddata", "pdf.ttf"):
            z.write(os.path.join(td, f), f"tessdata/{f}")
        for sub in ("configs", "tessconfigs"):
            for root, _, files in os.walk(os.path.join(td, sub)):
                for f in files:
                    full = os.path.join(root, f)
                    z.write(full, "tessdata/" + os.path.relpath(full, td).replace(os.sep, "/"))
        for lang, (url, sha) in LANGS.items():
            local = os.path.join(td, f"{lang}.traineddata")
            data = open(local, "rb").read() if os.path.isfile(local) else urllib.request.urlopen(url, context=_ssl_context()).read()
            if hashlib.sha256(data).hexdigest() != sha:
                raise SystemExit(f"{lang}.traineddata özeti uyuşmuyor")
            z.writestr(f"tessdata/{lang}.traineddata", data)
        z.writestr("NOTICE.txt", NOTICE)
    digest = hashlib.sha256(open(OUT, "rb").read()).hexdigest()
    print(f"{os.path.abspath(OUT)}\n{os.path.getsize(OUT) / 1048576:.1f} MB\nSHA-256: {digest}")


if __name__ == "__main__":
    main()
