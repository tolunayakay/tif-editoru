"""Tesseract OCR'ın uygulama içinden indirilip kurulması.

Windows: Projenin GitHub sürümlerinde yayımlanan taşınabilir Tesseract zip'i
(tools/make_tesseract_zip.py ile üretilir) kullanıcı klasörüne (%LOCALAPPDATA%) açılır.
Yönetici yetkisi gerekmez, bilgisayardaki başka Tesseract kurulumlarına dokunulmaz ve
indirilen dosya SHA-256 ile doğrulanır.
macOS: Homebrew varsa ``brew install tesseract tesseract-lang`` çalıştırılır.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from . import GITHUB_URL

Progress = Callable[[int, int, str], None]

TESS_VERSION = "5.4.0.20240606"
PORTABLE_NAME = "tesseract-portable-win64.zip"
PORTABLE_URL = f"{GITHUB_URL}/releases/download/tesseract-{TESS_VERSION}/{PORTABLE_NAME}"
PORTABLE_SHA256 = "49a8a4562e7149d5fa8f40aac0166cd140d2b9b4f18d033e87b5a8361c3f7b89"
PORTABLE_MB = 49
LANGS = {
    "tur": ("https://github.com/tesseract-ocr/tessdata/raw/main/tur.traineddata",
            "489b9504e80d7184ed1ac9a1976647884ee71149da231ff3c2c1dc15370f2f3d"),
}


class InstallError(RuntimeError):
    pass


def user_install_dir() -> Path | None:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        return Path(base) / "UyapTif" / "Tesseract-OCR" if base else None
    return None


def user_install_exists() -> bool:
    d = user_install_dir()
    return bool(d and (d / "tesseract.exe").is_file())


def brew_path() -> str | None:
    for c in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
        if os.path.isfile(c):
            return c
    return shutil.which("brew")


def supported() -> bool:
    return os.name == "nt" or (sys.platform == "darwin" and brew_path() is not None)


def unsupported_reason() -> str:
    if sys.platform == "darwin":
        return ("Homebrew bulunamadı. https://brew.sh adresinden Homebrew'u kurun ya da Terminal'de "
                "'brew install tesseract tesseract-lang' komutunu çalıştırın.")
    return "Bu işletim sisteminde otomatik kurulum desteklenmiyor; paket yöneticinizle 'tesseract' kurun."


# --------------------------------------------------------------------------- indirme

def _ssl_context() -> ssl.SSLContext:
    # İşletim sisteminin sertifika doğrulamasını kullan (kurumsal ağlar, eksik ara sertifikalar).
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        return ssl.create_default_context()


def _download(url: str, dest: Path, sha256: str, label: str, progress: Progress) -> None:
    h = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": "UyapTifViewer"})
    ctx = _ssl_context() if url.startswith("https:") else None
    with urllib.request.urlopen(req, timeout=60, context=ctx) as resp, open(dest, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            progress(done // 1024, max(total // 1024, done // 1024, 1),
                     f"{label} indiriliyor… {done / 1048576:.1f} / {total / 1048576:.1f} MB")
    if h.hexdigest() != sha256:
        dest.unlink(missing_ok=True)
        raise InstallError(f"{label} doğrulanamadı (SHA-256 uyuşmuyor). İndirme bozuk ya da değiştirilmiş olabilir.")


# --------------------------------------------------------------------------- Windows

def _install_windows(progress: Progress) -> str:
    target = user_install_dir()
    if target is None:
        raise InstallError("LOCALAPPDATA klasörü bulunamadı.")
    if not PORTABLE_SHA256:
        raise InstallError("Bu sürümde indirilebilir Tesseract paketi tanımlı değil.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="uyaptif_tess_") as tmp:
        archive = Path(tmp) / PORTABLE_NAME
        try:
            _download(PORTABLE_URL, archive, PORTABLE_SHA256, "Tesseract OCR", progress)
        except urllib.error.HTTPError as e:
            raise InstallError(f"Tesseract paketi indirilemedi (HTTP {e.code}).\n{PORTABLE_URL}") from e
        except urllib.error.URLError as e:
            raise InstallError(f"İnternet bağlantısı kurulamadı: {e.reason}") from e
        progress(0, 0, "Dosyalar açılıyor…")
        staging = target.with_name(target.name + ".yeni")
        shutil.rmtree(staging, ignore_errors=True)
        root = staging.resolve()
        with zipfile.ZipFile(archive) as z:
            for member in z.namelist():   # arşivden klasör dışına yazmayı engelle
                if not (staging / member).resolve().is_relative_to(root):
                    raise InstallError("Arşiv geçersiz dosya yolu içeriyor.")
            z.extractall(staging)
    if not (staging / "tesseract.exe").is_file():
        shutil.rmtree(staging, ignore_errors=True)
        raise InstallError("Arşivde tesseract.exe bulunamadı.")
    shutil.rmtree(target, ignore_errors=True)
    staging.rename(target)
    return str(target / "tesseract.exe")


def uninstall_windows() -> None:
    target = user_install_dir()
    if target is None or not target.exists():
        return
    shutil.rmtree(target, ignore_errors=True)
    if target.exists():
        raise InstallError(f"Klasör silinemedi: {target}\nOCR çalışıyorsa biraz bekleyip tekrar deneyin.")


# --------------------------------------------------------------------------- macOS

def _install_mac(progress: Progress) -> str:
    brew = brew_path()
    if brew is None:
        raise InstallError(unsupported_reason())
    progress(0, 0, "Homebrew ile Tesseract kuruluyor… (birkaç dakika sürebilir)")
    env = os.environ.copy()
    env["HOMEBREW_NO_AUTO_UPDATE"] = "1"
    proc = subprocess.Popen([brew, "install", "tesseract", "tesseract-lang"], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=env)
    for line in proc.stdout:
        line = line.strip()
        if line:
            progress(0, 0, line[:120])
    if proc.wait() != 0:
        raise InstallError("Homebrew kurulumu başarısız oldu. Terminal'de 'brew install tesseract tesseract-lang' deneyin.")
    exe = shutil.which("tesseract", path=os.path.dirname(brew))
    if not exe:
        raise InstallError("Kurulumdan sonra tesseract bulunamadı.")
    return exe


def install(progress: Progress) -> str:
    """Tesseract + Türkçe modeli kurar, tesseract yolunu döndürür."""
    if os.name == "nt":
        return _install_windows(progress)
    if sys.platform == "darwin":
        return _install_mac(progress)
    raise InstallError(unsupported_reason())
