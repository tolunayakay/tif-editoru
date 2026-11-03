# UYAP TIFF Görüntüleyici

UYAP, emniyet ve mahkemelerden gelen çok sayfalı `.tif` / `.tiff` evraklar (1-bit CCITT G4,
faks çözünürlüğü, ters taranmış sayfalar, devasa dosyalar) için Windows ve macOS'ta çalışan
masaüstü görüntüleyici. Python + Qt (PySide6) ile yazılmıştır.

## İndir

**Windows:** [Sürümler](https://github.com/tolunayakay/tif-editoru/releases) sayfasından `UyapTifViewer.exe`
dosyasını indirip çalıştırın. Kurulum gerekmez. OCR için programda **Ayarlar → "OCR'ı kullan"** anahtarını açmanız yeterli.

**macOS:** Aynı sayfadan Apple Silicon (M1 ve sonrası) için `UyapTifViewer-macOS-arm64.dmg`,
Intel Mac için `UyapTifViewer-macOS-x86_64.dmg` dosyasını indirin, uygulamayı Uygulamalar klasörüne sürükleyin.
Uygulama Apple tarafından onaylanmadığı için ilk açılışta **sağ tık → Aç** deyin
(veya Sistem Ayarları → Gizlilik ve Güvenlik → "Yine de aç"). OCR için Homebrew gerekir.

## Özellikler

| Alan | Özellik |
|---|---|
| Görüntüleme | Sayfalar ekrana geldikçe işlenir (lazy loading + bellek sınırlı önbellek, sonraki sayfa önceden hazırlanır) · Faks (204×98 dpi) sayfaları kare piksele düzeltilir · Uzaklaştırırken yazıların bozulmaması için yüksek kaliteli küçültme |
| Gezinme | Sol panelde küçük resimler (yalnızca görünenler üretilir) · PgUp/PgDn, ←/→, Home/End, Ctrl+G · Sayfa sonunda tekerlekle sonraki sayfaya geçiş |
| Yakınlaştırma | Ctrl+tekerlek (imleç altına) ya da ayardan Ctrl'siz tekerlek · Sayfaya / genişliğe sığdır · Boşluk basılı + sürükle, orta tuşla kaydırma |
| Döndürme | Sayfa veya seçili sayfalar (R, Shift+R, T) · Tüm belge (Ctrl+Shift+R / T) · Tesseract OSD ile otomatik yön düzeltme |
| Okunabilirlik | Parlaklık, kontrast, "mürekkebi koyulaştır" (gamma), Otsu/elle eşikleme, benek temizleme · Hazır ayarlar: soluk mürekkep, karbon kopya · Gece modu (I) · İmleç takipli büyüteç (M, Shift+tekerlek ile oran) |
| OCR | Arka planda düşük öncelikli Tesseract (Türkçe) · Ctrl+F ile belge içi arama, eşleşmeler sayfada vurgulanır, "Türkçe harf duyarsız" seçeneği · Seçili alanı metin olarak kopyalama (Ctrl+Shift+C) |
| Sayfa yönetimi | Silme (Delete), sürükle-bırak ile sıralama, Ctrl+Z geri alma · Boş sayfa tespiti · Dosya ekleyerek birleştirme (Ctrl+Shift+O veya pencereye sürükle-bırak) |
| Dışa aktarma | TIFF (G4) ve PDF · Seçili sayfa / aralık (`1-3, 7, 10-`) · Aranabilir PDF (OCR katmanı) · Döndürme ve iyileştirmeler korunur · S/B sayfalar PDF'e kayıpsız G4 olarak gömülür |
| UYAP profilleri | Orijinal · Dengeli (200 dpi) · Küçük (150 dpi S/B) · **Hedef boyuta sığdır**: belirttiğiniz MB sınırına inen en kaliteli profil otomatik seçilir |
| Pano | Seçili alanı resim olarak kopyalama (Ctrl+C) — dilekçeye imza/kaşe/paragraf eklemek için · PNG olarak kaydetme |
| Tema | Araç çubuğunun sağındaki ay/güneş anahtarı ile gece (koyu) / gündüz (açık) tema · Ayarlar'dan sistem temasını izleme |
| Ayarlar (Ctrl+,) | Tema, tekerlek davranışı, **OCR'ı kullan** anahtarı (Tesseract'ı programın kendisi indirip kurar), otomatik OCR, **güncellemeleri otomatik denetle** anahtarı (varsayılan kapalı) |
| Güncellemeler | Anahtar açıksa program açılışta günde en fazla bir kez GitHub'daki `v…` etiketli sürümlere bakar; hiçbir şey kendiliğinden indirilmez. Yardım → Güncellemeleri denetle ile elle de denetlenebilir |
| Sistem | Windows: .tif/.tiff "Birlikte aç" kaydı ve sağ tık menüsünde "TIFF Görüntüleyici ile Aç" (yönetici yetkisi gerekmez) · macOS: Finder'dan açma · Yazdırma · Tam ekran (F11) · Tek dosya taşınabilir .exe |

Tüm kısayollar için uygulamada **F1**.

> Kaynak evrakın üzerine asla yazılmaz: kaydetme her zaman yeni bir dosyaya yapılır
> (varsayılan ad `..._duzenlenmis.tif`).

## Geliştirme ortamında çalıştırma

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # macOS: .venv/bin/python
.venv/Scripts/python main.py samples/uyap_ornek.tif
```

`tools/make_samples.py` deneme için ters sayfa, boş sayfa, faks ve soluk gri sayfa içeren örnek dosyalar üretir.

## OCR (Tesseract) kurulumu

OCR olmadan görüntüleme, döndürme, iyileştirme, sayfa yönetimi ve dışa aktarma çalışır;
arama, metin kopyalama, aranabilir PDF ve otomatik yön düzeltme için Tesseract gerekir.

**En kolayı:** Uygulamada **Ayarlar → "OCR'ı kullan — Tesseract'ı indir ve kur"** anahtarını açın.

- Windows'ta taşınabilir Tesseract paketi (~49 MB) projenin GitHub sürümlerinden indirilir,
  SHA-256 ile doğrulanır ve `%LOCALAPPDATA%\UyapTif\Tesseract-OCR` klasörüne açılır.
  Yönetici izni gerekmez ve bilgisayardaki başka Tesseract kurulumlarına dokunulmaz.
  Ayarlar'daki düğmeyle tekrar kaldırılabilir.
- macOS'ta Homebrew varsa `brew install tesseract tesseract-lang` çalıştırılır.

### İndirilebilir Tesseract paketini yayımlama (geliştirici)

Programın indirdiği zip, kurulu bir Windows Tesseract'ından üretilir:

```bash
.venv/Scripts/python -m pip install pefile
.venv/Scripts/python tools/make_tesseract_zip.py
```

Çıkan `dist/tesseract-portable-win64.zip` dosyası GitHub'da **`tesseract-5.4.0.20240606`** etiketli
bir sürüme aynı adla yüklenmelidir. Betiğin yazdığı SHA-256 değeri `uyaptif/tess_install.py` içindeki
`PORTABLE_SHA256` ile aynı olmalıdır; zip yeniden üretilirse bu değer de güncellenmelidir.

### Elle kurulum

- **Windows:** [UB Mannheim Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) kurulumunda
  "Additional language data" altından **Turkish**'i seçin. Program `C:\Program Files\Tesseract-OCR`'ı kendiliğinden bulur.
- **macOS:** `brew install tesseract tesseract-lang`
- **Taşınabilir paket:** Tesseract klasörünü `vendor/tesseract` olarak kopyalayıp `build_windows.ps1`'i çalıştırın;
  zip içinde exe'nin yanına `tesseract/` klasörü olarak eklenir (yalnızca `tur`, `eng`, `osd` modelleri).
- Başka bir konum için `UYAPTIF_TESSERACT` ortam değişkenine `tesseract` dosyasının tam yolunu yazın.

## Paketleme

- **Windows:** `powershell -ExecutionPolicy Bypass -File build_windows.ps1`
  → `dist\UyapTifViewer.exe` (tek dosya) ve `dist\UyapTifViewer-portable.zip`
- **macOS** (Mac üzerinde derlenmelidir): `./build_mac.sh`
  → `dist/UYAP TIFF Görüntüleyici.app` ve `dist/UyapTifViewer.dmg`.
  `v…` etiketi gönderildiğinde GitHub Actions ([.github/workflows/macos.yml](.github/workflows/macos.yml))
  her iki işlemci için DMG'leri kendiliğinden derleyip sürüme ekler; Actions sekmesinden var olan bir sürüm için elle de çalıştırılabilir.
- **Duman testi:** `QT_QPA_PLATFORM=offscreen python tests/smoke_test.py`

Windows'ta varsayılan uygulama yapmak için: **Araçlar → Windows entegrasyonu → ilişkilendirmeyi ekle**,
ardından açılan "Varsayılan uygulamalar" sayfasında .tif/.tiff için programı seçin
(Windows 10/11 bu seçimin programla yapılmasına izin vermez).

## İletişim

Geliştirici: [tolunay.akay@galahukuk.com](mailto:tolunay.akay@galahukuk.com) ·
GitHub: <https://github.com/tolunayakay/tif-editoru>

## Proje yapısı

```
main.py                    giriş noktası
uyaptif/
  app.py                   QApplication, macOS dosya açma olayı, hata yakalama
  mainwindow.py            menüler, araç çubuğu, arama, sayfa işlemleri, dışa aktarma akışı
  viewer.py                sayfa görünümü: zoom, kaydırma, seçim, büyüteç, vurgular
  thumbs.py                küçük resim paneli (sürükle-bırak sıralama)
  render.py                arka plan sayfa/küçük resim işleme, LRU önbellek, iş parçacığı görevleri
  imaging.py               TIFF yükleme (Pillow + Qt yedeği), faks düzeltme, iyileştirme filtreleri
  document.py              sayfa listesi modeli ve geri alma
  ocr.py                   Tesseract çağrıları, arka plan OCR, Türkçe arama
  export.py                TIFF/PDF üretimi, sıkıştırma profilleri
  dialogs.py               dışa aktarma, iyileştirme, kısayol, ayarlar ve hakkında pencereleri
  widgets.py               anahtar (switch) ve ay/güneş tema anahtarı, tema yardımcıları
  tess_install.py          Tesseract'ın indirilip kullanıcı klasörüne kurulması
  platform_integration.py  Windows kayıt defteri (HKCU) entegrasyonu
```

## Lisans

GNU General Public License v3.0 — ayrıntılar için [LICENSE](LICENSE).
