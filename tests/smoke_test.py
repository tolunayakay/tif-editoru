"""Arayüzsüz duman testi: örnek TIFF'leri açar, işler ve dışa aktarır.

    QT_QPA_PLATFORM=offscreen python tests/smoke_test.py
"""
import os
import sys
import tempfile
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from PIL import Image  # noqa: E402

from uyaptif.app import App  # noqa: E402
from uyaptif.export import PROFILE_BY_KEY, export_pdf, export_tiff  # noqa: E402
from uyaptif.imaging import Enhancement, ink_ratio, load_frame  # noqa: E402
from uyaptif.mainwindow import MainWindow  # noqa: E402

SAMPLES = os.path.join(ROOT, "samples")


def main() -> None:
    app = App(sys.argv)
    win = MainWindow()
    win.show()

    def pump(seconds, until):
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            if until():
                return True
            time.sleep(0.01)
        return until()

    win.open_files([os.path.join(SAMPLES, "uyap_ornek.tif")])
    assert pump(15, lambda: win.view.image is not None), "ilk sayfa gösterilemedi"
    win.open_files([os.path.join(SAMPLES, "faks_204x98.tif"), os.path.join(SAMPLES, "soluk_gri.tif")], append=True)
    assert len(win.doc.pages) == 6, len(win.doc.pages)

    img, dpi = load_frame(os.path.join(SAMPLES, "faks_204x98.tif"), 0)
    assert img.size == (1728, 2290) and dpi == 204, (img.size, dpi)
    assert ink_ratio(load_frame(os.path.join(SAMPLES, "uyap_ornek.tif"), 2)[0]) < 0.003
    assert ink_ratio(load_frame(os.path.join(SAMPLES, "soluk_gri.tif"), 0)[0]) > 0.003

    win.goto(1)
    win.rotate(180)
    assert win.doc.pages[1].rotation == 180
    win.delete_pages()
    assert len(win.doc.pages) == 5
    win.undo()
    assert len(win.doc.pages) == 6

    win.set_enhancement(Enhancement(contrast=30, darken=40, threshold=-1))
    assert pump(15, lambda: win.renderer.get(win.page, win.enh) is not None)
    theme = win.theme_mode
    win.set_theme("dark")
    win.set_theme("light")
    win.set_theme(theme)

    out = tempfile.mkdtemp()
    noop = lambda *a: None  # noqa: E731
    for key in ("orijinal", "dengeli", "kucuk"):
        info = export_pdf(os.path.join(out, f"{key}.pdf"), win.doc.pages, None, PROFILE_BY_KEY[key], None, noop)
        assert info["size"] > 1000, info
    info = export_tiff(os.path.join(out, "out.tif"), win.doc.pages, None, PROFILE_BY_KEY["orijinal"], noop)
    with Image.open(info["path"]) as t:
        assert t.n_frames == 6, t.n_frames

    win.doc.modified = False
    win.close()
    print("DUMAN TESTİ BAŞARILI")


if __name__ == "__main__":
    main()
