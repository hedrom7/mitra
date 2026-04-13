"""Command line entry-point for the desktop site downloader."""
import os
import sys
from pathlib import Path

# PyInstaller bundle içindeyse Playwright path'ini ayarla
# BU ÇOK ÖNEMLİ: Bu ayar Playwright import edilmeden ÖNCE yapılmalı!
if getattr(sys, 'frozen', False):
    # PyInstaller bundle içindeyiz
    # sys.executable: .../Mitra.app/Contents/MacOS/site-downloader
    # app_bundle: .../Mitra.app
    app_bundle = Path(sys.executable).parent.parent.parent
    
    # Resources klasörü Contents/Resources altında
    resources_dir = app_bundle / 'Contents' / 'Resources'
    
    # Playwright tarayıcıları ms-playwright/ altında olmalı
    ms_playwright_dir = resources_dir / 'ms-playwright'
    
    if ms_playwright_dir.exists():
        playwright_path = str(ms_playwright_dir.resolve())
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = playwright_path
    else:
        # Eski yapı için geriye dönük uyumluluk
        playwright_browsers_dir = resources_dir / 'playwright-browsers'
        if playwright_browsers_dir.exists():
            os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(playwright_browsers_dir.resolve())

# Playwright import edilmeden önce path ayarlandı, şimdi import edebiliriz
from site_downloader.gui import run

if __name__ == "__main__":
    run()
