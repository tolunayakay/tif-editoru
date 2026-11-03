"""Sol taraftaki sayfa önizleme paneli (sürükle-bırak ile sıralama destekli)."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (QAbstractItemView, QListWidget, QListWidgetItem, QStyle,
                               QStyledItemDelegate)

from .document import Page

THUMB_W, THUMB_H = 130, 170
UID_ROLE = Qt.ItemDataRole.UserRole + 1
PIX_ROLE = Qt.ItemDataRole.UserRole + 2


class ThumbDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index) -> QSize:
        return QSize(THUMB_W + 24, THUMB_H + 30)

    def paint(self, p: QPainter, opt, index) -> None:
        p.save()
        r = opt.rect
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        if selected:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(opt.palette.highlight())
            p.drawRoundedRect(r.adjusted(3, 2, -3, -2), 6, 6)

        area = QRect(r.x() + 12, r.y() + 6, r.width() - 24, THUMB_H)
        pix: QPixmap | None = index.data(PIX_ROLE)
        if pix is not None and not pix.isNull():
            size = pix.deviceIndependentSize().toSize().scaled(area.size(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRect(QPoint(0, 0), size)
            target.moveCenter(area.center())
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawPixmap(target, pix)
        else:
            target = QRect(0, 0, int(area.height() * 0.707), area.height())
            target.moveCenter(area.center())
            p.fillRect(target, QColor(245, 245, 245))
            p.setPen(QColor(150, 150, 150))
            p.drawText(target, Qt.AlignmentFlag.AlignCenter, "…")
        p.setPen(QPen(QColor(120, 120, 120), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(target)

        f = QFont(opt.font)
        f.setBold(selected)
        p.setFont(f)
        p.setPen(opt.palette.highlightedText().color() if selected else opt.palette.text().color())
        p.drawText(QRect(r.x(), area.bottom() + 4, r.width(), 20), Qt.AlignmentFlag.AlignCenter,
                   str(index.row() + 1))
        p.restore()


class ThumbList(QListWidget):
    pageActivated = Signal(int)          # satır
    aboutToReorder = Signal()
    orderChanged = Signal(list)          # uid listesi
    visibleRowsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(ThumbDelegate(self))
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setUniformItemSizes(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumWidth(THUMB_W + 44)
        self.setSpacing(2)
        self._base: dict[int, QImage] = {}                    # uid -> döndürülmemiş küçük resim
        self._pix_cache: dict[tuple[int, int], QPixmap] = {}  # (uid, açı) -> pixmap
        self._visible_timer = QTimer(self, singleShot=True, interval=40)
        self._visible_timer.timeout.connect(self.visibleRowsChanged)
        self.verticalScrollBar().valueChanged.connect(lambda _: self._visible_timer.start())
        self.currentRowChanged.connect(self._on_current_row)

    # ------------------------------------------------------------------ içerik
    def set_pages(self, pages: list[Page], current: int = 0) -> None:
        bar = self.verticalScrollBar().value()
        self.blockSignals(True)
        self.clear()
        for page in pages:
            it = QListWidgetItem()
            it.setData(UID_ROLE, page.uid)
            it.setData(PIX_ROLE, self._pixmap_for(page))
            it.setToolTip(page.label)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsDragEnabled)
            self.addItem(it)
        if 0 <= current < len(pages):
            self.setCurrentRow(current)
        self.blockSignals(False)
        self.verticalScrollBar().setValue(bar)
        self._visible_timer.start()

    def refresh_page(self, row: int, page: Page) -> None:
        it = self.item(row)
        if it is not None:
            it.setData(PIX_ROLE, self._pixmap_for(page))

    def set_base_thumbnail(self, uid: int, img: QImage, pages: list[Page]) -> None:
        self._base[uid] = img
        for row in range(self.count()):
            it = self.item(row)
            if it.data(UID_ROLE) == uid:
                it.setData(PIX_ROLE, self._pixmap_for(pages[row]))
                break

    def has_thumbnail(self, uid: int) -> bool:
        return uid in self._base

    def forget_all(self) -> None:
        self._base.clear()
        self._pix_cache.clear()

    def _pixmap_for(self, page: Page) -> QPixmap | None:
        key = (page.uid, page.rotation)
        if key in self._pix_cache:
            return self._pix_cache[key]
        img = self._base.get(page.uid)
        if img is None or img.isNull():
            return None
        if page.rotation:
            img = img.transformed(QTransform().rotate(page.rotation), Qt.TransformationMode.SmoothTransformation)
        pix = QPixmap.fromImage(img)
        pix.setDevicePixelRatio(max(1.0, max(img.width() / THUMB_W, img.height() / THUMB_H)))
        self._pix_cache[key] = pix
        return pix

    # ------------------------------------------------------------------ durum
    def set_current(self, row: int) -> None:
        if row == self.currentRow() and self.item(row) and self.item(row).isSelected():
            return
        self.blockSignals(True)
        self.setCurrentRow(row)
        self.blockSignals(False)
        it = self.item(row)
        if it is not None:
            self.scrollToItem(it, QAbstractItemView.ScrollHint.EnsureVisible)

    def selected_rows(self) -> list[int]:
        return sorted(self.row(it) for it in self.selectedItems())

    def select_rows(self, rows: list[int]) -> None:
        self.clearSelection()
        for r in rows:
            it = self.item(r)
            if it is not None:
                it.setSelected(True)
        if rows:
            self.scrollToItem(self.item(rows[0]))

    def visible_rows(self) -> range:
        n = self.count()
        if n == 0:
            return range(0)
        vp = self.viewport().rect()
        top = self.indexAt(vp.topLeft() + QPoint(10, 5))
        bottom = self.indexAt(vp.bottomLeft() + QPoint(10, -5))
        start = top.row() if top.isValid() else 0
        end = bottom.row() if bottom.isValid() else n - 1
        return range(max(0, start - 4), min(n, end + 6))

    def _on_current_row(self, row: int) -> None:
        if row >= 0:
            self.pageActivated.emit(row)

    # ------------------------------------------------------------------ sürükle-bırak
    def dropEvent(self, e) -> None:
        if e.source() is not self:
            e.ignore()
            return
        self.aboutToReorder.emit()
        super().dropEvent(e)
        QTimer.singleShot(0, self._emit_order)

    def _emit_order(self) -> None:
        self.orderChanged.emit([self.item(i).data(UID_ROLE) for i in range(self.count())])

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._visible_timer.start()
