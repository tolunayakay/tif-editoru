"""Ana pencere: menüler, araç çubuğu, sayfa yönetimi, arama, OCR ve dışa aktarma."""
from __future__ import annotations

import dataclasses
import datetime
import os
import re
import sys

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import (QAction, QActionGroup, QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPainter,
                           QPixmap, QTransform)
from PySide6.QtPrintSupport import QAbstractPrintDialog, QPrintDialog, QPrinter
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QDockWidget,
                               QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QMainWindow, QMenu, QMessageBox, QProgressDialog, QSizePolicy,
                               QSpinBox, QStyle, QToolBar, QToolButton, QVBoxLayout, QWidget)

from . import APP_NAME, APP_ORG, __version__
from . import platform_integration as plat
from . import tess_install, updater
from .dialogs import (FIT_PROFILE, AboutDialog, EnhanceDialog, ExportDialog, SettingsDialog,
                      ShortcutsDialog)
from .document import Document, Page
from .export import PROFILE_BY_KEY, export_pdf, export_pdf_fit, export_tiff
from .imaging import Enhancement, ink_ratio, load_frame, pil_to_qimage, rotate_image
from .ocr import OcrEngine, OcrManager, find_matches
from .render import BackgroundTask, RenderService, ThumbnailProvider
from .thumbs import THUMB_H, THUMB_W, ThumbList
from .viewer import FIT_PAGE, FIT_WIDTH, TOOL_HAND, TOOL_SELECT, PageView
from .widgets import ThemeSwitch, apply_theme, is_dark

OPEN_FILTER = ("TIFF dosyaları (*.tif *.tiff);;"
               "Tüm görüntüler (*.tif *.tiff *.png *.jpg *.jpeg *.bmp *.gif);;Tüm dosyalar (*)")
BLANK_INK_RATIO = 0.003


def glyph_icon(text: str, color: QColor | None = None) -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    f = QFont()
    f.setPixelSize(50 if len(text) == 1 else 22)
    f.setBold(len(text) > 1)
    p.setFont(f)
    p.setPen(color or QApplication.palette().windowText().color())
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return QIcon(pm)


def app_icon() -> QIcon:
    pm = QPixmap(256, 256)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(255, 255, 255))
    p.setPen(QColor(60, 60, 70))
    p.drawRoundedRect(QRect(40, 16, 176, 224), 14, 14)
    p.setBrush(QColor(170, 30, 40))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRect(24, 120, 208, 80), 12, 12)
    f = QFont()
    f.setPixelSize(64)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor(255, 255, 255))
    p.drawText(QRect(24, 120, 208, 80), Qt.AlignmentFlag.AlignCenter, "TIF")
    p.setPen(QColor(150, 150, 160))
    for y in (48, 70, 92, 218):
        p.drawLine(70, y, 186, y)
    p.end()
    return QIcon(pm)


def natural_key(path: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", os.path.basename(path))]


def human_size(n: int) -> str:
    return f"{n / 1024 / 1024:.2f} MB" if n >= 1024 * 1024 else f"{n / 1024:.0f} KB"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowIcon(app_icon())
        self.settings = QSettings(APP_ORG, "TiffGoruntuleyici")
        self.theme_mode = self.settings.value("view/theme", "system")
        apply_theme(self.theme_mode)
        self._settings_dialog: SettingsDialog | None = None
        self.doc = Document()
        self.enh = Enhancement()
        self.night = False
        self.current = -1
        self._pending_scroll = "top"
        self._tasks: set[BackgroundTask] = set()
        self._enh_dialog: EnhanceDialog | None = None
        self._ocr_active = False
        self._matches: list[tuple[int, list[QRectF]]] = []
        self._match_idx = -1

        self.renderer = RenderService()
        self.renderer.ready.connect(self._on_render_ready)
        self.renderer.failed.connect(self._on_render_failed)
        self.thumb_provider = ThumbnailProvider(THUMB_W * 2, THUMB_H * 2)
        self.thumb_provider.ready.connect(self._on_thumb_ready)
        self.ocr_engine = OcrEngine(enabled=self.settings.value("ocr/enabled", "true") == "true")
        self.ocr = OcrManager(self.ocr_engine)
        self.ocr.pageDone.connect(self._on_ocr_page)

        self._build_ui()
        self._build_actions()
        self._build_menus_and_toolbar()
        self._restore_settings()
        self._update_ui_state()
        self.setAcceptDrops(True)
        QApplication.instance().installEventFilter(self)
        QTimer.singleShot(4000, self._maybe_check_updates)

    # ================================================================== arayüz kurulumu
    def _build_ui(self) -> None:
        self.view = PageView()
        self.view.nextPageRequested.connect(lambda: self.goto(self.current + 1, "top"))
        self.view.prevPageRequested.connect(lambda: self.goto(self.current - 1, "bottom"))
        self.view.zoomChanged.connect(self._on_zoom_changed)
        self.view.selectionFinished.connect(self._on_selection)

        self.search_bar = QWidget()
        sb = QHBoxLayout(self.search_bar)
        sb.setContentsMargins(6, 4, 6, 4)
        self.search_edit = QLineEdit(placeholderText="Belgede ara (OCR metni)…", clearButtonEnabled=True)
        self.search_edit.returnPressed.connect(self.search_next)
        self.search_edit.textChanged.connect(lambda _: self._search_timer.start())
        self.search_fold = QCheckBox("Türkçe harf duyarsız")
        self.search_fold.setToolTip("ç/c, ğ/g, ı/i, ö/o, ş/s, ü/u eşdeğer sayılır (OCR hatalarına karşı).")
        self.search_fold.setChecked(True)
        self.search_fold.toggled.connect(lambda _: self._run_search())
        self.search_info = QLabel()
        prev_b = QToolButton(text="▲", toolTip="Önceki eşleşme (Shift+F3)")
        next_b = QToolButton(text="▼", toolTip="Sonraki eşleşme (F3)")
        close_b = QToolButton(text="✕", toolTip="Aramayı kapat (Esc)")
        prev_b.clicked.connect(self.search_prev)
        next_b.clicked.connect(self.search_next)
        close_b.clicked.connect(self.close_search)
        for w in (self.search_edit, prev_b, next_b, self.search_fold, self.search_info, close_b):
            sb.addWidget(w, 1 if w is self.search_edit else 0)
        self.search_bar.hide()
        self._search_timer = QTimer(self, singleShot=True, interval=300)
        self._search_timer.timeout.connect(self._run_search)

        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.search_bar)
        cl.addWidget(self.view, 1)
        self.setCentralWidget(central)

        self.thumbs = ThumbList()
        self.thumbs.pageActivated.connect(lambda row: self.goto(row))
        self.thumbs.aboutToReorder.connect(self.doc_snapshot_for_reorder)
        self.thumbs.orderChanged.connect(self._on_reordered)
        self.thumbs.visibleRowsChanged.connect(self._request_visible_thumbs)
        self.thumbs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumbs.customContextMenuRequested.connect(self._thumb_menu)
        self.thumb_dock = QDockWidget("Sayfalar", self)
        self.thumb_dock.setObjectName("thumbs")
        self.thumb_dock.setWidget(self.thumbs)
        self.thumb_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable |
                                    QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.thumb_dock)

        self.lbl_page = QLabel()
        self.lbl_info = QLabel()
        self.lbl_ocr = QLabel()
        self.lbl_ocr.setToolTip(self.ocr_engine.status_text())
        self.lbl_zoom = QLabel()
        for w in (self.lbl_info, self.lbl_ocr, self.lbl_zoom):
            self.statusBar().addPermanentWidget(w)
        self.statusBar().addWidget(self.lbl_page)

    def _act(self, text: str, slot, shortcut=None, icon: str | QIcon | None = None,
             checkable: bool = False, tip: str | None = None) -> QAction:
        a = QAction(text, self)
        if isinstance(icon, str):
            a.setProperty("glyph", icon)
            icon = glyph_icon(icon)
        if icon is not None:
            a.setIcon(icon)
        if shortcut is not None:
            seqs = shortcut if isinstance(shortcut, list) else [shortcut]
            a.setShortcuts([QKeySequence(s) for s in seqs])
        a.setCheckable(checkable)
        tip = tip or text.replace("&", "").rstrip("…")
        if a.shortcut().toString():
            tip += f" ({a.shortcut().toString(QKeySequence.SequenceFormat.NativeText)})"
        a.setToolTip(tip)
        if checkable:
            a.toggled.connect(slot)
        else:
            a.triggered.connect(lambda _=False: slot())
        self.addAction(a)
        return a

    def _build_actions(self) -> None:
        st = self.style()
        A = self._act
        self.a_open = A("&Aç…", self.open_dialog, QKeySequence.StandardKey.Open,
                        st.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        self.a_append = A("Dosya &ekle (birleştir)…", self.append_dialog, "Ctrl+Shift+O", "⊞",
                          tip="Başka TIF dosyalarını bu belgenin sonuna ekle")
        self.a_save_tiff = A("TIFF olarak &kaydet…", lambda: self.export("tiff"), QKeySequence.StandardKey.Save,
                             st.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.a_export_pdf = A("&PDF olarak dışa aktar…", lambda: self.export("pdf"), "Ctrl+Shift+S", "PDF")
        self.a_export_sel = A("Seçili sayfaları &dışa aktar…", lambda: self.export("pdf", True), "Ctrl+E")
        self.a_print = A("&Yazdır…", self.print_document, QKeySequence.StandardKey.Print, "⎙")
        self.a_close_doc = A("Belgeyi &kapat", self.close_document, QKeySequence.StandardKey.Close)
        self.a_quit = A("Çı&kış", self.close, QKeySequence.StandardKey.Quit)

        self.a_undo = A("&Geri al", self.undo, QKeySequence.StandardKey.Undo, "↶")
        self.a_copy_img = A("Seçimi &resim olarak kopyala", self.copy_selection_image, QKeySequence.StandardKey.Copy)
        self.a_copy_text = A("Seçimi &metin olarak kopyala (OCR)", self.copy_selection_text, "Ctrl+Shift+C")
        self.a_save_region = A("Seçimi PNG olarak kaydet…", self.save_selection_png)
        self.a_delete = A("Sayfaları &sil", self.delete_pages, QKeySequence.StandardKey.Delete, "🗑",
                          tip="Seçili sayfaları sil")
        self.a_blank = A("&Boş sayfaları bul…", self.find_blank_pages)
        self.a_select_all = A("Tüm sayfaları seç", self.thumbs.selectAll, "Ctrl+Shift+A")

        self.a_first = A("İlk sayfa", lambda: self.goto(0), "Home", "⏮")
        self.a_prev = A("Önceki sayfa", lambda: self.goto(self.current - 1),
                        ["PgUp", "Left"], "◀")
        self.a_next = A("Sonraki sayfa", lambda: self.goto(self.current + 1),
                        ["PgDown", "Right"], "▶")
        self.a_last = A("Son sayfa", lambda: self.goto(len(self.doc.pages) - 1), "End", "⏭")
        self.a_goto = A("Sayfaya git…", self.goto_dialog, "Ctrl+G")

        self.a_zoom_in = A("Yakınlaştır", lambda: self.view.zoom_by(1.25),
                           [QKeySequence.StandardKey.ZoomIn, "+", "="], "⊕")
        self.a_zoom_out = A("Uzaklaştır", lambda: self.view.zoom_by(0.8),
                            [QKeySequence.StandardKey.ZoomOut, "-"], "⊖")
        self.a_fit_page = A("Sayfaya sığdır", lambda: self.view.apply_fit(FIT_PAGE), "Ctrl+0", "▣")
        self.a_fit_width = A("Genişliğe sığdır", lambda: self.view.apply_fit(FIT_WIDTH), "W", "↔")
        self.a_actual = A("Gerçek boyut (%100)", lambda: self._set_zoom_percent(100), "Ctrl+1")
        self.a_fullscreen = A("Tam ekran", self.toggle_fullscreen, "F11", checkable=True)
        self.a_night = A("Sayfa renklerini ters çevir", self.set_night, "I", "◐", checkable=True,
                         tip="Sayfayı siyah zemin üzerine beyaz yazı olarak göster")
        self.a_wheel_zoom = A("Tekerlek ile yakınlaştır (Ctrl'siz)", self._set_wheel_zoom, checkable=True)
        self.a_thumbs = self.thumb_dock.toggleViewAction()
        self.a_thumbs.setText("Sayfa paneli")
        self.a_thumbs.setShortcut(QKeySequence("F4"))

        self.a_rot_r = A("Sağa döndür (90°)", lambda: self.rotate(90), "R", "↻",
                         tip="Geçerli/seçili sayfaları sağa döndür")
        self.a_rot_l = A("Sola döndür (90°)", lambda: self.rotate(-90), "Shift+R", "↺",
                         tip="Geçerli/seçili sayfaları sola döndür")
        self.a_rot_180 = A("Ters çevir (180°)", lambda: self.rotate(180), "T")
        self.a_rot_all_r = A("Tüm belgeyi sağa döndür", lambda: self.rotate(90, True), "Ctrl+Shift+R")
        self.a_rot_all_l = A("Tüm belgeyi sola döndür", lambda: self.rotate(-90, True))
        self.a_rot_all_180 = A("Tüm belgeyi ters çevir (180°)", lambda: self.rotate(180, True), "Ctrl+Shift+T")
        self.a_auto_orient = A("Sayfa yönlerini otomatik düzelt (OCR)…", self.auto_orient)

        self.tool_group = QActionGroup(self)
        self.a_hand = A("El aracı (kaydır)", lambda on: on and self.view.set_tool(TOOL_HAND), "H", "✋", True)
        self.a_select = A("Seçim aracı (alan kopyala)", lambda on: on and self.view.set_tool(TOOL_SELECT),
                          "S", "⬚", True)
        self.tool_group.addAction(self.a_hand)
        self.tool_group.addAction(self.a_select)
        self.a_hand.setChecked(True)
        self.a_magnifier = A("Büyüteç", self.view.set_magnifier, "M", "🔍", True,
                             tip="İmleç takipli büyüteç (Shift+tekerlek: oran)")
        self.a_enhance = A("Görüntü iyileştirme…", self.show_enhance, "Ctrl+B", "☀")
        self.a_find = A("Belgede ara…", self.open_search, QKeySequence.StandardKey.Find, "🔎")
        self.a_find_next = A("Sonraki eşleşme", self.search_next, "F3")
        self.a_find_prev = A("Önceki eşleşme", self.search_prev, "Shift+F3")
        self.a_ocr = A("Arka planda OCR", self.set_ocr_active, None, "OCR", True,
                       tip="Tüm sayfaları arka planda metne çevir (arama için)")
        self.a_auto_ocr = A("Belge açılınca OCR'ı otomatik başlat", self._set_auto_ocr, checkable=True)

        self.a_shortcuts = A("Klavye kısayolları", lambda: ShortcutsDialog(self).exec(), "F1")
        self.a_about = A("Hakkında", self.about)
        self.a_updates = A("Güncellemeleri denetle…", lambda: self.check_updates(manual=True))
        self.a_about.setMenuRole(QAction.MenuRole.AboutRole)
        self.a_settings = A("Ayarlar…", self.show_settings, "Ctrl+,", "⚙")
        self.a_settings.setMenuRole(QAction.MenuRole.PreferencesRole)
        self.a_reg = A("Windows'a .tif/.tiff ilişkilendirmesini ekle", self.register_windows)
        self.a_unreg = A("Windows ilişkilendirmesini kaldır", self.unregister_windows)
        self.a_defapps = A("Varsayılan uygulamalar ayarlarını aç", plat.open_default_apps_settings)

        esc = QAction(self)
        esc.setShortcut(QKeySequence("Esc"))
        esc.triggered.connect(self._on_escape)
        self.addAction(esc)

    def _build_menus_and_toolbar(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu("&Dosya")
        m.addActions([self.a_open, self.a_append])
        self.recent_menu = m.addMenu("Son açılanlar")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        m.addSeparator()
        m.addActions([self.a_save_tiff, self.a_export_pdf, self.a_export_sel])
        m.addSeparator()
        m.addActions([self.a_print, self.a_close_doc])
        m.addSeparator()
        m.addAction(self.a_quit)

        m = mb.addMenu("Dü&zen")
        m.addActions([self.a_undo])
        m.addSeparator()
        m.addActions([self.a_copy_img, self.a_copy_text, self.a_save_region])
        m.addSeparator()
        m.addActions([self.a_select_all, self.a_delete, self.a_blank])

        m = mb.addMenu("&Görünüm")
        m.addActions([self.a_zoom_in, self.a_zoom_out, self.a_actual, self.a_fit_page, self.a_fit_width])
        m.addSeparator()
        m.addActions([self.a_first, self.a_prev, self.a_next, self.a_last, self.a_goto])
        m.addSeparator()
        m.addActions([self.a_night, self.a_fullscreen, self.a_thumbs, self.a_wheel_zoom])

        m = mb.addMenu("&Sayfa")
        m.addActions([self.a_rot_r, self.a_rot_l, self.a_rot_180])
        m.addSeparator()
        m.addActions([self.a_rot_all_r, self.a_rot_all_l, self.a_rot_all_180])
        m.addSeparator()
        m.addAction(self.a_auto_orient)

        m = mb.addMenu("&Araçlar")
        m.addActions([self.a_hand, self.a_select, self.a_magnifier])
        m.addSeparator()
        m.addActions([self.a_enhance, self.a_find, self.a_find_next, self.a_find_prev])
        m.addSeparator()
        m.addAction(self.a_ocr)
        m.addSeparator()
        m.addAction(self.a_settings)
        if plat.IS_WINDOWS:
            m.addSeparator()
            w = m.addMenu("Windows entegrasyonu")
            w.addActions([self.a_reg, self.a_unreg, self.a_defapps])

        m = mb.addMenu("&Yardım")
        m.addActions([self.a_shortcuts, self.a_updates, self.a_about])

        tb = QToolBar("Araç çubuğu")
        tb.setObjectName("main_toolbar")
        tb.setIconSize(tb.iconSize() * 0.9)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(tb)
        tb.addActions([self.a_open, self.a_save_tiff, self.a_export_pdf, self.a_print])
        tb.addSeparator()
        tb.addActions([self.a_first, self.a_prev])
        self.page_spin = QSpinBox(minimum=1, maximum=1, keyboardTracking=False)
        self.page_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.page_spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.page_spin.setMinimumWidth(52)
        self.page_spin.valueChanged.connect(lambda v: self.goto(v - 1))
        self.page_total = QLabel(" / 0 ")
        tb.addWidget(self.page_spin)
        tb.addWidget(self.page_total)
        tb.addActions([self.a_next, self.a_last])
        tb.addSeparator()
        tb.addAction(self.a_zoom_out)
        self.zoom_combo = QComboBox(editable=True)
        self.zoom_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.zoom_combo.addItems(["Sayfaya sığdır", "Genişliğe sığdır", "%25", "%50", "%75", "%100",
                                  "%150", "%200", "%300", "%400"])
        self.zoom_combo.setMinimumWidth(130)
        self.zoom_combo.activated.connect(self._on_zoom_combo)
        self.zoom_combo.lineEdit().returnPressed.connect(self._on_zoom_combo)
        tb.addWidget(self.zoom_combo)
        tb.addActions([self.a_zoom_in, self.a_fit_page, self.a_fit_width])
        tb.addSeparator()
        tb.addActions([self.a_rot_l, self.a_rot_r, self.a_delete, self.a_undo])
        tb.addSeparator()
        tb.addActions([self.a_hand, self.a_select, self.a_magnifier, self.a_enhance, self.a_night])
        tb.addSeparator()
        tb.addActions([self.a_find, self.a_ocr])
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        tb.addAction(self.a_settings)
        self.theme_switch = ThemeSwitch()
        self.theme_switch.setChecked(is_dark())
        self.theme_switch.toggled.connect(lambda dark: self.set_theme("dark" if dark else "light"))
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(6, 0, 8, 0)
        hl.addWidget(self.theme_switch)
        tb.addWidget(holder)

    # ================================================================== ayarlar
    def _restore_settings(self) -> None:
        geo = self.settings.value("window/geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        else:
            self.resize(1280, 900)
        state = self.settings.value("window/state")
        if state is not None:
            self.restoreState(state)
        self.a_wheel_zoom.setChecked(self.settings.value("view/wheel_zoom", "false") == "true")
        self.a_auto_ocr.setChecked(self.settings.value("ocr/auto", "true") == "true")
        self.a_night.setChecked(self.settings.value("view/night", "false") == "true")

    def _set_wheel_zoom(self, on: bool) -> None:
        self.view.wheel_zooms = on
        self.settings.setValue("view/wheel_zoom", "true" if on else "false")

    def _set_auto_ocr(self, on: bool) -> None:
        self.settings.setValue("ocr/auto", "true" if on else "false")

    def _recent(self) -> list[str]:
        v = self.settings.value("recent", [])
        return [v] if isinstance(v, str) else list(v or [])

    def _add_recent(self, path: str) -> None:
        items = [p for p in self._recent() if os.path.normcase(p) != os.path.normcase(path)]
        self.settings.setValue("recent", [path] + items[:9])

    def _fill_recent(self) -> None:
        self.recent_menu.clear()
        items = [p for p in self._recent() if os.path.exists(p)]
        if not items:
            self.recent_menu.addAction("(boş)").setEnabled(False)
        for p in items:
            self.recent_menu.addAction(p, lambda p=p: self.open_files([p]))

    # ================================================================== dosya açma
    def _start_dir(self) -> str:
        return self.settings.value("last_dir", os.path.expanduser("~"))

    def open_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "TIFF aç", self._start_dir(), OPEN_FILTER)
        if paths:
            self.open_files(sorted(paths, key=natural_key))

    def append_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Belgeye eklenecek dosyalar", self._start_dir(), OPEN_FILTER)
        if paths:
            self.open_files(sorted(paths, key=natural_key), append=True)

    def open_files(self, paths: list[str], append: bool = False) -> None:
        paths = [p for p in paths if os.path.isfile(p)]
        if not paths:
            return
        if not append or not self.doc.pages:
            if not self._confirm_discard():
                return
            self._reset_document()
        else:
            self.doc.snapshot()
        first_new = len(self.doc.pages)
        errors = []
        for p in paths:
            try:
                self.doc.add_file(p)
                self._add_recent(os.path.abspath(p))
            except Exception as e:
                errors.append(f"{os.path.basename(p)}: {e}")
        self.settings.setValue("last_dir", os.path.dirname(os.path.abspath(paths[0])))
        if errors:
            QMessageBox.warning(self, "Açılamayan dosyalar", "\n".join(errors))
        if not self.doc.pages:
            self._update_ui_state()
            return
        target = first_new if append and first_new < len(self.doc.pages) else max(0, self.current)
        self.thumbs.set_pages(self.doc.pages, target)
        self.current = -1
        self.goto(target)
        if self._ocr_active or (self.a_auto_ocr.isChecked() and self.ocr_engine.available):
            self.a_ocr.setChecked(True)
            self.ocr.schedule(self.doc.pages)
        self._update_ui_state()
        if append:
            self.statusBar().showMessage(f"{len(self.doc.pages) - first_new} sayfa eklendi", 4000)

    def _reset_document(self) -> None:
        self.ocr.cancel()
        self.doc = Document()
        self.current = -1
        self.renderer.clear()
        self.thumbs.forget_all()
        self.thumbs.set_pages([])
        self.view.clear_image()
        self._matches = []
        self._match_idx = -1

    def close_document(self) -> None:
        if self._confirm_discard():
            self._reset_document()
            self._update_ui_state()

    def _confirm_discard(self) -> bool:
        if not self.doc.modified or not self.doc.pages:
            return True
        r = QMessageBox.question(
            self, APP_NAME, "Belgede kaydedilmemiş değişiklikler (döndürme, silme, sıralama) var.\n"
                            "Kaydetmeden devam edilsin mi?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Save:
            self.export("tiff")
            return not self.doc.modified
        return r == QMessageBox.StandardButton.Discard

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls() and any(u.isLocalFile() for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        paths = sorted((u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()), key=natural_key)
        if not paths:
            return
        append = False
        if self.doc.pages:
            box = QMessageBox(QMessageBox.Icon.Question, APP_NAME, f"{len(paths)} dosya bırakıldı.", parent=self)
            b_new = box.addButton("Yeni belge olarak aç", QMessageBox.ButtonRole.AcceptRole)
            b_add = box.addButton("Mevcut belgeye ekle", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("İptal", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() not in (b_new, b_add):
                return
            append = box.clickedButton() is b_add
        e.acceptProposedAction()
        QTimer.singleShot(0, lambda: self.open_files(paths, append))

    # ================================================================== sayfa gösterimi
    @property
    def page(self) -> Page | None:
        return self.doc.pages[self.current] if 0 <= self.current < len(self.doc.pages) else None

    def goto(self, index: int, scroll: str = "top") -> None:
        n = len(self.doc.pages)
        if n == 0:
            return
        index = max(0, min(n - 1, index))
        if index == self.current and self.view.image is not None:
            return
        self.current = index
        self._show_current(scroll)

    def _show_current(self, scroll: str = "top", keep_view: bool = False) -> None:
        page = self.page
        if page is None:
            return
        self.thumbs.set_current(self.current)
        r = self.renderer.get(page, self.enh)
        if r is not None:
            self.view.set_image(r.display(self.night), scroll, keep_view)
            self._update_highlights()
        else:
            self._pending_scroll = "keep" if keep_view else scroll
            self.view.set_overlay("Sayfa yükleniyor…")
            self.renderer.request(page, self.enh, priority=10)
        for j in (self.current + 1, self.current - 1, self.current + 2):
            if 0 <= j < len(self.doc.pages):
                self.renderer.request(self.doc.pages[j], self.enh)
        self.ocr.prioritize(page)
        self._update_page_labels()

    def _on_render_ready(self, key) -> None:
        page = self.page
        if page is None or key != self.renderer.key(page, self.enh):
            return
        r = self.renderer.get(page, self.enh)
        if r is None:
            return
        keep = self._pending_scroll == "keep"
        self.view.set_image(r.display(self.night), "top" if keep else self._pending_scroll, keep)
        self._update_highlights()
        self._update_page_labels()

    def _on_render_failed(self, key, msg: str) -> None:
        page = self.page
        if page is not None and key == self.renderer.key(page, self.enh):
            self.view.set_overlay(f"Sayfa açılamadı:\n{msg}")
            self.statusBar().showMessage(f"Hata: {msg}", 8000)

    def _update_page_labels(self) -> None:
        n = len(self.doc.pages)
        self.page_spin.blockSignals(True)
        self.page_spin.setMaximum(max(1, n))
        self.page_spin.setValue(self.current + 1 if n else 1)
        self.page_spin.blockSignals(False)
        self.page_total.setText(f" / {n} ")
        page = self.page
        if page is None:
            self.lbl_page.setText("")
            self.lbl_info.setText("")
            return
        self.lbl_page.setText(f"Sayfa {self.current + 1}/{n} · {page.label}"
                              + (f" · {page.rotation}°" if page.rotation else ""))
        r = self.renderer.get(page, self.enh)
        if r is not None:
            kind = {"1": "S/B", "L": "Gri", "RGB": "Renkli"}.get(r.image.mode, r.image.mode)
            self.lbl_info.setText(f"{r.image.width}×{r.image.height} px · {r.dpi:.0f} dpi · {kind}")

    def _update_ui_state(self) -> None:
        has = bool(self.doc.pages)
        for a in (self.a_append, self.a_save_tiff, self.a_export_pdf, self.a_export_sel, self.a_print,
                  self.a_close_doc, self.a_delete, self.a_blank, self.a_first, self.a_prev, self.a_next,
                  self.a_last, self.a_goto, self.a_rot_r, self.a_rot_l, self.a_rot_180, self.a_rot_all_r,
                  self.a_rot_all_l, self.a_rot_all_180, self.a_find, self.a_select_all,
                  self.a_copy_img, self.a_copy_text, self.a_save_region):
            a.setEnabled(has)
        self.a_append.setEnabled(True)
        self.a_undo.setEnabled(self.doc.can_undo())
        self.a_auto_orient.setEnabled(has and self.ocr_engine.available and self.ocr_engine.has_osd)
        title = APP_NAME
        if has:
            title = f"{self.doc.title}{' *' if self.doc.modified else ''} — {APP_NAME}"
        self.setWindowTitle(title)
        self._update_page_labels()
        self._update_ocr_label()

    # ================================================================== küçük resimler
    def _request_visible_thumbs(self) -> None:
        for row in self.thumbs.visible_rows():
            if row >= len(self.doc.pages):
                break
            page = self.doc.pages[row]
            if not self.thumbs.has_thumbnail(page.uid):
                self.thumb_provider.request(page)

    def _on_thumb_ready(self, uid: int, img) -> None:
        self.thumbs.set_base_thumbnail(uid, img, self.doc.pages)

    def _thumb_menu(self, pos: QPoint) -> None:
        if not self.doc.pages:
            return
        m = QMenu(self)
        m.addActions([self.a_rot_r, self.a_rot_l, self.a_rot_180])
        m.addSeparator()
        m.addActions([self.a_export_sel, self.a_delete])
        m.exec(self.thumbs.viewport().mapToGlobal(pos))

    # ================================================================== sayfa işlemleri
    def _target_rows(self) -> list[int]:
        rows = self.thumbs.selected_rows()
        if len(rows) > 1 or (rows and self.thumbs.hasFocus()):
            return rows
        return [self.current] if self.current >= 0 else []

    def rotate(self, degrees: int, whole: bool = False) -> None:
        rows = list(range(len(self.doc.pages))) if whole else self._target_rows()
        if not rows:
            return
        self.doc.rotate(rows, degrees)
        self._after_pages_changed(rotated=[self.doc.pages[i] for i in rows])

    def delete_pages(self) -> None:
        rows = self._target_rows()
        if not rows:
            return
        if len(rows) == len(self.doc.pages):
            if QMessageBox.question(self, APP_NAME, "Tüm sayfalar silinsin mi?") != QMessageBox.StandardButton.Yes:
                return
        keep_uid = None
        for i in range(self.current, len(self.doc.pages)):
            if i not in rows:
                keep_uid = self.doc.pages[i].uid
                break
        if keep_uid is None:
            for i in range(self.current, -1, -1):
                if i not in rows:
                    keep_uid = self.doc.pages[i].uid
                    break
        self.doc.delete(rows)
        self._after_structure_change(keep_uid)
        self.statusBar().showMessage(f"{len(rows)} sayfa silindi — geri almak için Ctrl+Z", 5000)

    def undo(self) -> None:
        uid = self.page.uid if self.page else None
        if self.doc.undo():
            self._after_structure_change(uid)
            self._schedule_ocr_if_active(self.doc.pages)

    def doc_snapshot_for_reorder(self) -> None:
        self.doc.snapshot()

    def _on_reordered(self, uids: list[int]) -> None:
        uid = self.page.uid if self.page else None
        self.doc.reorder(uids)
        self._after_structure_change(uid)

    def _after_structure_change(self, keep_uid: int | None) -> None:
        self.thumbs.set_pages(self.doc.pages)
        idx = self.doc.index_of(keep_uid) if keep_uid is not None else -1
        if not self.doc.pages:
            self.current = -1
            self.view.clear_image()
        else:
            if idx < 0:
                idx = min(max(self.current, 0), len(self.doc.pages) - 1)
            self.current = idx
            self._show_current("keep" if self.view.image is not None else "top", keep_view=True)
        self._run_search()
        self._update_ui_state()

    def _after_pages_changed(self, rotated: list[Page]) -> None:
        for i, page in enumerate(self.doc.pages):
            if page in rotated:
                self.thumbs.refresh_page(i, page)
        self.thumbs.viewport().update()
        if self.page in rotated:
            self._show_current("top")
        self._schedule_ocr_if_active(rotated)
        self._run_search()
        self._update_ui_state()

    def goto_dialog(self) -> None:
        n = len(self.doc.pages)
        v, ok = QInputDialog.getInt(self, "Sayfaya git", f"Sayfa (1–{n}):", self.current + 1, 1, n)
        if ok:
            self.goto(v - 1)

    def find_blank_pages(self) -> None:
        pages = list(self.doc.pages)

        def work(task: BackgroundTask):
            blanks = []
            for i, p in enumerate(pages):
                task.report(i, len(pages), f"{i + 1}/{len(pages)}. sayfa inceleniyor")
                img, _ = load_frame(p.source, p.frame)
                if ink_ratio(img) < BLANK_INK_RATIO:
                    blanks.append(p.uid)
            return blanks

        def done(uids: list[int]) -> None:
            rows = [self.doc.index_of(u) for u in uids]
            rows = [r for r in rows if r >= 0]
            if not rows:
                QMessageBox.information(self, "Boş sayfalar", "Boş sayfa bulunamadı.")
                return
            self.thumbs.select_rows(rows)
            listing = ", ".join(str(r + 1) for r in rows)
            if QMessageBox.question(self, "Boş sayfalar",
                                    f"{len(rows)} boş görünen sayfa bulundu ve seçildi:\n{listing}\n\n"
                                    "Bu sayfalar silinsin mi? (Ctrl+Z ile geri alınabilir)") \
                    == QMessageBox.StandardButton.Yes:
                keep = self.page.uid if self.page and self.current not in rows else None
                self.doc.delete(rows)
                self._after_structure_change(keep)

        self._run_task("Boş sayfalar aranıyor", work, done)

    def auto_orient(self) -> None:
        pages = list(self.doc.pages)
        rotations = {p.uid: p.rotation for p in pages}
        engine = self.ocr_engine

        def work(task: BackgroundTask):
            out = {}
            for i, p in enumerate(pages):
                task.report(i, len(pages), f"{i + 1}/{len(pages)}. sayfanın yönü tespit ediliyor")
                img, dpi = load_frame(p.source, p.frame)
                deg = engine.orientation(rotate_image(img, rotations[p.uid]), dpi)
                if deg:
                    out[p.uid] = deg
            return out

        def done(fixes: dict[int, int]) -> None:
            targets = [p for p in self.doc.pages if p.uid in fixes]
            if not targets:
                QMessageBox.information(self, "Yön düzeltme", "Düzeltilmesi gereken sayfa bulunamadı.")
                return
            self.doc.snapshot()
            for p in targets:
                p.rotation = (p.rotation + fixes[p.uid]) % 360
            self.doc.modified = True
            self._after_pages_changed(targets)
            QMessageBox.information(self, "Yön düzeltme",
                                    f"{len(targets)} sayfa döndürüldü. Hatalıysa Ctrl+Z ile geri alabilirsiniz.")

        self._run_task("Sayfa yönleri tespit ediliyor", work, done)

    # ================================================================== görünüm
    def _on_zoom_changed(self, z: float) -> None:
        txt = f"%{z * 100:.0f}"
        self.lbl_zoom.setText(txt)
        if not self.zoom_combo.lineEdit().hasFocus():
            mode = self.view.fit_mode
            self.zoom_combo.setEditText("Sayfaya sığdır" if mode == FIT_PAGE else
                                        "Genişliğe sığdır" if mode == FIT_WIDTH else txt)

    def _on_zoom_combo(self, *_):
        t = self.zoom_combo.currentText().strip()
        if t.startswith("Sayfa"):
            self.view.apply_fit(FIT_PAGE)
        elif t.startswith("Geniş"):
            self.view.apply_fit(FIT_WIDTH)
        else:
            m = re.search(r"\d+([.,]\d+)?", t)
            if m:
                self._set_zoom_percent(float(m.group(0).replace(",", ".")))
        self.view.setFocus()

    def _set_zoom_percent(self, pct: float) -> None:
        self.view.fit_mode = None
        self.view.set_zoom(pct / 100.0, self.view.viewport().rect().center())

    def toggle_fullscreen(self, on: bool) -> None:
        if on:
            self._was_maximized = self.isMaximized()
            self.showFullScreen()
        else:
            self.showMaximized() if getattr(self, "_was_maximized", False) else self.showNormal()

    def set_night(self, on: bool) -> None:
        self.night = on
        self.settings.setValue("view/night", "true" if on else "false")
        if self.page is not None:
            self._show_current(keep_view=True)

    def show_enhance(self) -> None:
        if self._enh_dialog is None:
            self._enh_dialog = EnhanceDialog(self, self.enh)
            self._enh_dialog.enhancementChanged.connect(self.set_enhancement)
        self._enh_dialog.show()
        self._enh_dialog.raise_()

    def set_enhancement(self, enh: Enhancement) -> None:
        if enh == self.enh:
            return
        self.enh = enh
        self.a_enhance.setText("Görüntü iyileştirme… (etkin)" if not enh.is_identity() else "Görüntü iyileştirme…")
        if self.page is not None:
            self._show_current(keep_view=True)

    def _on_escape(self) -> None:
        if self.search_bar.isVisible():
            self.close_search()
        elif self.isFullScreen():
            self.a_fullscreen.setChecked(False)
        elif self.view.selection is not None:
            self.view.clear_selection()
        elif self.a_magnifier.isChecked():
            self.a_magnifier.setChecked(False)

    def eventFilter(self, obj, ev) -> bool:
        t = ev.type()
        if t in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and ev.key() == Qt.Key.Key_Space \
                and self.isActiveWindow() and not ev.isAutoRepeat():
            fw = QApplication.focusWidget()
            if not isinstance(fw, (QLineEdit, QAbstractSpinBox, QComboBox)):
                self.view.set_space_pan(t == QEvent.Type.KeyPress)
                return True
        elif t == QEvent.Type.KeyPress and ev.key() == Qt.Key.Key_Space and ev.isAutoRepeat():
            fw = QApplication.focusWidget()
            if not isinstance(fw, (QLineEdit, QAbstractSpinBox, QComboBox)):
                return True
        elif t == QEvent.Type.WindowDeactivate and obj is self:
            self.view.set_space_pan(False)
        return super().eventFilter(obj, ev)

    # ================================================================== seçim / pano
    def _on_selection(self, rect: QRectF, gpos: QPoint) -> None:
        m = QMenu(self)
        m.addActions([self.a_copy_img, self.a_copy_text, self.a_save_region])
        m.popup(gpos + QPoint(8, 8))

    def _selection_crop(self):
        page, rect = self.page, self.view.selection
        if page is None or rect is None:
            return None
        r = self.renderer.get(page, self.enh)
        if r is None:
            return None
        box = (int(rect.left()), int(rect.top()), int(rect.right()), int(rect.bottom()))
        return r.image.crop(box), r.dpi

    def copy_selection_image(self) -> None:
        crop = self._selection_crop()
        if crop is None:
            self.statusBar().showMessage("Önce seçim aracıyla (S) bir alan seçin.", 4000)
            return
        QApplication.clipboard().setImage(pil_to_qimage(crop[0]))
        self.statusBar().showMessage(f"Seçili alan resim olarak panoya kopyalandı ({crop[0].width}×{crop[0].height})",
                                     4000)

    def copy_selection_text(self) -> None:
        crop = self._selection_crop()
        if crop is None:
            self.statusBar().showMessage("Önce seçim aracıyla (S) bir alan seçin.", 4000)
            return
        if not self.ocr_engine.available:
            self._ocr_missing()
            return
        img, dpi = crop
        engine = self.ocr_engine

        def done(text: str) -> None:
            if not text:
                self.statusBar().showMessage("Seçili alanda metin bulunamadı.", 4000)
                return
            QApplication.clipboard().setText(text)
            self.statusBar().showMessage(f"Metin panoya kopyalandı ({len(text)} karakter)", 4000)

        self._run_task("Metin tanınıyor", lambda task: engine.text(img, dpi), done)

    def save_selection_png(self) -> None:
        crop = self._selection_crop()
        if crop is None:
            self.statusBar().showMessage("Önce seçim aracıyla (S) bir alan seçin.", 4000)
            return
        base = os.path.splitext(os.path.basename(self.page.source))[0]
        path, _ = QFileDialog.getSaveFileName(self, "Alanı kaydet",
                                              os.path.join(self._start_dir(), f"{base}_s{self.current + 1}_alan.png"),
                                              "PNG (*.png)")
        if path:
            img, dpi = crop
            img.save(path, dpi=(dpi, dpi))

    # ================================================================== OCR ve arama
    def set_ocr_active(self, on: bool) -> None:
        if on and not self.ocr_engine.available:
            self.a_ocr.blockSignals(True)
            self.a_ocr.setChecked(False)
            self.a_ocr.blockSignals(False)
            self._ocr_missing()
            return
        self._ocr_active = on
        if on:
            self.ocr.schedule(self.doc.pages)
            if self.page:
                self.ocr.prioritize(self.page)
        else:
            self.ocr.cancel()
        self._update_ocr_label()

    def _schedule_ocr_if_active(self, pages: list[Page]) -> None:
        if self._ocr_active:
            self.ocr.schedule(pages)

    def _on_ocr_page(self, uid: int) -> None:
        self._update_ocr_label()
        if self.search_bar.isVisible() and self.search_edit.text().strip():
            self._search_timer.start(600)

    def _update_ocr_label(self) -> None:
        if not self.ocr_engine.available:
            self.lbl_ocr.setText("OCR: yok")
            return
        n = len(self.doc.pages)
        done = sum(1 for p in self.doc.pages if self.ocr.is_done(p))
        state = "" if done == n or not self._ocr_active else " …"
        self.lbl_ocr.setText(f"OCR: {done}/{n}{state}" if n else "OCR: hazır")

    def _ocr_missing(self) -> None:
        if sys.platform == "darwin":
            how = "Terminal'de:  brew install tesseract tesseract-lang"
        else:
            how = ("UB Mannheim Tesseract kurulum programını kurarken 'Turkish' dil paketini seçin\n"
                   "ya da taşınabilir sürümde programın yanındaki 'tesseract' klasörüne kopyalayın.")
        box = QMessageBox(QMessageBox.Icon.Information, "OCR kullanılamıyor",
                          f"{self.ocr_engine.status_text()}.\n\nOCR (metin arama/kopyalama, aranabilir PDF) için "
                          "Tesseract ve Türkçe dil modeli gerekir. Ayarlar'daki \"OCR'ı kullan\" anahtarını "
                          "açarsanız program bunları indirip kurar.\n\n"
                          f"Elle kurulum: {how}", parent=self)
        open_btn = box.addButton("Ayarları aç", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Kapat", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            self.show_settings()

    def open_search(self) -> None:
        self.search_bar.show()
        self.search_edit.setFocus()
        self.search_edit.selectAll()
        if not self.ocr_engine.available:
            self.search_info.setText("OCR yok — arama yapılamaz")
        elif not self._ocr_active:
            self.a_ocr.setChecked(True)

    def close_search(self) -> None:
        self.search_bar.hide()
        self._matches = []
        self._match_idx = -1
        self.view.set_highlights([])
        self.view.setFocus()

    def _run_search(self) -> None:
        if not self.search_bar.isVisible():
            return
        q = self.search_edit.text().strip()
        prev = self._matches[self._match_idx] if 0 <= self._match_idx < len(self._matches) else None
        self._matches = []
        if q:
            fold = self.search_fold.isChecked()
            for page in self.doc.pages:
                words = self.ocr.words_for(page)
                if words:
                    self._matches += [(page.uid, m) for m in find_matches(words, q, fold)]
        self._match_idx = -1
        if prev is not None:
            for i, (uid, rects) in enumerate(self._matches):
                if uid == prev[0] and rects[0] == prev[1][0]:
                    self._match_idx = i
                    break
        if self._match_idx < 0 and self._matches and q:
            cur_uid = self.page.uid if self.page else None
            order = {p.uid: i for i, p in enumerate(self.doc.pages)}
            here = order.get(cur_uid, 0)
            self._match_idx = next((i for i, (u, _) in enumerate(self._matches) if order[u] >= here), 0)
            self._goto_match()
        self._update_search_info()
        self._update_highlights()

    def _update_search_info(self) -> None:
        if not self.ocr_engine.available:
            self.search_info.setText("OCR yok — arama için Tesseract gerekir")
            return
        n = len(self.doc.pages)
        done = sum(1 for p in self.doc.pages if self.ocr.is_done(p))
        scanned = "" if done == n else f" · {done}/{n} sayfa tarandı"
        if not self.search_edit.text().strip():
            self.search_info.setText(scanned.strip(" ·"))
        elif self._matches:
            self.search_info.setText(f"{self._match_idx + 1}/{len(self._matches)} eşleşme{scanned}")
        else:
            self.search_info.setText(f"Bulunamadı{scanned}")

    def search_next(self) -> None:
        self._step_match(1)

    def search_prev(self) -> None:
        self._step_match(-1)

    def _step_match(self, d: int) -> None:
        if not self.search_bar.isVisible():
            self.open_search()
            return
        if not self._matches:
            self._run_search()
            return
        self._match_idx = (self._match_idx + d) % len(self._matches)
        self._goto_match()
        self._update_search_info()

    def _goto_match(self) -> None:
        uid, _ = self._matches[self._match_idx]
        idx = self.doc.index_of(uid)
        if idx != self.current:
            self.goto(idx)
        self._update_highlights()

    def _update_highlights(self) -> None:
        page = self.page
        if page is None or not self.search_bar.isVisible():
            self.view.set_highlights([])
            return
        rects, current = [], -1
        for i, (uid, mrects) in enumerate(self._matches):
            if uid == page.uid:
                if i == self._match_idx:
                    current = len(rects)
                rects += mrects
        self.view.set_highlights(rects, current)

    # ================================================================== dışa aktarma
    def export(self, fmt: str, prefer_selected: bool = False) -> None:
        if not self.doc.pages:
            return
        selected = self.thumbs.selected_rows()
        ocr_status = None
        if not self.ocr_engine.available:
            ocr_status = self.ocr_engine.status_text()
        dlg = ExportDialog(self, fmt, len(self.doc.pages), selected, self.current,
                           not self.enh.is_identity(), ocr_status, self.settings,
                           prefer_selected=prefer_selected and len(selected) > 0)
        if not dlg.exec() or dlg.options is None:
            return
        opts = dlg.options
        subset = len(opts.indices) != len(self.doc.pages)
        base = os.path.splitext(os.path.basename(self.doc.files[0]))[0]
        suffix = "_secili" if subset else ("_duzenlenmis" if fmt == "tiff" else "")
        ext = ".pdf" if fmt == "pdf" else ".tif"
        folder = self.settings.value("export_dir", os.path.dirname(self.doc.files[0]))
        path, _ = QFileDialog.getSaveFileName(
            self, "PDF olarak kaydet" if fmt == "pdf" else "TIFF olarak kaydet",
            os.path.join(folder, base + suffix + ext),
            "PDF (*.pdf)" if fmt == "pdf" else "TIFF (*.tif *.tiff)")
        if not path:
            return
        if not path.lower().endswith((".pdf",) if fmt == "pdf" else (".tif", ".tiff")):
            path += ext
        if any(os.path.normcase(os.path.abspath(path)) == os.path.normcase(f) for f in self.doc.files):
            QMessageBox.warning(self, APP_NAME, "Açık olan kaynak dosyanın üzerine yazılamaz.\n"
                                                "Lütfen farklı bir dosya adı seçin.")
            return
        self.settings.setValue("export_dir", os.path.dirname(path))

        pages = [dataclasses.replace(self.doc.pages[i]) for i in opts.indices]
        enh = self.enh if opts.apply_enhancement else None
        ocr = self.ocr_engine if opts.ocr else None
        if fmt == "tiff":
            profile = PROFILE_BY_KEY[opts.profile_key]
            fn = lambda task: export_tiff(path, pages, enh, profile, task.report)
        elif opts.profile_key == FIT_PROFILE:
            limit = int(opts.max_mb * 1024 * 1024)
            fn = lambda task: export_pdf_fit(path, pages, enh, limit, ocr, task.report)
        else:
            profile = PROFILE_BY_KEY[opts.profile_key]
            fn = lambda task: export_pdf(path, pages, enh, profile, ocr, task.report)

        def done(info: dict) -> None:
            if fmt == "tiff" and not subset:
                self.doc.modified = False
                self._update_ui_state()
            msg = (f"{info['pages']} sayfa kaydedildi.\n\n{info['path']}\n"
                   f"Boyut: {human_size(info['size'])} · Profil: {info['profile'].name}")
            if info.get("ocr_failed"):
                msg += f"\n\nUyarı: {info['ocr_failed']} sayfaya OCR metin katmanı eklenemedi."
            if info.get("fits") is False:
                msg += (f"\n\nUyarı: En küçük profil bile {human_size(info['limit'])} sınırının altına inemedi. "
                        "Belgeyi sayfa aralıklarıyla birden çok dosyaya bölmeyi düşünün.")
                QMessageBox.warning(self, "Dışa aktarıldı", msg)
            else:
                QMessageBox.information(self, "Dışa aktarıldı", msg)

        self._run_task("Dışa aktarılıyor", fn, done)

    def _run_task(self, title: str, fn, on_done, parent=None, on_fail=None) -> None:
        task = BackgroundTask(fn)
        parent = parent or self
        dlg = QProgressDialog(title + "…", "İptal", 0, 0, parent)
        dlg.setWindowTitle(APP_NAME)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(400)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.canceled.connect(task.cancel_event.set)

        def progress(d: int, t: int, m: str) -> None:
            dlg.setMaximum(t)
            dlg.setValue(d)
            if m:
                dlg.setLabelText(m)

        def cleanup() -> None:
            self._tasks.discard(task)
            dlg.canceled.disconnect()
            dlg.close()
            dlg.deleteLater()

        def finished(result) -> None:
            cleanup()
            on_done(result)

        def failed(msg: str) -> None:
            cleanup()
            if msg:
                QMessageBox.critical(parent, title, msg)
            else:
                self.statusBar().showMessage("İşlem iptal edildi.", 4000)
            if on_fail is not None:
                on_fail()

        task.progress.connect(progress)
        task.finished.connect(finished)
        task.failed.connect(failed)
        self._tasks.add(task)
        task.start()

    # ================================================================== yazdırma
    def print_document(self) -> None:
        n = len(self.doc.pages)
        if not n:
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dlg = QPrintDialog(printer, self)
        dlg.setMinMax(1, n)
        dlg.setOptions(QAbstractPrintDialog.PrintDialogOption.PrintPageRange |
                       QAbstractPrintDialog.PrintDialogOption.PrintCurrentPage |
                       QAbstractPrintDialog.PrintDialogOption.PrintSelection |
                       QAbstractPrintDialog.PrintDialogOption.PrintToFile)
        if not dlg.exec():
            return
        rng = printer.printRange()
        if rng == QPrinter.PrintRange.PageRange:
            rows = list(range(printer.fromPage() - 1, printer.toPage()))
        elif rng == QPrinter.PrintRange.CurrentPage:
            rows = [self.current]
        elif rng == QPrinter.PrintRange.Selection:
            rows = self.thumbs.selected_rows() or [self.current]
        else:
            rows = list(range(n))
        progress = QProgressDialog("Yazdırılıyor…", "İptal", 0, len(rows), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(300)
        painter = QPainter(printer)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        try:
            for k, row in enumerate(rows):
                progress.setValue(k)
                QApplication.processEvents()
                if progress.wasCanceled():
                    break
                if k:
                    printer.newPage()
                img = self.renderer.render_sync(self.doc.pages[row], self.enh).qimage
                area = painter.viewport()
                if (img.width() > img.height()) != (area.width() > area.height()):
                    img = img.transformed(QTransform().rotate(90))
                size = img.size().scaled(area.size(), Qt.AspectRatioMode.KeepAspectRatio)
                target = QRect(QPoint(0, 0), size)
                target.moveCenter(area.center())
                painter.drawImage(target, img)
        finally:
            painter.end()
            progress.close()

    # ================================================================== sistem
    def register_windows(self) -> None:
        try:
            plat.register_windows()
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"Kayıt yapılamadı: {e}")
            return
        r = QMessageBox.question(
            self, APP_NAME,
            ".tif/.tiff dosyaları için 'Birlikte aç' kaydı ve sağ tık menüsünde "
            f"'{plat.MENU_TEXT}' seçeneği eklendi.\n\n"
            "Windows, varsayılan uygulamanın programla değiştirilmesine izin vermez. "
            "Şimdi 'Varsayılan uygulamalar' ayarlarını açıp .tif ve .tiff için bu programı seçmek ister misiniz?")
        if r == QMessageBox.StandardButton.Yes:
            plat.open_default_apps_settings()

    def unregister_windows(self) -> None:
        try:
            plat.unregister_windows()
            QMessageBox.information(self, APP_NAME, "Windows ilişkilendirmesi kaldırıldı.")
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"Kaldırılamadı: {e}")

    def about(self) -> None:
        AboutDialog(self, app_icon(), self.ocr_engine.status_text()).exec()

    # ================================================================== tema ve ayarlar
    def show_settings(self) -> None:
        if self._settings_dialog is None:
            self._settings_dialog = SettingsDialog(self)
        self._settings_dialog.refresh()
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    def set_theme(self, mode: str) -> None:
        self.theme_mode = mode
        self.settings.setValue("view/theme", mode)
        apply_theme(mode)
        self._sync_theme_widgets()

    def _sync_theme_widgets(self) -> None:
        self.theme_switch.blockSignals(True)
        self.theme_switch.setChecked(is_dark())
        self.theme_switch.blockSignals(False)
        for a in self.actions():
            g = a.property("glyph")
            if g:
                a.setIcon(glyph_icon(g))
        if self._settings_dialog is not None and self._settings_dialog.isVisible():
            self._settings_dialog.refresh()

    def changeEvent(self, e) -> None:
        if e.type() in (QEvent.Type.ThemeChange, QEvent.Type.PaletteChange):
            QTimer.singleShot(0, self._sync_theme_widgets)
        super().changeEvent(e)

    # ================================================================== OCR kurulumu
    def reload_ocr_engine(self) -> None:
        enabled = self.settings.value("ocr/enabled", "true") == "true"
        self.ocr_engine = OcrEngine(enabled=enabled)
        self.ocr.engine = self.ocr_engine
        if not self.ocr_engine.available:
            self.ocr.cancel()
            self.a_ocr.blockSignals(True)
            self.a_ocr.setChecked(False)
            self.a_ocr.blockSignals(False)
            self._ocr_active = False
        elif self.a_auto_ocr.isChecked() and self.doc.pages:
            self.a_ocr.setChecked(True)
        self.lbl_ocr.setToolTip(self.ocr_engine.status_text())
        self._update_ui_state()
        if self.search_bar.isVisible():
            self._run_search()

    def set_ocr_enabled(self, on: bool, parent=None, done=None) -> None:
        """Ayarlardaki anahtar: açılınca gerekirse Tesseract indirilip kurulur."""
        parent = parent or self
        finish = done or (lambda: None)
        if not on:
            self.settings.setValue("ocr/enabled", "false")
            self.reload_ocr_engine()
            finish()
            return
        probe = OcrEngine(enabled=True)
        if probe.installed and probe.has_turkish:
            self.settings.setValue("ocr/enabled", "true")
            self.reload_ocr_engine()
            finish()
            return
        if not tess_install.supported():
            QMessageBox.information(parent, "OCR kurulumu", tess_install.unsupported_reason())
            finish()
            return
        if sys.platform == "darwin":
            text = ("Tesseract ve dil paketleri Homebrew ile kurulacak. Bu işlem internet bağlantısı gerektirir "
                    "ve birkaç dakika sürebilir. Devam edilsin mi?")
        else:
            text = (f"Tesseract OCR ve Türkçe dil modeli (~{tess_install.PORTABLE_MB} MB) GitHub'dan indirilip "
                    "yalnızca sizin kullanıcı hesabınıza kurulacak (yönetici izni gerekmez):\n"
                    f"{tess_install.user_install_dir()}\n\nDevam edilsin mi?")
        if QMessageBox.question(parent, "OCR kurulumu", text) != QMessageBox.StandardButton.Yes:
            finish()
            return

        def ok(exe: str) -> None:
            self.settings.setValue("ocr/enabled", "true")
            self.reload_ocr_engine()
            finish()
            if self.ocr_engine.available:
                QMessageBox.information(parent, "OCR kurulumu", f"OCR kullanıma hazır.\n{exe}")
            else:
                QMessageBox.warning(parent, "OCR kurulumu",
                                    f"Kurulum tamamlandı ancak OCR başlatılamadı: {self.ocr_engine.status_text()}")

        self._run_task("Tesseract kuruluyor", lambda task: tess_install.install(task.report), ok,
                       parent=parent, on_fail=finish)

    def uninstall_tesseract(self, parent=None, done=None) -> None:
        parent = parent or self
        if QMessageBox.question(parent, "Tesseract'ı kaldır",
                                "Programın kurduğu Tesseract OCR bilgisayardan kaldırılsın mı?") \
                != QMessageBox.StandardButton.Yes:
            return

        def ok(_) -> None:
            self.reload_ocr_engine()
            if done:
                done()

        self._run_task("Tesseract kaldırılıyor", lambda task: tess_install.uninstall_windows(), ok,
                       parent=parent, on_fail=done)

    # ================================================================== güncellemeler
    @property
    def auto_update_check(self) -> bool:
        return self.settings.value("updates/auto", "false") == "true"

    def set_auto_update_check(self, on: bool) -> None:
        self.settings.setValue("updates/auto", "true" if on else "false")
        if on:
            self.check_updates(manual=False)

    def _maybe_check_updates(self) -> None:
        today = datetime.date.today().isoformat()
        if self.auto_update_check and self.settings.value("updates/last_check", "") != today:
            self.check_updates(manual=False)

    def check_updates(self, manual: bool = True, parent=None) -> None:
        parent = parent or self

        def done(release) -> None:
            self.settings.setValue("updates/last_check", datetime.date.today().isoformat())
            if self._settings_dialog is not None and self._settings_dialog.isVisible():
                self._settings_dialog.refresh()
            if release is None:
                if manual:
                    QMessageBox.information(parent, "Güncellemeler",
                                            f"Programınız güncel (sürüm {__version__}).")
                return
            if not manual and self.settings.value("updates/skip", "") == release.version:
                return
            box = QMessageBox(QMessageBox.Icon.Information, "Yeni sürüm var",
                              f"{APP_NAME} {release.version} yayımlandı (kurulu sürüm: {__version__}).",
                              parent=parent)
            if release.notes:
                box.setDetailedText(release.notes)
            get = box.addButton("İndirme sayfasını aç", QMessageBox.ButtonRole.AcceptRole)
            skip = box.addButton("Bu sürümü atla", QMessageBox.ButtonRole.DestructiveRole) if not manual else None
            box.addButton("Daha sonra", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is get:
                QDesktopServices.openUrl(QUrl(release.url))
            elif skip is not None and box.clickedButton() is skip:
                self.settings.setValue("updates/skip", release.version)

        if manual:
            self._run_task("Güncellemeler denetleniyor", lambda task: updater.check_for_update(), done,
                           parent=parent)
            return
        task = BackgroundTask(lambda task: updater.check_for_update())
        task.finished.connect(lambda r: (self._tasks.discard(task), done(r)))
        task.failed.connect(lambda _msg: self._tasks.discard(task))   # sessiz denetimde hata gösterme
        self._tasks.add(task)
        task.start()

    def closeEvent(self, e) -> None:
        if not self._confirm_discard():
            e.ignore()
            return
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState())
        self.ocr.stop()
        e.accept()
