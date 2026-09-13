#!/usr/bin/env python3
"""Generator banner pixel animasi untuk README Pecut Lamaran Gmail.

Kenapa digenerate, bukan ditulis tangan: wordmark pixel butuh ratusan <rect>
yang posisinya harus presisi. Font 5x7 di bawah ini sumber kebenarannya, jadi
mengubah ukuran atau teks cukup ubah satu variabel.

Jalankan:  python3 assets/_gen_banner.py  ->  assets/banner.svg
"""
from pathlib import Path

# --- font pixel 5x7 (1 = pixel menyala) -------------------------------------
FONT = {
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
}

# --- amplop pixel 12x8 (garis luar + lipatan V) -----------------------------
ENVELOPE = [
    "111111111111",
    "110000000011",
    "101000000101",
    "100100001001",
    "100010010001",
    "100001100001",
    "100000000001",
    "111111111111",
]

INK, TEAL, MUTED, PANEL, LINE = "#1b1a17", "#0f6d6a", "#8c867b", "#f3f1ec", "#e7e1d7"

W, H = 900, 210
S = 13            # ukuran 1 pixel wordmark
GAP = S           # jarak antar huruf
X0, Y0 = 56, 58   # pojok kiri-atas wordmark

EW = 12           # ukuran 1 pixel amplop
EX, EY = 520, 54

DOT = 9           # ukuran titik yang terbang
DOT_Y = EY + 4 * EW - DOT // 2   # sejajar tengah amplop
DOT_X = EX + 12 * EW + 22


def rects(grid, x0, y0, s):
    out = []
    for r, row in enumerate(grid):
        for c, ch in enumerate(row):
            if ch == "1":
                out.append(
                    f'<rect x="{x0 + c * s}" y="{y0 + r * s}" width="{s}" height="{s}"/>'
                )
    return "\n      ".join(out)


def main():
    letters = []
    x = X0
    for i, ch in enumerate("PECUT", start=1):
        letters.append(f'    <g class="l l{i}">\n      {rects(FONT[ch], x, Y0, S)}\n    </g>')
        x += 5 * S + GAP
    wordmark = "\n".join(letters)

    dots = "\n".join(
        f'    <rect class="dot d{i + 1}" x="{DOT_X}" y="{DOT_Y}" '
        f'width="{DOT}" height="{DOT}"/>'
        for i in range(4)
    )

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="Pecut Lamaran Gmail">
  <title>Pecut Lamaran Gmail</title>
  <style>
    /* Pixel art, bukan foto: tajam di semua ukuran dan cocok untuk tool CLI.
       Tiap gerak punya alasan, tidak ada animasi hiasan:
       - gelombang teal menyapu wordmark, menandai nama produk sebagai fokus;
       - amplop naik-turun, menandai proses "sedang mengirim";
       - titik berbaris terbang keluar dari amplop, mewakili email yang terkirim.
       Warna diambil dari aplikasi (tinta, teal, kertas) supaya satu identitas. */
    .panel {{ fill: {PANEL}; stroke: {LINE}; stroke-width: 1.5; }}
    /* Animasi WAJIB dipasang ke elemen rect, bukan ke grup huruf: tiap rect
       punya aturan .l rect {{ fill: INK }} sendiri, dan nilai langsung pada
       elemen mengalahkan fill warisan dari grup. Kalau dipasang di grup,
       sapuan teal tidak pernah terlihat (grup jadi teal, rect tetap tinta). */
    .l rect {{ fill: {INK}; }}
    .l1 rect {{ animation: sweep 2.8s ease-in-out infinite 0s; }}
    .l2 rect {{ animation: sweep 2.8s ease-in-out infinite .18s; }}
    .l3 rect {{ animation: sweep 2.8s ease-in-out infinite .36s; }}
    .l4 rect {{ animation: sweep 2.8s ease-in-out infinite .54s; }}
    .l5 rect {{ animation: sweep 2.8s ease-in-out infinite .72s; }}
    @keyframes sweep {{
      0%, 100% {{ fill: {INK}; }}
      38%      {{ fill: {TEAL}; }}
      62%      {{ fill: {TEAL}; }}
    }}
    .env rect {{ fill: {INK}; }}
    .env {{ animation: bob 3.2s ease-in-out infinite; }}
    @keyframes bob {{ 0%, 100% {{ transform: translateY(0); }} 50% {{ transform: translateY(-8px); }} }}
    .dot {{ fill: {TEAL}; animation: fly 2.4s ease-out infinite; }}
    .d1 {{ animation-delay: 0s; }}
    .d2 {{ animation-delay: .42s; }}
    .d3 {{ animation-delay: .84s; }}
    .d4 {{ animation-delay: 1.26s; }}
    @keyframes fly {{
      0%   {{ transform: translate(0, 0); opacity: 0; }}
      18%  {{ opacity: 1; }}
      72%  {{ opacity: 1; }}
      100% {{ transform: translate(148px, -10px); opacity: 0; }}
    }}
    .sub {{ font: 600 15px ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
            letter-spacing: 4.2px; fill: {MUTED}; }}
    @media (prefers-reduced-motion: reduce) {{
      .l1 rect, .l2 rect, .l3 rect, .l4 rect, .l5 rect, .env, .dot {{ animation: none; }}
    }}
  </style>
  <rect class="panel" x="0.75" y="0.75" width="{W - 1.5}" height="{H - 1.5}" rx="20"/>
  <g class="word">
{wordmark}
  </g>
  <g class="env">
      {rects(ENVELOPE, EX, EY, EW)}
  </g>
{dots}
  <text class="sub" x="{X0}" y="180">LAMARAN GMAIL</text>
</svg>
'''
    out = Path(__file__).with_name("banner.svg")
    out.write_text(svg, encoding="utf-8")
    print(f"tulis {out} ({len(svg)} byte)")


if __name__ == "__main__":
    main()
