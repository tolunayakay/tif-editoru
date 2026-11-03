"""Uygulama girişi: QApplication, macOS dosya açma olayları, hata yakalama."""
from __future__ import annotations

import sys
import traceback

from PySide6.QtCore import QEvent, QLibraryInfo, QLocale, Qt, QTranslator
from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_NAME, APP_ORG, __version__


class App(QApplication):
    def __init__(self, argv: list[str]):
        super().__init__(argv)
        self.setApplicationName(APP_NAME)
        self.setOrganizationName(APP_ORG)
        self.setApplicationVersion(__version__)
        self.window = None
        self._queued: list[str] = []

    def event(self, e) -> bool:
        # macOS: Finder'dan "Birlikte Aç" ya da Dock'a sürükleme
        if e.type() == QEvent.Type.FileOpen:
            path = e.file()
            if self.window is not None:
                self.window.open_files([path], append=False)
            else:
                self._queued.append(path)
            return True
        return super().event(e)


def _excepthook(exc_type, exc, tb) -> None:
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    sys.stderr.write(text)
    app = QApplication.instance()
    if app is not None:
        QMessageBox.critical(None, APP_NAME, f"Beklenmeyen bir hata oluştu:\n\n{exc}\n\n{text[-1500:]}")


def run(argv: list[str]) -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("UyapTif.Viewer")
        except Exception:
            pass
    app = App(argv)
    sys.excepthook = _excepthook
    # Standart düğmeler (Evet/Hayır/Kapat…) ve iletişim kutuları Türkçe olsun
    translator = QTranslator(app)
    if translator.load(QLocale(QLocale.Language.Turkish), "qtbase", "_",
                       QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)

    from .mainwindow import MainWindow, app_icon
    app.setWindowIcon(app_icon())
    win = MainWindow()
    app.window = win
    win.show()
    files = [a for a in argv[1:] if not a.startswith("-")] + app._queued
    if files:
        win.open_files(files[:1])
        if len(files) > 1:
            win.open_files(files[1:], append=True)
    return app.exec()
