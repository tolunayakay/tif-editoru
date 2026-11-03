"""Arka planda sayfa ve küçük resim işleme (lazy loading + LRU önbellek)."""
from __future__ import annotations

import threading
import traceback
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

from .document import Page
from .imaging import (Enhancement, apply_enhancement, load_frame, make_thumbnail,
                      pil_to_qimage, rotate_image)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], None]):
        super().__init__()
        self._fn = fn
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            self._fn()
        except Exception:
            traceback.print_exc()


@dataclass
class Rendered:
    image: Image.Image   # döndürülmüş + iyileştirilmiş tam çözünürlüklü görüntü
    qimage: QImage
    dpi: float
    _inverted: QImage | None = field(default=None, repr=False)

    def display(self, night: bool) -> QImage:
        if not night:
            return self.qimage
        if self._inverted is None:
            inv = self.qimage.copy()
            inv.invertPixels()
            self._inverted = inv
        return self._inverted

    @property
    def nbytes(self) -> int:
        bands = {"1": 0.125, "L": 1, "RGB": 3}.get(self.image.mode, 3)
        w, h = self.image.size
        return int(w * h * bands) + self.qimage.sizeInBytes()


RenderKey = tuple[int, int, Enhancement]


class RenderService(QObject):
    ready = Signal(object)          # RenderKey
    failed = Signal(object, str)    # RenderKey, hata

    def __init__(self, max_bytes: int = 450 * 1024 * 1024):
        super().__init__()
        self._cache: OrderedDict[RenderKey, Rendered] = OrderedDict()
        self._pending: set[RenderKey] = set()
        self._lock = threading.Lock()
        self._max_bytes = max_bytes
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(2)

    @staticmethod
    def key(page: Page, enh: Enhancement) -> RenderKey:
        return (page.uid, page.rotation, enh)

    def get(self, page: Page, enh: Enhancement) -> Rendered | None:
        k = self.key(page, enh)
        with self._lock:
            r = self._cache.get(k)
            if r is not None:
                self._cache.move_to_end(k)
            return r

    def request(self, page: Page, enh: Enhancement, priority: int = 0) -> None:
        k = self.key(page, enh)
        with self._lock:
            if k in self._cache or k in self._pending:
                return
            self._pending.add(k)
        src, frame = page.source, page.frame
        self._pool.start(_Task(lambda: self._work(k, src, frame)), priority)

    def render_sync(self, page: Page, enh: Enhancement) -> Rendered:
        r = self.get(page, enh)
        if r is None:
            k = self.key(page, enh)
            r = self._render(k, page.source, page.frame)
            self._store(k, r)
        return r

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    # ------------------------------------------------------------------ iç
    def _work(self, k: RenderKey, src: str, frame: int) -> None:
        try:
            r = self._render(k, src, frame)
        except Exception as e:
            with self._lock:
                self._pending.discard(k)
            self.failed.emit(k, str(e))
            return
        self._store(k, r)
        self.ready.emit(k)

    def _render(self, k: RenderKey, src: str, frame: int) -> Rendered:
        uid, rotation, enh = k
        base = None
        with self._lock:
            for (u, rot, e), r in self._cache.items():
                if u == uid and e == enh:
                    base = (rot, r)
                    break
        if base is not None:
            # Aynı sayfanın başka açıdaki hali önbellekte: dosyayı yeniden çözmeden döndür.
            rot, r = base
            img, dpi = rotate_image(r.image, (rotation - rot) % 360), r.dpi
        else:
            img, dpi = load_frame(src, frame)
            img = apply_enhancement(rotate_image(img, rotation), enh)
        return Rendered(img, pil_to_qimage(img), dpi)

    def _store(self, k: RenderKey, r: Rendered) -> None:
        with self._lock:
            self._pending.discard(k)
            self._cache[k] = r
            self._cache.move_to_end(k)
            total = sum(x.nbytes for x in self._cache.values())
            while total > self._max_bytes and len(self._cache) > 2:
                _, old = self._cache.popitem(last=False)
                total -= old.nbytes


class ThumbnailProvider(QObject):
    """Küçük resimleri döndürülmemiş halde üretir; döndürme arayüzde uygulanır."""
    ready = Signal(int, QImage)   # uid, görüntü

    def __init__(self, max_w: int, max_h: int):
        super().__init__()
        self._size = (max_w, max_h)
        self._pending: set[int] = set()
        self._lock = threading.Lock()
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(2)

    def request(self, page: Page) -> None:
        with self._lock:
            if page.uid in self._pending:
                return
            self._pending.add(page.uid)
        uid, src, frame = page.uid, page.source, page.frame
        self._pool.start(_Task(lambda: self._work(uid, src, frame)))

    def _work(self, uid: int, src: str, frame: int) -> None:
        try:
            img = make_thumbnail(src, frame, *self._size)
            q = pil_to_qimage(img)
        except Exception:
            q = QImage()
        self.ready.emit(uid, q)


class BackgroundTask(QObject):
    """Uzun işlemleri (dışa aktarma, boş sayfa tarama vb.) iş parçacığında çalıştırır."""
    progress = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)

    class Cancelled(Exception):
        pass

    def __init__(self, fn: Callable[["BackgroundTask"], object]):
        super().__init__()
        self._fn = fn
        self.cancel_event = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def report(self, done: int, total: int, msg: str = "") -> None:
        if self.cancel_event.is_set():
            raise BackgroundTask.Cancelled()
        self.progress.emit(done, total, msg)

    def _run(self) -> None:
        try:
            result = self._fn(self)
        except BackgroundTask.Cancelled:
            self.failed.emit("")
        except Exception as e:
            traceback.print_exc()
            self.failed.emit(str(e) or e.__class__.__name__)
        else:
            self.finished.emit(result)
