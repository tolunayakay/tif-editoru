"""Belge modeli: birden çok dosyadan gelen sayfaların sıralı listesi."""
from __future__ import annotations

import itertools
import os
from dataclasses import dataclass, field

from .imaging import count_frames

_uid_counter = itertools.count(1)


@dataclass(eq=False)
class Page:
    source: str
    frame: int
    rotation: int = 0          # saat yönünde derece (0/90/180/270)
    uid: int = field(default_factory=lambda: next(_uid_counter))

    @property
    def label(self) -> str:
        return f"{os.path.basename(self.source)} · s.{self.frame + 1}"


class Document:
    UNDO_LIMIT = 50

    def __init__(self) -> None:
        self.pages: list[Page] = []
        self.files: list[str] = []
        self.modified = False
        self._undo: list[list[tuple[Page, int]]] = []

    # ------------------------------------------------------------------ dosyalar
    def add_file(self, path: str) -> int:
        path = os.path.abspath(path)
        n = count_frames(path)
        self.pages.extend(Page(path, i) for i in range(n))
        self.files.append(path)
        if len(self.files) > 1:
            self.modified = True
        return n

    @property
    def title(self) -> str:
        if not self.files:
            return ""
        name = os.path.basename(self.files[0])
        if len(self.files) > 1:
            name += f" (+{len(self.files) - 1} dosya)"
        return name

    # ------------------------------------------------------------------ geri al
    def snapshot(self) -> None:
        self._undo.append([(p, p.rotation) for p in self.pages])
        del self._undo[: -self.UNDO_LIMIT]

    def can_undo(self) -> bool:
        return bool(self._undo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        state = self._undo.pop()
        for page, rot in state:
            page.rotation = rot
        self.pages = [p for p, _ in state]
        self.modified = True
        return True

    # ------------------------------------------------------------------ sayfa işlemleri
    def index_of(self, uid: int) -> int:
        for i, p in enumerate(self.pages):
            if p.uid == uid:
                return i
        return -1

    def rotate(self, indices: list[int], degrees: int) -> None:
        self.snapshot()
        for i in indices:
            self.pages[i].rotation = (self.pages[i].rotation + degrees) % 360
        self.modified = True

    def delete(self, indices: list[int]) -> None:
        self.snapshot()
        drop = set(indices)
        self.pages = [p for i, p in enumerate(self.pages) if i not in drop]
        self.modified = True

    def reorder(self, uids: list[int]) -> None:
        by_uid = {p.uid: p for p in self.pages}
        new = [by_uid[u] for u in uids if u in by_uid]
        if len(new) == len(self.pages) and new != self.pages:
            self.pages = new
            self.modified = True
