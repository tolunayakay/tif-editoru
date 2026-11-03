# Windows için taşınabilir paket üretir:
#   dist\UyapTifViewer.exe                    (tek dosya, kurulumsuz)
#   dist\UyapTifViewer-portable\              (exe + isteğe bağlı tesseract klasörü)
#   dist\UyapTifViewer-portable.zip
#
# OCR'ı pakete gömmek için: UB Mannheim Tesseract'ı Türkçe dil paketiyle kurun ve
# "C:\Program Files\Tesseract-OCR" klasörünü vendor\tesseract olarak kopyalayın.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) { py -3.12 -m venv .venv }
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install -q -r requirements.txt pyinstaller
& $py tools\make_icon.py
& $py -m PyInstaller --noconfirm --clean UyapTifViewer.spec

$portable = "dist\UyapTifViewer-portable"
if (Test-Path $portable) { Remove-Item -Recurse -Force $portable }
New-Item -ItemType Directory -Force $portable | Out-Null
Copy-Item dist\UyapTifViewer.exe $portable

if (Test-Path vendor\tesseract\tesseract.exe) {
    Write-Host "Tesseract pakete ekleniyor..."
    $dst = "$portable\tesseract"
    New-Item -ItemType Directory -Force "$dst\tessdata" | Out-Null
    Get-ChildItem vendor\tesseract -File | Where-Object { $_.Extension -in ".exe", ".dll" } |
        Copy-Item -Destination $dst
    foreach ($f in "tur.traineddata", "eng.traineddata", "osd.traineddata", "pdf.ttf") {
        if (Test-Path "vendor\tesseract\tessdata\$f") { Copy-Item "vendor\tesseract\tessdata\$f" "$dst\tessdata" }
    }
    if (Test-Path vendor\tesseract\tessdata\configs) {
        Copy-Item -Recurse vendor\tesseract\tessdata\configs "$dst\tessdata\configs"
    }
} else {
    Write-Host "vendor\tesseract bulunamadı: OCR, kullanıcının bilgisayarındaki Tesseract kurulumuna bağlı olacak."
}

Compress-Archive -Force -Path "$portable\*" -DestinationPath "dist\UyapTifViewer-portable.zip"
Write-Host "Hazır: dist\UyapTifViewer.exe ve dist\UyapTifViewer-portable.zip"
