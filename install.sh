#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$HOME/.mitra"
BIN_DIR="$HOME/.local/bin"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ─── Renkler ─────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
  CY='\033[96m'; GR='\033[92m'; RD='\033[91m'; DM='\033[2m'; RS='\033[0m'
else
  CY=''; GR=''; RD=''; DM=''; RS=''
fi

info() { printf "  ${CY}▶${RS}  %s\n" "$*"; }
ok()   { printf "  ${GR}✓${RS}  %s\n" "$*"; }
fail() { printf "  ${RD}✗${RS}  %s\n" "$*" >&2; exit 1; }

# ─── Banner ──────────────────────────────────────────────────────────────────
printf "${CY}"
cat << 'EOF'

  ███╗   ███╗██╗████████╗██████╗  █████╗
  ████╗ ████║██║╚══██╔══╝██╔══██╗██╔══██╗
  ██╔████╔██║██║   ██║   ██████╔╝███████║
  ██║╚██╔╝██║██║   ██║   ██╔══██╗██╔══██║
  ██║ ╚═╝ ██║██║   ██║   ██║  ██║██║  ██║
  ╚═╝     ╚═╝╚═╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝

EOF
printf "${RS}"
printf "  ${DM}Kurulum başlatılıyor…${RS}\n\n"

# ─── Python bul (3.12 ve altını tercih et — en kararlı) ──────────────────────
find_python() {
    for cmd in python3.12 python3.11 python3.10 python3.13 python3.14 python3; do
        if command -v "$cmd" &>/dev/null; then
            ok_ver=$("$cmd" -c "import sys; print(sys.version_info >= (3,10))" 2>/dev/null || true)
            if [ "$ok_ver" = "True" ]; then
                echo "$cmd"; return
            fi
        fi
    done
}

PYTHON=$(find_python)
[ -z "$PYTHON" ] && fail "Python 3.10+ bulunamadı.\n  macOS için: brew install python@3.12"
info "Python: $($PYTHON --version)"

# ─── Sanal ortam oluştur ─────────────────────────────────────────────────────
info "Sanal ortam oluşturuluyor: $INSTALL_DIR/venv"
rm -rf "$INSTALL_DIR/venv"
mkdir -p "$INSTALL_DIR"
"$PYTHON" -m venv "$INSTALL_DIR/venv"

# ─── Mitra kur ───────────────────────────────────────────────────────────────
info "Mitra ve bağımlılıklar yükleniyor…"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet "$REPO_DIR"

# ─── Global komut oluştur ────────────────────────────────────────────────────
mkdir -p "$BIN_DIR"
MITRA_BIN="$INSTALL_DIR/venv/bin/mitra"

cat > "$BIN_DIR/mitra" << WRAPPER
#!/usr/bin/env bash
exec "$MITRA_BIN" "\$@"
WRAPPER
chmod +x "$BIN_DIR/mitra"
ok "Komut oluşturuldu: $BIN_DIR/mitra"

# ─── PATH kontrolü ve güncelleme ─────────────────────────────────────────────
SHELL_RC=""
if [ -n "${ZSH_VERSION:-}" ] || [ "$(basename "$SHELL")" = "zsh" ]; then
    SHELL_RC="$HOME/.zshrc"
elif [ -n "${BASH_VERSION:-}" ] || [ "$(basename "$SHELL")" = "bash" ]; then
    SHELL_RC="$HOME/.bashrc"
fi

add_to_path() {
    if [ -n "$SHELL_RC" ] && ! grep -q 'local/bin' "$SHELL_RC" 2>/dev/null; then
        echo '' >> "$SHELL_RC"
        echo '# Mitra' >> "$SHELL_RC"
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_RC"
        ok "PATH güncellendi: $SHELL_RC"
    fi
}

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    add_to_path
    export PATH="$BIN_DIR:$PATH"
fi

# ─── Tamamlandı ──────────────────────────────────────────────────────────────
echo
printf "  ${GR}✓ Kurulum tamamlandı!${RS}\n\n"
printf "  İlk çalıştırmada Chromium (~170 MB) otomatik indirilir.\n\n"
printf "  Şimdi yeni bir terminal aç ve yaz:\n\n"
printf "    ${CY}mitra${RS}\n\n"
