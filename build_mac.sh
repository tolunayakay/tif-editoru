#!/usr/bin/env bash
# macOS için .app paketi ve .dmg üretir.
# OCR için: brew install tesseract tesseract-lang   (uygulama Homebrew kurulumunu otomatik bulur)
set -euo pipefail
cd "$(dirname "$0")"

python3 -m venv .venv
.venv/bin/python -m pip install -q -r requirements.txt pyinstaller
.venv/bin/python tools/make_icon.py
.venv/bin/python -m PyInstaller --noconfirm --clean UyapTifViewer.spec

APP="dist/UYAP TIFF Görüntüleyici.app"
# İmzasız uygulamanın Gatekeeper tarafından engellenmemesi için ad-hoc imza
codesign --force --deep --sign - "$APP" || true
hdiutil create -volname "UYAP TIFF Görüntüleyici" -srcfolder "$APP" -ov -format UDZO dist/UyapTifViewer.dmg
echo "Hazır: $APP ve dist/UyapTifViewer.dmg"
