# Mitra — Web Sitesi İndirici

Web sitelerini Playwright destekli headless Chromium ile offline olarak indirir.
Dinamik içerik (lazy-load, scroll), Google Fonts, CSS/JS, resimler ve iç bağlantılar
otomatik olarak yakalanır; bağlantılar yerel dosyalara yönlendirilir.

---

## Kurulum

### Gereksinimler
- Python 3.10+
- pip

### Kurulum

```bash
git clone https://github.com/hedrom7/mitra.git
cd mitra
bash install.sh
```

Yeni terminal aç:

```bash
mitra
```

> İlk çalıştırmada Chromium (~170 MB) **otomatik** indirilir. Başka bir şey yapmanıza gerek yoktur.

---

## Kullanım

### İnteraktif mod (önerilen)

```
mitra
```

Adım adım sorular yanıtlanır:

```
  ┌──────────────────────────────────────────────┐
  │        MITRA — Web Sitesi İndirici           │
  └──────────────────────────────────────────────┘

  Site URL'si     : https://example.com
  Kayıt klasörü   : [~/mitra-sites/example.com]
  Derinlik        : [1]
  Eş zamanlı      : [3]

  Gelişmiş ayarlar? (e/H) :

  ──────────────────────────────────────────────
  ▶  https://example.com
  📁 /Users/ad/mitra-sites/example.com
  Derinlik: 1  |  Eş zamanlı: 3  |  Kaydırma: 6
  ──────────────────────────────────────────────

  Başlatmak için Enter'a basın  (q = iptal):
```

### Komut satırı modları

```bash
# URL belirt, klasörü otomatik belirle
mitra https://example.com

# Klasör belirt
mitra https://example.com -o ~/siteler/example

# Derin tarama
mitra https://example.com -o ./çıktı -d 3 -c 5

# Tarayıcıyı görünür aç (debug)
mitra https://example.com --no-headless
```

### Tüm seçenekler

| Seçenek | Kısa | Varsayılan | Açıklama |
|---|---|---|---|
| `url` | — | — | İndirilecek site URL'si |
| `--output` | `-o` | `~/mitra-sites/<alan>` | Kayıt klasörü |
| `--depth` | `-d` | `1` | Maksimum tarama derinliği |
| `--concurrent` | `-c` | `3` | Eş zamanlı sayfa sayısı |
| `--scroll` | — | `6` | Lazy-load için kaydırma adımı |
| `--max-size` | — | `50 MB` | Bu boyuttan büyük dosyaları atla |
| `--no-headless` | — | — | Tarayıcıyı görünür modda aç |
| `--no-resume` | — | — | Mevcut dosyaları yeniden indir |
| `--rate-limit` | — | `200 ms` | Sayfalar arası bekleme süresi |

---

## Özellikler

- Playwright tabanlı headless Chromium
- Lazy-load içerik için otomatik kaydırma
- Google Fonts (Poppins vb.) offline indirme
- CSS `url()` ve `@import` yeniden yazımı
- SmartMenus / Elementor uyumlu HTML temizleme
- Devam etme desteği (indirilmiş dosyaları atla)
- PySide6 masaüstü arayüzü (`python main.py`)

---

## Geliştirme ortamı

```bash
git clone https://github.com/hedrom7/mitra.git
cd mitra
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[gui]"
playwright install chromium
```

```bash
python3 -m pytest          # testler
python main.py             # masaüstü arayüzü
```
