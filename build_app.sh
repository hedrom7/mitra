#!/bin/bash

set -e

echo "🚀 Mitra uygulaması oluşturuluyor..."

# Sanal ortam oluştur veya kullan
if [ ! -d "venv" ]; then
    echo "📦 Sanal ortam oluşturuluyor..."
    python3 -m venv venv
fi

echo "📦 Bağımlılıklar yükleniyor..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

echo "🌐 Playwright tarayıcıları yükleniyor..."
python3 -m playwright install chromium

# İkon dosyasını kontrol et ve gerekirse dönüştür
ICON_PNG=""
ICON_ICNS=""

# PNG dosyası varsa ICNS'e dönüştür
for png_file in app_icon.png icon.png *.png; do
    if [ -f "$png_file" ] && [ "$png_file" != "*.png" ]; then
        ICON_PNG="$png_file"
        ICON_ICNS="${png_file%.png}.icns"
        if [ ! -f "$ICON_ICNS" ]; then
            echo "🖼️  PNG ikon bulundu, ICNS'e dönüştürülüyor..."
            ./convert_icon.sh "$ICON_PNG" 2>/dev/null || echo "⚠️  İkon dönüştürme başarısız, ikon olmadan devam ediliyor"
        fi
        break
    fi
done

# ICNS dosyasını ara
if [ -z "$ICON_ICNS" ] || [ ! -f "$ICON_ICNS" ]; then
    for icns_file in app_icon.icns icon.icns *.icns; do
        if [ -f "$icns_file" ] && [ "$icns_file" != "*.icns" ]; then
            ICON_ICNS="$icns_file"
            break
        fi
    done
fi

if [ -f "$ICON_ICNS" ]; then
    echo "✅ İkon bulundu: $ICON_ICNS"
    # Sadece ana uygulama spec'ini güncelle (installer yok)
    sed -i.bak "s|icon=None|icon='$ICON_ICNS'|g" site-downloader.spec 2>/dev/null || \
    sed -i '' "s|icon=None|icon='$ICON_ICNS'|g" site-downloader.spec 2>/dev/null
    rm -f site-downloader.spec.bak 2>/dev/null
else
    echo "ℹ️  İkon dosyası bulunamadı, varsayılan ikon kullanılacak"
    echo "   İkon eklemek için: PNG dosyasını proje klasörüne koyun ve ./convert_icon.sh <dosya.png> çalıştırın"
fi

echo "🔨 PyInstaller ile uygulama derleniyor..."
pyinstaller site-downloader.spec --clean --noconfirm

# Playwright tarayıcılarını bul ve kopyala
echo "📦 Playwright tarayıcıları bundle'a ekleniyor..."
PYTHON_SCRIPT=$(cat <<'EOF'
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

p = sync_playwright().start()
chromium_path = Path(p.chromium.executable_path)
p.stop()

# Playwright root dizinini bul (ms-playwright klasörü)
# chromium_path: .../chromium-1200/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing
# Root: .../ms-playwright/ (bir parent daha yukarı)
browsers_path = chromium_path.parent.parent.parent.parent.parent.parent
print(str(browsers_path))
EOF
)

PLAYWRIGHT_ROOT=$(python3 -c "$PYTHON_SCRIPT")
APP_RESOURCES="dist/Mitra.app/Contents/Resources"
PLAYWRIGHT_CACHE="$HOME/Library/Caches/ms-playwright"

if [ -d "$PLAYWRIGHT_CACHE" ]; then
    mkdir -p "$APP_RESOURCES/ms-playwright"
    
    # chromium-1200 ve chromium_headless_shell-1200 klasörlerini kopyala
    if [ -d "$PLAYWRIGHT_CACHE/chromium-1200" ]; then
        cp -RL "$PLAYWRIGHT_CACHE/chromium-1200" "$APP_RESOURCES/ms-playwright/"
        echo "✅ chromium-1200 kopyalandı"
    fi
    
    if [ -d "$PLAYWRIGHT_CACHE/chromium_headless_shell-1200" ]; then
        cp -RL "$PLAYWRIGHT_CACHE/chromium_headless_shell-1200" "$APP_RESOURCES/ms-playwright/"
        echo "✅ chromium_headless_shell-1200 kopyalandı"
    fi
    
    echo "✅ Playwright tarayıcıları kopyalandı: $APP_RESOURCES/ms-playwright"
else
    echo "⚠️  Playwright tarayıcıları bulunamadı, manuel olarak eklemeniz gerekebilir"
fi

# Quarantine flag'ini kaldır (macOS güvenlik)
echo "🔓 macOS güvenlik flag'i kaldırılıyor..."
xattr -cr "dist/Mitra.app" 2>/dev/null || echo "⚠️  xattr komutu çalıştırılamadı (normal olabilir)"

echo ""
echo "📦 DMG kurulum paketi oluşturuluyor..."

# DMG için geçici klasör oluştur
DMG_DIR="dist/dmg_contents"
rm -rf "$DMG_DIR"
mkdir -p "$DMG_DIR"

# Sadece uygulamayı kopyala (installer yok - klasik drag-and-drop)
cp -r "dist/Mitra.app" "$DMG_DIR/"

# Applications klasörüne sembolik link oluştur (sürükle-bırak için)
ln -s /Applications "$DMG_DIR/Applications"

# DMG oluştur
DMG_NAME="Mitra.dmg"
DMG_PATH="dist/$DMG_NAME"

# Eski DMG'yi sil
rm -f "$DMG_PATH"

# DMG'yi önce read-write modda oluştur (ikon eklemek için)
# Boyutu otomatik hesapla (içerik + %20 ekstra)
CONTENT_SIZE=$(du -sm "$DMG_DIR" | cut -f1)
DMG_SIZE=$((CONTENT_SIZE + CONTENT_SIZE / 5 + 50))  # %20 ekstra + 50MB güvenlik payı
TEMP_DMG="${DMG_PATH%.dmg}.rw.dmg"
hdiutil create -volname "Mitra" -srcfolder "$DMG_DIR" -ov -format UDRW -size ${DMG_SIZE}m "$TEMP_DMG"

# DMG'ye ikon ekle
if [ -f "$ICON_ICNS" ]; then
    echo "🖼️  DMG'ye ikon ekleniyor..."
    
    # DMG'yi mount et
    MOUNT_POINT="/Volumes/Mitra"
    
    # Eğer zaten mount edilmişse unmount et
    if [ -d "$MOUNT_POINT" ]; then
        hdiutil detach "$MOUNT_POINT" -quiet 2>/dev/null || true
        sleep 1
    fi
    
    # DMG'yi mount et (read-write)
    hdiutil attach "$TEMP_DMG" -quiet -mountpoint "$MOUNT_POINT" 2>/dev/null
    
    if [ -d "$MOUNT_POINT" ]; then
        # İkonu kopyala
        cp "$ICON_ICNS" "$MOUNT_POINT/.VolumeIcon.icns"
        
        # Volume icon'u ayarla
        SetFile -a C "$MOUNT_POINT" 2>/dev/null || \
        /usr/bin/SetFile -a C "$MOUNT_POINT" 2>/dev/null || \
        echo "⚠️  SetFile bulunamadı, ikon görünmeyebilir"
        
        # Unmount et
        hdiutil detach "$MOUNT_POINT" -quiet 2>/dev/null || true
        sleep 1
        
        echo "✅ DMG ikonu eklendi"
    else
        echo "⚠️  DMG mount edilemedi, ikon eklenemedi"
    fi
fi

# Read-write DMG'yi sıkıştırılmış read-only DMG'ye dönüştür
hdiutil convert "$TEMP_DMG" -format UDZO -ov -o "$DMG_PATH"
rm -f "$TEMP_DMG"

# DMG dosyasının kendisine ikon ekle (Finder'da görünmesi için)
if [ -f "$ICON_ICNS" ] && [ -f "$DMG_PATH" ]; then
    echo "🖼️  DMG dosyasına ikon ekleniyor..."
    # Python script ile ikon ekle
    python3 set_dmg_icon.py "$DMG_PATH" "$ICON_ICNS" 2>/dev/null || \
    # Alternatif: sips kullan
    sips -i "$ICON_ICNS" >/dev/null 2>&1 && \
    DeRez -only icns "$ICON_ICNS" > /tmp/icon.rsrc 2>/dev/null && \
    Rez -append /tmp/icon.rsrc -o "$DMG_PATH" 2>/dev/null && \
    SetFile -a C "$DMG_PATH" 2>/dev/null && \
    rm -f /tmp/icon.rsrc 2>/dev/null && \
    touch "$DMG_PATH" || \
    echo "⚠️  DMG dosyası ikonu eklenemedi (normal olabilir)"
fi

# Geçici klasörü temizle
rm -rf "$DMG_DIR"

# Quarantine flag'ini kaldır
xattr -cr "$DMG_PATH" 2>/dev/null || true

echo ""
echo "✅ Build tamamlandı!"
echo ""
echo "📦 Kurulum paketi hazır: $DMG_PATH"
echo ""
echo "📋 Kullanım (Klasik macOS Kurulum):"
echo "   1. 'Mitra.dmg' dosyasını açın"
echo "   2. Açılan pencerede 'Mitra.app' dosyasını 'Applications' klasörüne sürükleyin"
echo "   3. DMG'yi çıkarın (Finder'da sağ tık > Eject)"
echo "   4. Spotlight'tan (Cmd+Space) 'Mitra' yazarak uygulamayı açın"
echo ""
echo "💡 DMG dosyasını başka bilgisayarlara kopyalayabilirsiniz!"
