#!/usr/bin/env bash
# Hentikan aplikasi Pecut + tunnel (kalau nyangkut / mau bersih-bersih).
cd "$(dirname "$0")" || exit 1
pkill -f "python app.py" 2>/dev/null && echo "app dihentikan" || echo "app tidak jalan"
pkill -f "cloudflared tunnel" 2>/dev/null && echo "tunnel dihentikan" || echo "tunnel tidak jalan"
sleep 1
echo "selesai."
