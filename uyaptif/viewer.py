"""Sayfa görüntüleme alanı: yakınlaştırma, kaydırma, seçim ve büyüteç."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QImage, QPainter, QPainterPath, QPen,
                           QPixmap, QTransform)
from PySide6.QtWidgets import (QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene,
                               QGraphicsView, QRubberBand, QWidget)

MIN_ZOOM, MAX_ZOOM = 0.03, 16.0
FIT_PAGE, FIT_WIDTH = "page", "width"
TOOL_HAND, TOOL_SELECT = "hand", "select"


class Magnifier(QWidget):
    """İmleci takip eden dairesel büyüteç (ıslak imza, mühür, kaşe incelemesi için)."""

    def __init__(self, view: "PageView"):
        super().__init__(view.viewport())
        self._view = view
        self.factor = 2.5
        self._center = QPointF()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.resize(260, 260)
        self.hide()

    def follow(self, viewport_pos: QPoint) -> None:
        self._center = self._view.mapToScene(viewport_pos)
        self.move(viewport_pos - QPoint(self.width() // 2, self.height() // 2))
        self.show()
        self.raise_()
        self.update()

    def paintEvent(self, _event) -> None:
        img = self._view.image
        if img is None:
            return
        scale = max(self._view.zoom * self.factor, 0.05)
        sw, sh = self.width() / scale, self.height() / scale
        src = QRectF(self._center.x() - sw / 2, self._center.y() - sh / 2, sw, sh)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        path = QPainterPath()
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        path.addEllipse(r)
        p.setClipPath(path)
        p.fillRect(self.rect(), QColor(90, 90, 90))
        p.drawImage(QRectF(self.rect()), img, src)
        p.setClipping(False)
        p.setPen(QPen(QColor(30, 120, 220), 3))
        p.drawEllipse(r)
        p.setPen(QPen(QColor(30, 120, 220, 160), 1))
        c = QRectF(self.rect()).center()
        p.drawLine(QPointF(c.x() - 8, c.y()), QPointF(c.x() + 8, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - 8), QPointF(c.x(), c.y() + 8))
        p.end()


class PageView(QGraphicsView):
    zoomChanged = Signal(float)
    nextPageRequested = Signal()
    prevPageRequested = Signal()
    selectionFinished = Signal(QRectF, QPoint)   # görüntü koordinatlarında alan, ekran konumu
    selectionCleared = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self._item = QGraphicsPixmapItem()
        self._item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.scene().addItem(self._item)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor(72, 72, 76))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.viewport().setMouseTracking(True)

        self.image: QImage | None = None
        self._full_pixmap: QPixmap | None = None
        self.zoom = 1.0
        self.fit_mode: str | None = FIT_PAGE
        self.wheel_zooms = False
        self._tool = TOOL_HAND
        self._space = False
        self._loading: str | None = None
        self._edge_acc = 0
        self._mid_pan: QPoint | None = None
        self._sel_origin: QPoint | None = None
        self._rubber = QRubberBand(QRubberBand.Shape.Rectangle, self.viewport())
        self._sel_item: QGraphicsRectItem | None = None
        self._highlights: list[QGraphicsRectItem] = []
        self.magnifier = Magnifier(self)
        self.magnifier_on = False

        self._hq_timer = QTimer(self, singleShot=True, interval=120)
        self._hq_timer.timeout.connect(self._update_hq_pixmap)
        self._apply_tool()

    # ------------------------------------------------------------------ görüntü
    def set_image(self, image: QImage, scroll: str = "top", keep_view: bool = False) -> None:
        old_size = self.image.size() if self.image is not None else None
        self.image = image
        self._full_pixmap = QPixmap.fromImage(image)
        self._item.setPixmap(self._full_pixmap)
        self._item.setScale(1.0)
        self.scene().setSceneRect(QRectF(0, 0, image.width(), image.height()))
        self.clear_selection()
        self.set_highlights([])
        self._loading = None
        if keep_view and old_size == image.size():
            self._hq_timer.start()
            self.viewport().update()
            return
        if self.fit_mode:
            self.apply_fit(self.fit_mode)
        else:
            self.set_zoom(self.zoom)
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum() if scroll == "bottom" else bar.minimum())
        self.horizontalScrollBar().setValue(
            (self.horizontalScrollBar().maximum() + self.horizontalScrollBar().minimum()) // 2)

    def clear_image(self) -> None:
        self.image = None
        self._full_pixmap = None
        self._item.setPixmap(QPixmap())
        self.scene().setSceneRect(QRectF(0, 0, 1, 1))
        self.clear_selection()
        self.set_highlights([])
        self.magnifier.hide()

    def set_overlay(self, text: str | None) -> None:
        """Sayfanın üzerine yarı saydam bir mesaj çizer (ör. 'Sayfa yükleniyor…')."""
        self._loading = text
        self.viewport().update()

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        if not self._loading:
            return
        painter.save()
        painter.resetTransform()
        vr = self.viewport().rect()
        painter.fillRect(vr, QColor(0, 0, 0, 70))
        painter.setPen(QColor(255, 255, 255))
        f = painter.font()
        f.setPointSize(13)
        painter.setFont(f)
        painter.drawText(vr, Qt.AlignmentFlag.AlignCenter, self._loading)
        painter.restore()

    def _update_hq_pixmap(self) -> None:
        """Uzaklaştırınca yazıların bozulmaması için alan-ortalamalı küçültme kullan."""
        if self.image is None:
            return
        dpr = self.devicePixelRatioF()
        eff = self.zoom * dpr
        if eff >= 0.95:
            if self._item.pixmap().cacheKey() != self._full_pixmap.cacheKey():
                self._item.setPixmap(self._full_pixmap)
                self._item.setScale(1.0)
            return
        tw = max(1, round(self.image.width() * eff))
        th = max(1, round(self.image.height() * eff))
        scaled = self.image.scaled(tw, th, Qt.AspectRatioMode.IgnoreAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
        self._item.setPixmap(QPixmap.fromImage(scaled))
        self._item.setScale(self.image.width() / tw)

    # ------------------------------------------------------------------ yakınlaştırma
    def set_zoom(self, z: float, anchor: QPoint | None = None) -> None:
        z = max(MIN_ZOOM, min(MAX_ZOOM, z))
        scene_pt = self.mapToScene(anchor) if anchor is not None else None
        self.setTransform(QTransform.fromScale(z, z))
        if scene_pt is not None:
            delta = self.mapFromScene(scene_pt) - anchor
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + delta.y())
        self.zoom = z
        self._hq_timer.start()
        self.zoomChanged.emit(z)
        if self.magnifier.isVisible():
            self.magnifier.update()

    def zoom_by(self, factor: float, anchor: QPoint | None = None) -> None:
        self.fit_mode = None
        if anchor is None:
            anchor = self.viewport().rect().center()
        self.set_zoom(self.zoom * factor, anchor)

    def apply_fit(self, mode: str) -> None:
        self.fit_mode = mode
        if self.image is None:
            return
        vw = max(10, self.viewport().width() - 16)
        vh = max(10, self.viewport().height() - 16)
        w, h = self.image.width(), self.image.height()
        if mode == FIT_WIDTH:
            z = vw / w
            if h * z > vh:   # dikey kaydırma çubuğu çıkacak
                z = max(10, vw - self.verticalScrollBar().sizeHint().width()) / w
        else:
            z = min(vw / w, vh / h)
        self.set_zoom(z)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.fit_mode:
            self.apply_fit(self.fit_mode)

    # ------------------------------------------------------------------ araçlar
    def set_tool(self, tool: str) -> None:
        self._tool = tool
        self._apply_tool()

    def set_space_pan(self, active: bool) -> None:
        if self._space != active:
            self._space = active
            self._apply_tool()

    def _apply_tool(self) -> None:
        hand = self._space or self._tool == TOOL_HAND
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag if hand else QGraphicsView.DragMode.NoDrag)
        self.viewport().setCursor(Qt.CursorShape.OpenHandCursor if hand else Qt.CursorShape.CrossCursor)

    def set_magnifier(self, on: bool) -> None:
        self.magnifier_on = on
        if not on:
            self.magnifier.hide()
        else:
            pos = self.viewport().mapFromGlobal(self.cursor().pos())
            if self.viewport().rect().contains(pos) and self.image is not None:
                self.magnifier.follow(pos)

    # ------------------------------------------------------------------ seçim ve vurgular
    def clear_selection(self) -> None:
        if self._sel_item is not None:
            self.scene().removeItem(self._sel_item)
            self._sel_item = None

    @property
    def selection(self) -> QRectF | None:
        return self._sel_item.rect() if self._sel_item is not None else None

    def _set_selection(self, rect: QRectF) -> None:
        self.clear_selection()
        item = QGraphicsRectItem(rect)
        pen = QPen(QColor(30, 120, 220), 2, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        item.setPen(pen)
        item.setBrush(QBrush(QColor(30, 120, 220, 40)))
        item.setZValue(10)
        self.scene().addItem(item)
        self._sel_item = item

    def set_highlights(self, rects: list[QRectF], current: int = -1) -> None:
        for it in self._highlights:
            self.scene().removeItem(it)
        self._highlights = []
        for i, r in enumerate(rects):
            it = QGraphicsRectItem(r.adjusted(-3, -3, 3, 3))
            cur = i == current
            it.setBrush(QBrush(QColor(255, 140, 0, 110) if cur else QColor(255, 230, 0, 90)))
            pen = QPen(QColor(230, 90, 0) if cur else QColor(200, 170, 0), 2)
            pen.setCosmetic(True)
            it.setPen(pen)
            it.setZValue(5)
            self.scene().addItem(it)
            self._highlights.append(it)
        if 0 <= current < len(rects):
            r = rects[current]
            self.ensureVisible(r, 80, 80)

    # ------------------------------------------------------------------ fare/klavye
    def wheelEvent(self, e) -> None:
        mods = e.modifiers()
        dy = e.angleDelta().y()
        if self.magnifier_on and mods & Qt.KeyboardModifier.ShiftModifier:
            self.magnifier.factor = max(1.2, min(8.0, self.magnifier.factor * (1.0015 ** dy)))
            self.magnifier.update()
            return
        if mods & Qt.KeyboardModifier.ControlModifier or (self.wheel_zooms and not mods):
            if dy:
                self.zoom_by(1.0015 ** dy, e.position().toPoint())
            return
        bar = self.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum()
        at_top = bar.value() <= bar.minimum()
        need = 120 if bar.maximum() == bar.minimum() else 240
        if dy < 0 and at_bottom:
            self._edge_acc = max(0, self._edge_acc) - dy
            if self._edge_acc >= need:
                self._edge_acc = 0
                self.nextPageRequested.emit()
            return
        if dy > 0 and at_top:
            self._edge_acc = min(0, self._edge_acc) - dy
            if -self._edge_acc >= need:
                self._edge_acc = 0
                self.prevPageRequested.emit()
            return
        self._edge_acc = 0
        super().wheelEvent(e)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.MiddleButton:
            self._mid_pan = e.position().toPoint()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if (e.button() == Qt.MouseButton.LeftButton and self._tool == TOOL_SELECT
                and not self._space and self.image is not None):
            self._sel_origin = e.position().toPoint()
            self._rubber.setGeometry(QRect(self._sel_origin, QSize()))
            self._rubber.show()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:
        pos = e.position().toPoint()
        if self.magnifier_on and self.image is not None:
            self.magnifier.follow(pos)
        if self._mid_pan is not None:
            d = pos - self._mid_pan
            self._mid_pan = pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - d.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - d.y())
            return
        if self._sel_origin is not None:
            self._rubber.setGeometry(QRect(self._sel_origin, pos).normalized())
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.MiddleButton and self._mid_pan is not None:
            self._mid_pan = None
            self._apply_tool()
            return
        if self._sel_origin is not None and e.button() == Qt.MouseButton.LeftButton:
            vr = QRect(self._sel_origin, e.position().toPoint()).normalized()
            self._sel_origin = None
            self._rubber.hide()
            rect = self.mapToScene(vr).boundingRect().intersected(self.sceneRect())
            if vr.width() > 4 and vr.height() > 4 and rect.width() >= 2 and rect.height() >= 2:
                rect = QRectF(rect.toAlignedRect())
                self._set_selection(rect)
                self.selectionFinished.emit(rect, e.globalPosition().toPoint())
            else:
                self.clear_selection()
                self.selectionCleared.emit()
            return
        super().mouseReleaseEvent(e)
        self._apply_tool()

    def leaveEvent(self, e) -> None:
        self.magnifier.hide()
        super().leaveEvent(e)
