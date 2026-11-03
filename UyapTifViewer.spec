# -*- mode: python ; coding: utf-8 -*-
# PyInstaller tarifi. Windows'ta tek dosya .exe, macOS'ta .app paketi üretir.
#   pyinstaller --noconfirm UyapTifViewer.spec
import sys
from pathlib import Path

ROOT = Path(SPECPATH)
sys.path.insert(0, str(ROOT))
from uyaptif import __version__  # noqa: E402

NAME = "UyapTifViewer"
ICON_WIN = ROOT / "assets" / "icon.ico"
ICON_MAC = ROOT / "assets" / "icon.icns"

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    excludes=["tkinter", "unittest", "pydoc", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtWebEngineCore",
              "PySide6.QtNetwork", "PySide6.QtMultimedia", "PySide6.QtOpenGL", "PySide6.QtSql"],
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=False,
              icon=str(ICON_MAC) if ICON_MAC.exists() else None)
    coll = COLLECT(exe, a.binaries, a.datas, name=NAME)
    app = BUNDLE(
        coll,
        name="UYAP TIFF Görüntüleyici.app",
        icon=str(ICON_MAC) if ICON_MAC.exists() else None,
        bundle_identifier="tr.uyaptif.viewer",
        info_plist={
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "TIFF Görüntüsü",
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": ["public.tiff"],
                "CFBundleTypeExtensions": ["tif", "tiff"],
            }],
        },
    )
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name=NAME, console=False, upx=False,
              icon=str(ICON_WIN) if ICON_WIN.exists() else None)
