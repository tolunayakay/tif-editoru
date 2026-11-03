"""Özel arayüz bileşenleri: anahtar (switch) ve ay/güneş tema anahtarı; tema yardımcıları."""
from __future__ import annotations

import math

from PySide6.QtCore import Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy

THEME_LIGHT, THEME_DARK, THEME_SYSTEM = "light", "dark", "system"


def apply_theme(mode: str) -> None:
    hints = QGuiApplication.styleHints()
    if mode == THEME_DARK:
        hints.setColorScheme(Qt.ColorScheme.Dark)
    elif mode == THEME_LIGHT:
        hints.setColorScheme(Qt.ColorScheme.Light)
    else:
        hints.unsetColorScheme()


def is_dark() -> bool:
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


class ToggleSwitch(QAbstractButton):
    """Kaydırmalı açık/kapalı anahtarı."""

    def __init__(self, parent=None, width: int = 44, height: int = 24):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._size = QSize(width, height)
        self._pos = 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:
        return self._size

    def _get_knob(self) -> float:
        return self._pos

    def _set_knob(self, v: float) -> None:
        self._pos = v
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def setChecked(self, on: bool) -> None:  # noqa: N802 - Qt adı
        super().setChecked(on)
        self._anim.stop()
        self._set_knob(1.0 if on else 0.0)

    def track_color(self) -> QColor:
        if not self.isEnabled():
            return self.palette().mid().color()
        on = self.palette().highlight().color()
        off = self.palette().mid().color()
        t = self._pos
        return QColor(round(off.red() + (on.red() - off.red()) * t),
                      round(off.green() + (on.green() - off.green()) * t),
                      round(off.blue() + (on.blue() - off.blue()) * t))

    def knob_rect(self) -> QRectF:
        h = self.height()
        d = h - 6
        x = 3 + (self.width() - d - 6) * self._pos
        return QRectF(x, 3, d, d)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.track_color())
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        self.paint_knob(p, self.knob_rect())
        p.end()

    def paint_knob(self, p: QPainter, k: QRectF) -> None:
        p.setBrush(QColor(255, 255, 255))
        p.setPen(QPen(QColor(0, 0, 0, 40), 1))
        p.drawEllipse(k)


class ThemeSwitch(ToggleSwitch):
    """Ay/güneş tema anahtarı: işaretli = koyu tema."""

    def __init__(self, parent=None):
        super().__init__(parent, 60, 28)
        self.setToolTip("Açık / koyu tema")

    def track_color(self) -> QColor:
        day, night = QColor(125, 190, 245), QColor(38, 45, 82)
        t = self._pos
        return QColor(round(day.red() + (night.red() - day.red()) * t),
                      round(day.green() + (night.green() - day.green()) * t),
                      round(day.blue() + (night.blue() - day.blue()) * t))

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Arka planda soluk yıldızlar (gece) / bulut (gündüz)
        p.setPen(Qt.PenStyle.NoPen)
        w, h = self.width(), self.height()
        if self._pos > 0.05:
            p.setBrush(QColor(255, 255, 255, int(200 * self._pos)))
            for x, y, s in ((0.18, 0.32, 1.6), (0.30, 0.62, 1.2), (0.42, 0.28, 1.0)):
                p.drawEllipse(QPointF(w * x, h * y), s, s)
        if self._pos < 0.95:
            p.setBrush(QColor(255, 255, 255, int(220 * (1 - self._pos))))
            p.drawEllipse(QPointF(w * 0.70, h * 0.58), 5, 4)
            p.drawEllipse(QPointF(w * 0.78, h * 0.52), 6, 5)
            p.drawEllipse(QPointF(w * 0.86, h * 0.60), 4, 3.5)
        p.end()

    def paint_knob(self, p: QPainter, k: QRectF) -> None:
        c = k.center()
        r = k.width() / 2
        if self._pos < 0.5:   # güneş
            pen = QPen(QColor(255, 196, 0), 1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            for i in range(8):
                a = i * math.pi / 4
                p.drawLine(QPointF(c.x() + math.cos(a) * r * 0.62, c.y() + math.sin(a) * r * 0.62),
                           QPointF(c.x() + math.cos(a) * r * 0.92, c.y() + math.sin(a) * r * 0.92))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 206, 40))
            p.drawEllipse(c, r * 0.48, r * 0.48)
        else:                 # hilal
            moon = QPainterPath()
            moon.addEllipse(c, r * 0.82, r * 0.82)
            cut = QPainterPath()
            cut.addEllipse(QPointF(c.x() + r * 0.42, c.y() - r * 0.30), r * 0.70, r * 0.70)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(245, 240, 210))
            p.drawPath(moon.subtracted(cut))
