#!/usr/bin/env bash
# Jalankan Pecut Lamaran Gmail + tunnel publik (cloudflared) supaya piksel
# pelacakan "dibaca" bisa diakses penerima email.
#
# Cara pakai:  ./jalan-tunnel.sh
# Hentikan   :  Ctrl+C  (tunnel ikut berhenti)
# Port bentrok: skrip ini otomatis membersihkan sisa proses sendiri,
#               atau memakai port lain kalau port sedang dipakai program lain.
set -e
cd "$(dirname "$0")" || exit 1

CF="${CLOUDFLARED_BIN:-$HOME/bin/cloudflared}"
PY="$(dirname "$0")/.venv/bin/python"
[ -x "$PY" ] || PY=python3

# Cek apakah sebuah port sedang dipakai.
port_busy() {
  "$PY" - "$1" <<'PYEOF'
import socket, sys
s = socket.socket()
s.settimeout(0.5)
try:
    s.connect(("127.0.0.1", int(sys.argv[1])))
    sys.exit(0)   # terpakai
except Exception:
    sys.exit(1)   # bebas
finally:
    s.close()
PYEOF
}

# Bersihkan sisa proses milik aplikasi ini (app.py + cloudflared) yang nyangkut.
# Sengaja spesifik agar tidak membunuh proses lain (mis. shell ini sendiri).
cleanup_own() {
  pkill -f "python app.py" 2>/dev/null || true
  pkill -f "cloudflared tunnel" 2>/dev/null || true
  sleep 1
}

PORT="${PECUT_PORT:-5000}"
ORIG_PORT="$PORT"

# 1) Kalau port terpakai, coba bersihkan sisa proses sendiri dulu.
if port_busy "$PORT"; then
  echo "[tunnel] port $PORT sedang dipakai — membersihkan sisa proses lama..."
  cleanup_own
  sleep 1
fi

# 2) Kalau masih terpakai (program lain), pilih port bebas otomatis.
if port_busy "$PORT"; then
  for p in 5001 5002 5050 8000 8080 8090 8888; do
    if ! port_busy "$p"; then PORT="$p"; break; fi
  done
  if [ "$PORT" != "$ORIG_PORT" ]; then
    echo "[tunnel] port $ORIG_PORT masih dipakai program lain — memakai port $PORT."
  fi
fi
if port_busy "$PORT"; then
  echo "[tunnel] GAGAL: semua port kandidat terpakai. Set PECUT_PORT=<port bebas> ./jalan-tunnel.sh"
  exit 1
fi

# Pastikan cloudflared ada.
if [ ! -x "$CF" ]; then
  echo "[tunnel] cloudflared belum ada — mengunduh..."
  mkdir -p "$(dirname "$CF")"
  curl -sL -o "$CF" \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64
  chmod +x "$CF"
fi

CFLOG="$(mktemp)"
echo "[tunnel] menyalakan tunnel ke http://127.0.0.1:$PORT ..."
"$CF" tunnel --protocol http2 --url "http://127.0.0.1:$PORT" >"$CFLOG" 2>&1 &
CF_PID=$!

cleanup() { kill "$CF_PID" 2>/dev/null || true; rm -f "$CFLOG"; }
trap cleanup EXIT INT TERM

# Tunggu URL publik muncul (maks ~40 detik).
URL=""
for _ in $(seq 1 40); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$CFLOG" | head -1 || true)
  [ -n "$URL" ] && break
  sleep 1
done

if [ -z "$URL" ]; then
  echo "[tunnel] GAGAL mendapat URL. Log:"; tail -20 "$CFLOG"; exit 1
fi
echo "[tunnel] URL publik: $URL"
export PECUT_PUBLIC_URL="$URL"

# Tunggu tunnel benar-benar tersambung.
for _ in $(seq 1 20); do
  grep -q "Registered tunnel connection" "$CFLOG" && break
  sleep 1
done

echo "[tunnel] pelacakan baca AKTIF. Buka http://127.0.0.1:$PORT"
echo "[tunnel] (Ctrl+C untuk berhenti)"
exec "$PY" app.py
