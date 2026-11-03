"""İletişim kutuları: dışa aktarma, görüntü iyileştirme, kısayollar."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QRadioButton, QSlider, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView)

from .export import PROFILES, parse_page_ranges
from .imaging import Enhancement

FIT_PROFILE = "__fit__"


@dataclass
class ExportOptions:
    indices: list[int]
    profile_key: str
    max_mb: float
    apply_enhancement: bool
    ocr: bool


class ExportDialog(QDialog):
    def __init__(self, parent, fmt: str, page_count: int, selected: list[int], current: int,
                 enhancement_active: bool, ocr_status: str | None, settings,
                 prefer_selected: bool = False):
        super().__init__(parent)
        self.fmt = fmt
        self._count = page_count
        self._selected = selected
        self._current = current
        self.setWindowTitle("PDF olarak dışa aktar" if fmt == "pdf" else "TIFF olarak kaydet")
        lay = QVBoxLayout(self)

        scope = QGroupBox("Sayfalar")
        sl = QVBoxLayout(scope)
        self.rb_all = QRadioButton(f"Tüm sayfalar ({page_count})")
        self.rb_sel = QRadioButton(f"Seçili sayfalar ({len(selected)})")
        self.rb_cur = QRadioButton(f"Yalnızca geçerli sayfa ({current + 1})")
        self.rb_range = QRadioButton("Aralık:")
        self.range_edit = QLineEdit(placeholderText="ör. 1-3, 7, 10-")
        self.range_edit.textEdited.connect(lambda _: self.rb_range.setChecked(True))
        self.rb_sel.setEnabled(len(selected) > 0)
        group = QButtonGroup(self)
        for rb in (self.rb_all, self.rb_sel, self.rb_cur, self.rb_range):
            group.addButton(rb)
        (self.rb_sel if prefer_selected and selected else self.rb_all).setChecked(True)
        sl.addWidget(self.rb_all)
        sl.addWidget(self.rb_sel)
        sl.addWidget(self.rb_cur)
        row = QHBoxLayout()
        row.addWidget(self.rb_range)
        row.addWidget(self.range_edit, 1)
        sl.addLayout(row)
        lay.addWidget(scope)

        comp = QGroupBox("Sıkıştırma")
        form = QFormLayout(comp)
        self.profile = QComboBox()
        for p in PROFILES:
            self.profile.addItem(p.name, p.key)
        if fmt == "pdf":
            self.profile.addItem("Hedef boyuta sığdır (otomatik)", FIT_PROFILE)
        self.profile_desc = QLabel(wordWrap=True)
        self.profile_desc.setStyleSheet("color: palette(mid);")
        self.max_mb = QDoubleSpinBox(suffix=" MB", decimals=1, minimum=0.5, maximum=500.0, singleStep=0.5)
        self.max_mb.setValue(float(settings.value("export/max_mb", 10.0)))
        self.max_mb.setToolTip("UYAP dosya yükleme sınırınıza göre ayarlayın.")
        form.addRow("Profil:", self.profile)
        form.addRow("", self.profile_desc)
        form.addRow("Azami boyut:", self.max_mb)
        lay.addWidget(comp)

        self.cb_enh = QCheckBox("Görüntü iyileştirmelerini uygula (kontrast, eşikleme…)")
        self.cb_enh.setEnabled(enhancement_active)
        self.cb_enh.setChecked(enhancement_active)
        lay.addWidget(self.cb_enh)
        self.cb_ocr = QCheckBox("Aranabilir PDF (OCR metin katmanı ekle)")
        if fmt == "pdf":
            self.cb_ocr.setEnabled(ocr_status is None)
            self.cb_ocr.setChecked(ocr_status is None and settings.value("export/ocr", "true") == "true")
            if ocr_status:
                self.cb_ocr.setToolTip(ocr_status)
                self.cb_ocr.setText(self.cb_ocr.text() + f" — {ocr_status}")
            lay.addWidget(self.cb_ocr)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Dışa aktar…" if fmt == "pdf" else "Kaydet…")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        key = settings.value(f"export/{fmt}_profile", "dengeli" if fmt == "pdf" else "orijinal")
        idx = self.profile.findData(key)
        self.profile.setCurrentIndex(max(0, idx))
        self.profile.currentIndexChanged.connect(self._update_desc)
        self._update_desc()
        self._settings = settings
        self.options: ExportOptions | None = None

    def _update_desc(self) -> None:
        key = self.profile.currentData()
        self.max_mb.setEnabled(key == FIT_PROFILE)
        if key == FIT_PROFILE:
            self.profile_desc.setText("Belirtilen boyutun altına inen en yüksek kaliteli profil seçilir.")
        else:
            self.profile_desc.setText(next(p.description for p in PROFILES if p.key == key))

    def _accept(self) -> None:
        if self.rb_all.isChecked():
            indices = list(range(self._count))
        elif self.rb_sel.isChecked():
            indices = list(self._selected)
        elif self.rb_cur.isChecked():
            indices = [self._current]
        else:
            try:
                indices = parse_page_ranges(self.range_edit.text(), self._count)
            except ValueError as e:
                self.range_edit.setFocus()
                self.range_edit.setToolTip(str(e))
                self.range_edit.setStyleSheet("border: 1px solid red;")
                return
        if not indices:
            return
        key = self.profile.currentData()
        self._settings.setValue(f"export/{self.fmt}_profile", key)
        self._settings.setValue("export/max_mb", self.max_mb.value())
        if self.fmt == "pdf" and self.cb_ocr.isEnabled():
            self._settings.setValue("export/ocr", "true" if self.cb_ocr.isChecked() else "false")
        self.options = ExportOptions(indices, key, self.max_mb.value(),
                                     self.cb_enh.isChecked() and self.cb_enh.isEnabled(),
                                     self.fmt == "pdf" and self.cb_ocr.isChecked() and self.cb_ocr.isEnabled())
        self.accept()


class _SliderRow(QWidget):
    changed = Signal()

    def __init__(self, lo: int, hi: int, value: int = 0):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Orientation.Horizontal, minimum=lo, maximum=hi, value=value)
        self.label = QLabel(str(value), minimumWidth=32, alignment=Qt.AlignmentFlag.AlignRight)
        self.slider.valueChanged.connect(lambda v: (self.label.setText(str(v)), self.changed.emit()))
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.label)

    def value(self) -> int:
        return self.slider.value()

    def set_value(self, v: int) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(v)
        self.label.setText(str(v))
        self.slider.blockSignals(False)


class EnhanceDialog(QDialog):
    """Kontrast/eşikleme ayarları; değişiklikler anında önizlenir."""
    enhancementChanged = Signal(object)

    PRESETS = {
        "Soluk mürekkep": Enhancement(contrast=25, darken=45),
        "Karbon kopya": Enhancement(contrast=20, darken=30, threshold=-1, despeckle=True),
        "Koyu / lekeli tarama": Enhancement(brightness=25, contrast=30, despeckle=True),
    }

    def __init__(self, parent, enh: Enhancement):
        super().__init__(parent)
        self.setWindowTitle("Görüntü iyileştirme")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.brightness = _SliderRow(-100, 100)
        self.contrast = _SliderRow(-100, 100)
        self.darken = _SliderRow(-100, 100)
        self.th_mode = QComboBox()
        self.th_mode.addItems(["Kapalı", "Otomatik (Otsu)", "Elle"])
        self.threshold = _SliderRow(1, 254, 128)
        self.despeckle = QCheckBox("Gürültü / benek temizle")
        form.addRow("Parlaklık:", self.brightness)
        form.addRow("Kontrast:", self.contrast)
        form.addRow("Mürekkebi koyulaştır:", self.darken)
        form.addRow("Eşikleme (siyah-beyaz):", self.th_mode)
        form.addRow("Eşik değeri:", self.threshold)
        form.addRow("", self.despeckle)
        lay.addLayout(form)

        presets = QHBoxLayout()
        presets.addWidget(QLabel("Hazır:"))
        for name, preset in self.PRESETS.items():
            b = QPushButton(name)
            b.clicked.connect(lambda _=False, p=preset: self.set_enhancement(p, emit=True))
            presets.addWidget(b)
        lay.addLayout(presets)

        note = QLabel("Ayarlar tüm sayfalara uygulanır ve dışa aktarırken isteğe bağlı olarak korunur. "
                      "Gece modu (I) yalnızca görünümü etkiler.", wordWrap=True)
        note.setStyleSheet("color: palette(mid);")
        lay.addWidget(note)
        buttons = QDialogButtonBox()
        reset = buttons.addButton("Sıfırla", QDialogButtonBox.ButtonRole.ResetRole)
        close = buttons.addButton("Kapat", QDialogButtonBox.ButtonRole.AcceptRole)
        reset.clicked.connect(lambda: self.set_enhancement(Enhancement(), emit=True))
        close.clicked.connect(self.accept)
        lay.addWidget(buttons)

        self._timer = QTimer(self, singleShot=True, interval=180)
        self._timer.timeout.connect(lambda: self.enhancementChanged.emit(self.enhancement()))
        for w in (self.brightness, self.contrast, self.darken, self.threshold):
            w.changed.connect(self._timer.start)
        self.th_mode.currentIndexChanged.connect(self._on_mode)
        self.despeckle.toggled.connect(self._timer.start)
        self.set_enhancement(enh)

    def _on_mode(self) -> None:
        self.threshold.setEnabled(self.th_mode.currentIndex() == 2)
        self._timer.start()

    def enhancement(self) -> Enhancement:
        mode = self.th_mode.currentIndex()
        th = 0 if mode == 0 else (-1 if mode == 1 else self.threshold.value())
        return Enhancement(self.brightness.value(), self.contrast.value(), self.darken.value(),
                           th, self.despeckle.isChecked())

    def set_enhancement(self, enh: Enhancement, emit: bool = False) -> None:
        self.brightness.set_value(enh.brightness)
        self.contrast.set_value(enh.contrast)
        self.darken.set_value(enh.darken)
        self.th_mode.blockSignals(True)
        self.th_mode.setCurrentIndex(0 if enh.threshold == 0 else (1 if enh.threshold < 0 else 2))
        self.th_mode.blockSignals(False)
        if enh.threshold > 0:
            self.threshold.set_value(enh.threshold)
        self.threshold.setEnabled(self.th_mode.currentIndex() == 2)
        self.despeckle.blockSignals(True)
        self.despeckle.setChecked(enh.despeckle)
        self.despeckle.blockSignals(False)
        if emit:
            self.enhancementChanged.emit(self.enhancement())


SHORTCUTS = [
    ("Sonraki / önceki sayfa", "Page Down, → / Page Up, ←"),
    ("İlk / son sayfa", "Home / End"),
    ("Sayfa numarasına git", "Ctrl+G"),
    ("Yakınlaştır / uzaklaştır", "+ / −  (Ctrl + tekerlek)"),
    ("Sayfaya / genişliğe sığdır", "Ctrl+0 / W"),
    ("Gerçek boyut (%100)", "Ctrl+1"),
    ("Sürükleyerek kaydır", "Boşluk tuşu basılı + sürükle, ya da orta tuş"),
    ("Sağa / sola döndür", "R / Shift+R"),
    ("180° çevir", "T"),
    ("Tüm belgeyi sağa döndür / 180°", "Ctrl+Shift+R / Ctrl+Shift+T"),
    ("El aracı / seçim aracı", "H / S"),
    ("Büyüteç (Shift+tekerlek: büyütme oranı)", "M"),
    ("Gece modu (renkleri ters çevir)", "I"),
    ("Görüntü iyileştirme", "Ctrl+B"),
    ("Belgede ara", "Ctrl+F, sonraki: F3 / Enter"),
    ("Seçili alanı resim olarak kopyala", "Ctrl+C"),
    ("Seçili alanı metin olarak kopyala (OCR)", "Ctrl+Shift+C"),
    ("Sayfa sil", "Delete"),
    ("Geri al", "Ctrl+Z"),
    ("Aç / dosya ekle (birleştir)", "Ctrl+O / Ctrl+Shift+O"),
    ("TIFF olarak kaydet / PDF'e aktar", "Ctrl+S / Ctrl+Shift+S"),
    ("Seçili sayfaları dışa aktar", "Ctrl+E"),
    ("Yazdır", "Ctrl+P"),
    ("Tam ekran", "F11"),
]


class ShortcutsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Klavye kısayolları")
        self.resize(560, 640)
        lay = QVBoxLayout(self)
        table = QTableWidget(len(SHORTCUTS), 2)
        table.setHorizontalHeaderLabels(["İşlem", "Kısayol"])
        table.verticalHeader().hide()
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for r, (a, k) in enumerate(SHORTCUTS):
            table.setItem(r, 0, QTableWidgetItem(a))
            table.setItem(r, 1, QTableWidgetItem(k))
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(table)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        b.rejected.connect(self.reject)
        lay.addWidget(b)


# --------------------------------------------------------------------------- ayarlar

class _SettingRow(QWidget):
    """Başlık + açıklama solda, anahtar sağda."""

    def __init__(self, title: str, desc: str, switch):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 6)
        text = QVBoxLayout()
        text.setSpacing(2)
        t = QLabel(title)
        f = t.font()
        f.setBold(True)
        t.setFont(f)
        self.desc = QLabel(desc, wordWrap=True)
        self.desc.setStyleSheet("color: palette(placeholder-text);")
        text.addWidget(t)
        text.addWidget(self.desc)
        lay.addLayout(text, 1)
        lay.addSpacing(12)
        lay.addWidget(switch, 0, Qt.AlignmentFlag.AlignVCenter)


class SettingsDialog(QDialog):
    def __init__(self, win):
        from . import tess_install
        from .widgets import ThemeSwitch, ToggleSwitch

        super().__init__(win)
        self.win = win
        self.setWindowTitle("Ayarlar")
        self.setMinimumWidth(540)
        lay = QVBoxLayout(self)

        g = QGroupBox("Görünüm")
        gl = QVBoxLayout(g)
        self.theme = ThemeSwitch()
        self.theme.toggled.connect(self._on_theme)
        gl.addWidget(_SettingRow("Gece / gündüz teması", "Programın koyu ya da açık renkli görünümü.", self.theme))
        self.follow_system = QCheckBox("İşletim sisteminin temasını izle")
        self.follow_system.toggled.connect(self._on_follow_system)
        gl.addWidget(self.follow_system)
        self.wheel = ToggleSwitch()
        self.wheel.setChecked(win.a_wheel_zoom.isChecked())
        self.wheel.toggled.connect(win.a_wheel_zoom.setChecked)
        gl.addWidget(_SettingRow("Tekerlek ile yakınlaştır",
                                 "Kapalıyken tekerlek sayfayı kaydırır, Ctrl + tekerlek yakınlaştırır.", self.wheel))
        lay.addWidget(g)

        g = QGroupBox("OCR (metin tanıma)")
        gl = QVBoxLayout(g)
        self.ocr = ToggleSwitch()
        gl.addWidget(_SettingRow(
            "OCR'ı kullan — Tesseract'ı indir ve kur",
            "Belgede arama, seçili alanı metin olarak kopyalama, aranabilir PDF ve otomatik yön düzeltme için "
            "gereklidir. Kurulu değilse açtığınızda Tesseract ve Türkçe dil modeli "
            f"(~{tess_install.PORTABLE_MB} MB) indirilip kullanıcı klasörünüze kurulur; yönetici izni gerekmez.",
            self.ocr))
        self.ocr_status = QLabel(wordWrap=True, textInteractionFlags=Qt.TextInteractionFlag.TextSelectableByMouse)
        gl.addWidget(self.ocr_status)
        self.auto_ocr = ToggleSwitch()
        self.auto_ocr.setChecked(win.a_auto_ocr.isChecked())
        self.auto_ocr.toggled.connect(win.a_auto_ocr.setChecked)
        self.auto_row = _SettingRow("Belge açılınca OCR'ı otomatik başlat",
                                    "Sayfalar arka planda, düşük öncelikle taranır.", self.auto_ocr)
        gl.addWidget(self.auto_row)
        self.remove_btn = QPushButton("Programın kurduğu Tesseract'ı kaldır")
        self.remove_btn.clicked.connect(self._remove)
        gl.addWidget(self.remove_btn, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(g)

        g = QGroupBox("Güncellemeler")
        gl = QVBoxLayout(g)
        self.updates = ToggleSwitch()
        self.updates.setChecked(win.auto_update_check)
        self.updates.toggled.connect(win.set_auto_update_check)
        gl.addWidget(_SettingRow(
            "Güncellemeleri otomatik denetle",
            "Program açılırken (günde en fazla bir kez) GitHub'da yeni sürüm olup olmadığına bakar. "
            "Hiçbir şey kendiliğinden indirilmez; yeni sürüm varsa size sorulur.", self.updates))
        row = QHBoxLayout()
        check = QPushButton("Şimdi denetle")
        check.clicked.connect(lambda: win.check_updates(manual=True, parent=self))
        row.addWidget(check)
        self.update_info = QLabel()
        self.update_info.setStyleSheet("color: palette(placeholder-text);")
        row.addWidget(self.update_info, 1)
        gl.addLayout(row)
        lay.addWidget(g)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.ocr.toggled.connect(self._on_ocr_toggled)
        self.refresh()

    def refresh(self) -> None:
        from . import tess_install
        from .widgets import is_dark

        self.follow_system.blockSignals(True)
        self.follow_system.setChecked(self.win.theme_mode == "system")
        self.follow_system.blockSignals(False)
        self.theme.blockSignals(True)
        self.theme.setChecked(is_dark())
        self.theme.blockSignals(False)

        eng = self.win.ocr_engine
        self.ocr.blockSignals(True)
        self.ocr.setChecked(eng.available)
        self.ocr.blockSignals(False)
        if eng.installed:
            text = f"{'✅' if eng.available else '⏸'} {eng.status_text()}<br><small>{eng.exe}</small>"
        elif eng.exe:
            text = f"⚠️ {eng.status_text()}<br><small>{eng.exe}</small>"
        else:
            text = "⬜ Tesseract bu bilgisayarda kurulu değil."
            if not tess_install.supported():
                text += f"<br><small>{tess_install.unsupported_reason()}</small>"
        self.ocr_status.setText(text)
        self.auto_row.setEnabled(eng.available)
        self.remove_btn.setVisible(tess_install.user_install_exists())

        from . import __version__
        last = self.win.settings.value("updates/last_check", "")
        self.update_info.setText(f"Kurulu sürüm: {__version__}" + (f" · son denetim: {last}" if last else ""))

    def _on_theme(self, dark: bool) -> None:
        self.win.set_theme("dark" if dark else "light")
        self.refresh()

    def _on_follow_system(self, on: bool) -> None:
        from .widgets import is_dark
        self.win.set_theme("system" if on else ("dark" if is_dark() else "light"))
        self.refresh()

    def _on_ocr_toggled(self, on: bool) -> None:
        self.win.set_ocr_enabled(on, parent=self, done=self.refresh)

    def _remove(self) -> None:
        self.win.uninstall_tesseract(parent=self, done=self.refresh)


# --------------------------------------------------------------------------- hakkında

FEATURES = [
    ("⚡", "Hızlı çok sayfalı görüntüleme",
     "Yüzlerce sayfalık UYAP evrakı anında açılır; sayfalar ekrana geldikçe işlenir. "
     "Faks çözünürlüklü sayfalar otomatik düzeltilir."),
    ("🔄", "Sayfa yönü düzeltme",
     "Ters ya da yan taranmış sayfaları tek tuşla (R) döndürün veya OCR ile tüm belgeyi otomatik düzeltin."),
    ("🔆", "Okunabilirlik araçları",
     "Soluk mürekkep ve karbon kopyalar için kontrast, koyulaştırma, eşikleme ve benek temizleme."),
    ("🔍", "Büyüteç",
     "Islak imza, mühür ve silik kaşeleri sayfayı büyütmeden imleç takipli büyüteçle inceleyin."),
    ("🔎", "Türkçe OCR ve arama",
     "Taranmış belgede Ctrl+F ile kelime arayın; seçili alanı doğrudan metin olarak kopyalayın."),
    ("🗂", "Sayfa yönetimi",
     "Boş sayfaları bulun, sürükle-bırak ile sıralayın, parça parça gelen evrakları tek belgede birleştirin."),
    ("📄", "PDF ve UYAP uyumlu sıkıştırma",
     "Aranabilir PDF üretin; hedef boyut sınırına sığan en net çıktı otomatik seçilir."),
    ("📋", "Dilekçe için alıntı",
     "İmza, kaşe ya da paragraf alanını seçip resim olarak panoya kopyalayın, dilekçenize yapıştırın."),
    ("🌗", "Gece / gündüz teması",
     "Göz yorgunluğunu azaltan koyu tema ve sayfa renklerini ters çevirme."),
    ("🛡", "Kaynak evrak korunur",
     "Orijinal dosyanın üzerine asla yazılmaz; tüm değişiklikler yeni bir dosyaya kaydedilir."),
]


class AboutDialog(QDialog):
    def __init__(self, parent, icon, ocr_status: str):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWidgets import QFrame, QGridLayout, QScrollArea

        from . import APP_NAME, DEVELOPER_EMAIL, GITHUB_URL, __version__

        super().__init__(parent)
        self.setWindowTitle("Hakkında")
        self.resize(740, 700)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame(objectName="aboutHeader")
        header.setStyleSheet("#aboutHeader { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                             "stop:0 #8e1b26, stop:1 #3b1f4a); } #aboutHeader QLabel { color: white; }")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(28, 22, 28, 22)
        logo = QLabel()
        logo.setPixmap(icon.pixmap(72, 72))
        hl.addWidget(logo)
        hl.addSpacing(12)
        titles = QVBoxLayout()
        name = QLabel(APP_NAME)
        f = name.font()
        f.setPointSize(f.pointSize() + 8)
        f.setBold(True)
        name.setFont(f)
        titles.addWidget(name)
        titles.addWidget(QLabel(f"Sürüm {__version__}  ·  Windows ve macOS"))
        tag = QLabel("UYAP, emniyet ve mahkemelerden gelen TIFF evrakları için hukuk pratiğine özel görüntüleyici.",
                     wordWrap=True)
        tag.setStyleSheet("color: rgba(255,255,255,0.85);")
        titles.addWidget(tag)
        hl.addLayout(titles, 1)
        outer.addWidget(header)

        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(20, 18, 20, 18)
        grid.setSpacing(12)
        for i, (emoji, title, text) in enumerate(FEATURES):
            card = QFrame(objectName="featureCard")
            card.setStyleSheet("#featureCard { border: 1px solid palette(midlight); border-radius: 10px; "
                               "background: palette(base); }")
            cl = QHBoxLayout(card)
            cl.setContentsMargins(12, 10, 12, 10)
            e = QLabel(emoji)
            ef = e.font()
            ef.setPointSize(ef.pointSize() + 9)
            e.setFont(ef)
            e.setAlignment(Qt.AlignmentFlag.AlignTop)
            e.setFixedWidth(38)
            cl.addWidget(e)
            tl = QVBoxLayout()
            tl.setSpacing(3)
            t = QLabel(title)
            tf = t.font()
            tf.setBold(True)
            t.setFont(tf)
            d = QLabel(text, wordWrap=True)
            d.setStyleSheet("color: palette(placeholder-text);")
            tl.addWidget(t)
            tl.addWidget(d)
            tl.addStretch(1)
            cl.addLayout(tl, 1)
            grid.addWidget(card, i // 2, i % 2)
        scroll = QScrollArea(widgetResizable=True, frameShape=QFrame.Shape.NoFrame)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        footer = QFrame(objectName="aboutFooter")
        footer.setStyleSheet("#aboutFooter { border-top: 1px solid palette(midlight); }")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(20, 12, 20, 14)
        info = QLabel(f"<small>OCR: {ocr_status}<br>Geliştirici: "
                      f"<a href='mailto:{DEVELOPER_EMAIL}'>{DEVELOPER_EMAIL}</a></small>",
                      openExternalLinks=True)
        fl.addWidget(info, 1)
        contact = QPushButton("✉  Geliştiriciyle iletişim")
        contact.setToolTip(DEVELOPER_EMAIL)
        subject = bytes(QUrl.toPercentEncoding(f"{APP_NAME} {__version__} hakkında")).decode()
        contact.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(f"mailto:{DEVELOPER_EMAIL}?subject={subject}")))
        fl.addWidget(contact)
        if GITHUB_URL:
            gh = QPushButton("⭐  GitHub")
            gh.setToolTip(GITHUB_URL)
            gh.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL)))
            fl.addWidget(gh)
        close = QPushButton("Kapat")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        fl.addWidget(close)
        outer.addWidget(footer)
