"""Tesseract OCR entegrasyonu: arka plan tarama, kelime arama, alan metni, yön tespiti.

Tesseract ayrı bir program olarak çağrılır; şu konumlarda aranır:
  1. Uygulamanın yanındaki ``tesseract/`` klasörü (taşınabilir paket)
  2. UYAPTIF_TESSERACT ortam değişkeni
  3. PATH ve bilinen kurulum dizinleri (Windows: Program Files, macOS: Homebrew)
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from collections import deque
from pathlib import Path
from typing import NamedTuple

from PIL import Image
from PySide6.QtCore import QObject, QRectF, Signal

from .document import Page
from .imaging import load_frame, rotate_image

EXE_NAME = "tesseract.exe" if os.name == "nt" else "tesseract"
_CREATE_NO_WINDOW = 0x08000000
_BELOW_NORMAL = 0x00004000


class OcrError(RuntimeError):
    pass


class Word(NamedTuple):
    text: str
    x: int
    y: int
    w: int
    h: int
    line: tuple[int, int, int]

    @property
    def rect(self) -> QRectF:
        return QRectF(self.x, self.y, self.w, self.h)


def _app_dirs() -> list[Path]:
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        dirs += [exe_dir, exe_dir.parent / "Resources"]
        if hasattr(sys, "_MEIPASS"):
            dirs.append(Path(sys._MEIPASS))
    root = Path(__file__).resolve().parent.parent
    dirs += [root, root / "vendor"]
    return dirs


def find_tesseract() -> tuple[str | None, str | None]:
    """(çalıştırılabilir dosya, paketle gelen tessdata dizini) döndürür."""
    for d in _app_dirs():
        exe = d / "tesseract" / EXE_NAME
        if exe.is_file():
            td = exe.parent / "tessdata"
            return str(exe), (str(td) if td.is_dir() else None)
    from .tess_install import user_install_dir
    user_dir = user_install_dir()
    if user_dir and (user_dir / EXE_NAME).is_file():
        return str(user_dir / EXE_NAME), None
    env = os.environ.get("UYAPTIF_TESSERACT")
    if env and Path(env).is_file():
        return env, None
    found = shutil.which("tesseract")
    if found:
        return found, None
    candidates = []
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                     os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
            if base:
                candidates.append(Path(base) / "Tesseract-OCR" / EXE_NAME)
    else:
        candidates += [Path("/opt/homebrew/bin/tesseract"), Path("/usr/local/bin/tesseract"),
                       Path("/opt/local/bin/tesseract"), Path("/usr/bin/tesseract")]
    for c in candidates:
        if c.is_file():
            return str(c), None
    return None, None


class OcrEngine:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.exe, self.tessdata = find_tesseract()
        self.langs: list[str] = []
        self.lang = "tur"
        if self.exe:
            try:
                out = self._run(["--list-langs"]).decode("utf-8", "replace")
                self.langs = [ln.strip() for ln in out.splitlines()[1:] if ln.strip()]
            except Exception:
                self.exe = None
        if "tur" not in self.langs and "eng" in self.langs:
            self.lang = "eng"

    @property
    def installed(self) -> bool:
        return bool(self.exe) and bool(self.langs)

    @property
    def available(self) -> bool:
        return self.enabled and self.installed

    @property
    def has_turkish(self) -> bool:
        return "tur" in self.langs

    @property
    def has_osd(self) -> bool:
        return "osd" in self.langs

    def status_text(self) -> str:
        if not self.enabled:
            return "OCR ayarlardan kapatıldı"
        if not self.exe:
            return "Tesseract bulunamadı"
        if not self.has_turkish:
            return "Türkçe dil modeli (tur) eksik"
        return f"Tesseract hazır ({self.lang})"

    # ------------------------------------------------------------------ alt süreç
    def _run(self, args: list[str], background: bool = False, timeout: int = 300) -> bytes:
        cmd = [self.exe]
        if self.tessdata:
            cmd += ["--tessdata-dir", self.tessdata]
        cmd += args
        env = os.environ.copy()
        flags = 0
        if os.name == "nt":
            flags |= _CREATE_NO_WINDOW
            if background:
                flags |= _BELOW_NORMAL
        if background:
            env["OMP_THREAD_LIMIT"] = "1"
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env,
                                  creationflags=flags, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired as e:
            raise OcrError("OCR zaman aşımına uğradı") from e
        if proc.returncode != 0:
            msg = proc.stderr.decode("utf-8", "replace").strip()
            raise OcrError(msg[-600:] or f"Tesseract hata kodu {proc.returncode}")
        return proc.stdout

    @staticmethod
    def _save_input(img: Image.Image, dpi: float, folder: str) -> str:
        path = os.path.join(folder, "in.png")
        if img.mode not in ("1", "L"):
            img = img.convert("L")
        img.save(path, dpi=(dpi, dpi))
        return path

    # ------------------------------------------------------------------ işlemler
    def words(self, img: Image.Image, dpi: float, background: bool = True) -> list[Word]:
        with tempfile.TemporaryDirectory(prefix="uyaptif_") as tmp:
            src = self._save_input(img, dpi, tmp)
            out = self._run([src, "stdout", "-l", self.lang, "--psm", "3", "--dpi", str(int(dpi)), "tsv"],
                            background=background)
        return parse_tsv(out.decode("utf-8", "replace"))

    def text(self, img: Image.Image, dpi: float) -> str:
        if dpi < 250:   # küçük alanlarda tanıma kalitesi için büyüt
            f = 300.0 / dpi
            img = img.convert("L").resize((round(img.width * f), round(img.height * f)), Image.Resampling.LANCZOS)
            dpi = 300.0
        with tempfile.TemporaryDirectory(prefix="uyaptif_") as tmp:
            src = self._save_input(img, dpi, tmp)
            out = self._run([src, "stdout", "-l", self.lang, "--psm", "6", "--dpi", str(int(dpi))])
        text = out.decode("utf-8", "replace").replace("\r\n", "\n").replace("\f", "")
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    def textonly_pdf(self, img: Image.Image, dpi: float) -> bytes:
        with tempfile.TemporaryDirectory(prefix="uyaptif_") as tmp:
            src = self._save_input(img, dpi, tmp)
            base = os.path.join(tmp, "out")
            self._run([src, base, "-l", self.lang, "--psm", "3", "--dpi", str(int(dpi)),
                       "-c", "textonly_pdf=1", "pdf"])
            with open(base + ".pdf", "rb") as f:
                return f.read()

    def orientation(self, img: Image.Image, dpi: float, min_conf: float = 3.0) -> int:
        """Sayfayı düz okumak için gereken saat yönü dönüş açısı (0/90/180/270)."""
        if dpi > 300:
            f = 300.0 / dpi
            img = img.convert("L").resize((round(img.width * f), round(img.height * f)), Image.Resampling.BOX)
            dpi = 300.0
        with tempfile.TemporaryDirectory(prefix="uyaptif_") as tmp:
            src = self._save_input(img, dpi, tmp)
            try:
                out = self._run([src, "stdout", "--psm", "0", "-l", "osd", "--dpi", str(int(dpi))])
            except OcrError:
                return 0   # çok az metin varsa Tesseract hata verir
        text = out.decode("utf-8", "replace")
        m_deg = re.search(r"Orientation in degrees:\s*(\d+)", text)
        m_conf = re.search(r"Orientation confidence:\s*([\d.]+)", text)
        if not m_deg or not m_conf or float(m_conf.group(1)) < min_conf:
            return 0
        return int(m_deg.group(1)) % 360


def parse_tsv(tsv: str) -> list[Word]:
    words: list[Word] = []
    for ln in tsv.splitlines()[1:]:
        parts = ln.split("\t")
        if len(parts) < 12 or parts[0] != "5":
            continue
        text = parts[11].strip()
        if not text:
            continue
        try:
            block, par, line = int(parts[2]), int(parts[3]), int(parts[4])
            x, y, w, h = (int(v) for v in parts[6:10])
        except ValueError:
            continue
        words.append(Word(text, x, y, w, h, (block, par, line)))
    return words


# --------------------------------------------------------------------------- arama

_TR_LOWER = str.maketrans({"I": "ı", "İ": "i"})
_TR_FOLD = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u",
                          "â": "a", "î": "i", "û": "u"})
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def normalize(s: str, fold: bool) -> str:
    s = s.translate(_TR_LOWER).lower()
    if fold:
        s = s.translate(_TR_FOLD)
    return _NON_WORD.sub("", s)


def find_matches(words: list[Word], query: str, fold: bool = True) -> list[list[QRectF]]:
    """Sorgu eşleşmeleri; her eşleşme kelime kutularının listesidir."""
    toks = [t for t in (normalize(q, fold) for q in query.split()) if t]
    if not toks or not words:
        return []
    normed = [normalize(w.text, fold) for w in words]
    n = len(toks)
    out: list[list[QRectF]] = []
    for i in range(len(words) - n + 1):
        if n == 1:
            ok = toks[0] in normed[i]
        else:
            ok = (normed[i].endswith(toks[0]) and normed[i + n - 1].startswith(toks[-1])
                  and all(toks[k] == normed[i + k] for k in range(1, n - 1)))
        if ok:
            out.append(_merge_lines(words[i:i + n]))
    return out


def _merge_lines(ws: list[Word]) -> list[QRectF]:
    rects: list[QRectF] = []
    last_line = None
    for w in ws:
        if rects and w.line == last_line:
            rects[-1] = rects[-1].united(w.rect)
        else:
            rects.append(w.rect)
        last_line = w.line
    return rects


# --------------------------------------------------------------------------- arka plan

class OcrManager(QObject):
    """Sayfaları sırayla, düşük öncelikte OCR'dan geçirir."""
    pageDone = Signal(int)     # uid
    failed = Signal(str)

    def __init__(self, engine: OcrEngine):
        super().__init__()
        self.engine = engine
        self._results: dict[int, tuple[int, list[Word]]] = {}
        self._queue: deque[Page] = deque()
        self._cv = threading.Condition()
        self._running = True
        self._busy_uid: int | None = None
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def words_for(self, page: Page) -> list[Word] | None:
        r = self._results.get(page.uid)
        if r is None or r[0] != page.rotation:
            return None
        return r[1]

    def is_done(self, page: Page) -> bool:
        return self.words_for(page) is not None

    def schedule(self, pages: list[Page]) -> None:
        if not self.engine.available:
            return
        with self._cv:
            queued = {p.uid for p in self._queue}
            for p in pages:
                if p.uid not in queued and not self.is_done(p):
                    self._queue.append(p)
                    queued.add(p.uid)
            self._cv.notify()

    def prioritize(self, page: Page) -> None:
        with self._cv:
            for p in list(self._queue):
                if p.uid == page.uid:
                    self._queue.remove(p)
                    self._queue.appendleft(p)
                    break

    def pending(self) -> int:
        with self._cv:
            return len(self._queue) + (1 if self._busy_uid is not None else 0)

    def cancel(self) -> None:
        with self._cv:
            self._queue.clear()

    def stop(self) -> None:
        with self._cv:
            self._running = False
            self._queue.clear()
            self._cv.notify()

    def _loop(self) -> None:
        while True:
            with self._cv:
                while self._running and not self._queue:
                    self._cv.wait()
                if not self._running:
                    return
                page = self._queue.popleft()
                rotation = page.rotation
                if self.is_done(page):
                    continue
                self._busy_uid = page.uid
            try:
                img, dpi = load_frame(page.source, page.frame)
                words = self.engine.words(rotate_image(img, rotation), dpi)
            except Exception as e:
                self.failed.emit(f"{page.label}: {e}")
                words = []
            self._results[page.uid] = (rotation, words)
            with self._cv:
                self._busy_uid = None
            self.pageDone.emit(page.uid)
