#!/usr/bin/env bash
# Jalankan aplikasi Pecut Lamaran Gmail (tanpa tunnel / tanpa pelacakan baca).
# Untuk pelacakan "dibaca", pakai ./jalan-tunnel.sh
# Shebang /usr/bin/env bash supaya jalan di Termux maupun Ubuntu.
set -e
cd "$(dirname "$0")" || exit 1

VENV_PY=".venv/bin/python"

# Bersihkan sisa proses app.py yang nyangkut (mis. dari sesi sebelumnya).
pkill -f "python app.py" 2>/dev/null && { echo "[run.sh] menutup sisa proses lama..."; sleep 1; } || true

# 1) Pastikan venv ada.
if [ ! -x "$VENV_PY" ]; then
  echo "[run.sh] .venv belum ada — membuat venv baru..."
  python3 -m venv .venv
fi

# 2) Pastikan dependensi terpasang.
if ! "$VENV_PY" -c "import flask, googleapiclient, google_auth_oauthlib" >/dev/null 2>&1; then
  echo "[run.sh] Dependensi belum lengkap — memasang dari requirements.txt..."
  "$VENV_PY" -m pip install --upgrade pip >/dev/null
  "$VENV_PY" -m pip install -r requirements.txt
fi

# 3) Jalankan.
PORT="${PECUT_PORT:-5000}"
echo "[run.sh] Menjalankan di http://127.0.0.1:$PORT"
exec "$VENV_PY" app.py
