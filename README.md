
# Pecut Lamaran Gmail — Termux/Ubuntu

Aplikasi Flask: 1 akun Gmail pengirim → banyak email perusahaan tujuan.

## Isi
- 1 akun Gmail sebagai pengirim (OAuth).
- Banyak email perusahaan sebagai tujuan di `daftar.csv`.
- Isi email sama untuk semua; subject/CV bisa berbeda per baris.
- CV/berkas boleh sama (default) atau berbeda per baris.
- Batas aplikasi: maksimal 500 baris per sekali proses.
- `sent_log.csv` menyimpan hasil kirim; `sent_log_dry.csv` untuk mode simulasi.

## Instalasi
Cara paling gampang — skrip ini otomatis membuat venv & memasang dependensi
kalau belum ada:

```bash
cd ~/pecut-lamaran-gmail
./run.sh
```

Kalau muncul `Permission denied`, beri izin sekali:
```bash
chmod +x run.sh
```

Manual (kalau perlu):
```bash
cd ~/pecut-lamaran-gmail
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

> Penting: jalankan lewat `./run.sh` (atau aktifkan venv dulu). Kalau
> menjalankan `python app.py` dengan Python sistem, akan muncul pesan
> "Gagal memuat dependensi" karena Flask hanya ada di dalam `.venv`.

Buka `http://127.0.0.1:5000`.

## Halaman

### 1. Daftar tujuan — tersinkron dengan web UI
`daftar.csv` adalah sumber tunggal. Halaman membacanya langsung tiap dibuka,
dan semua aksi di web menulis balik ke file itu:

| Aksi di web | Efek ke `daftar.csv` |
|---|---|
| Tambah baris | menambah satu baris di akhir |
| Hapus (tombol per baris) | menghapus baris tersebut |
| Edit textarea + Simpan | menimpa seluruh isi file |
| Impor file CSV | menimpa seluruh isi file |

### 2. Kirim sekarang
Tombol **KIRIM SEKARANG** memakai `daftar.csv` di disk (tanpa upload ulang).
Kolom Status di tabel menampilkan hasil terakhir per email dari `sent_log.csv`.

### 3. Jadwal kirim otomatis
Buat jadwal dengan waktu (format lokal WIB) + isi email. Jadwal disimpan di
`schedule.json` dan dijalankan oleh thread scheduler yang hidup selama
aplikasi berjalan (dicek tiap 5 detik). Status per jadwal:
`pending` → `running` → `done` / `failed`, bisa `cancelled` atau dihapus.
Jadwal memakai `daftar.csv` saat dijalankan, jadi daftar terbaru selalu dipakai.

> Jadwal hanya berjalan selama aplikasi hidup. Kalau HP/proses dimatikan,
> jadwal yang belum jatuh tempo akan jalan saat aplikasi dinyalakan lagi
> (selama waktunya sudah/sedang lewat). Untuk jadwal yang andal, jalankan
> aplikasi terus-menerus (mis. lewat `tmux`) atau pasang cron yang memanggil
> proses ini.

### 4. Cek balasan
Halaman `/replies` membaca kotak masuk Gmail: menampilkan pengirim, subject,
ringkasan, dan status **BELUM DIBACA / dibaca**, plus tanda `lamaran` untuk
pengirim yang ada di daftar tujuan. Tombol **Tandai dibaca** menghapus label
`UNREAD` pesan itu.

Agar cepat, metadata semua pesan diambil dalam **satu permintaan batch**
(bukan satu-per-satu), dan hasilnya di-cache singkat (lihat `REPLIES_TTL`,
default 60 detik). Kunjungan pertama ±1 detik; kunjungan berikutnya hampir
instan. Tombol **🔄 Ambil terbaru dari Gmail** memaksa muat ulang dari Gmail
sekarang.

Catatan: Gmail API **tidak** menyediakan "read receipt" (apakah penerima
membuka email kita). Yang bisa dipantau: pesan masuk sebagai balasan, dan
status dibaca/belum dibaca di kotak masuk kita sendiri.

## OAuth (dua izin terpisah)
Letakkan file OAuth Desktop Client dari Google Cloud sebagai `credentials.json`.

**Tidak perlu browser otomatis.** Buka halaman depan → menu **🔑 Izin Google**,
lalu tekan **Hubungkan**:

- **Kirim email** (scope `gmail.send`) → disimpan di `token.json`.
- **Baca kotak masuk** (scope `gmail.readonly` + `gmail.modify`) → disimpan di
  `token_read.json`.

Alurnya: kamu diklik → diarahkan ke halaman izin Google → setujui → Google
mengembalikan ke `http://127.0.0.1:5000/oauth/callback` → selesai. Karena
browser-nya adalah browser yang sedang kamu pakai (di HP), tidak ada
percobaan membuka browser otomatis yang biasanya gagal di Termux
(`could not locate runnable browser`).

Scope baca dipisah supaya kirim tetap bisa jalan walau izin baca belum diberikan.

### Kalau muncul `redirect_uri_mismatch`
Callback default: `http://127.0.0.1:5000/oauth/callback`. Untuk OAuth client
tipe **Desktop app**, Google mengizinkan loopback `127.0.0.1` tanpa perlu
mendaftarkan port. Kalau client kamu tipe lain, tambahkan URI itu di
Google Cloud Console → Credentials → OAuth client → Authorized redirect URIs.
Bisa juga diubah lewat env:
```bash
PECUT_REDIRECT_URI="http://127.0.0.1:5000/oauth/callback" ./run.sh
```

Jangan upload `credentials.json`, `token.json`, atau `token_read.json` ke GitHub.

## Mode simulasi (uji tanpa kirim asli)
Set `PECUT_DRY_RUN=1` sebelum menjalankan:

```bash
PECUT_DRY_RUN=1 python app.py
```

Semua "kirim" jadi simulasi: tidak menyentuh Gmail, tidak butuh OAuth, dan
hasilnya dicatat di `sent_log_dry.csv`. Halaman menampilkan spanduk peringatan
MODE SIMULASI.

## CSV
```csv
email,subject,cv
hrd@abc.com,Lamaran Operator Produksi,
hrd@xyz.com,Lamaran Admin,cv-admin.pdf
```

Jika `cv` kosong, aplikasi memakai CV default yang dipilih di halaman.
Nama file pada CSV harus sama dengan file di folder `uploads/`.

### Toleransi format
File CSV boleh datang dari mana saja (termasuk ekspor Excel/HP):

- Pemisah boleh koma `,`, titik-koma `;`, tab, atau `|` — dideteksi otomatis.
- Nama kolom tak peduli huruf besar/kecil (`Email`, `SUBJECT`, dst).
- BOM dan baris berakhiran CRLF (Windows/Android) ditangani.
- Encoding: UTF-8 atau Latin-1/Windows-1252.
- Nama file boleh `daftar.csv`, `Daftar.csv`, `DAFTAR.CSV` (tak peduli huruf).

Header wajib memuat kolom `email` dan `subject` (kolom `cv` opsional).
Kalau file tak terbaca, halaman menampilkan peringatan jelas — bukan error.

## Sinkronisasi daftar.csv
- Halaman **selalu** membaca ulang `daftar.csv` dari disk tiap kali dibuka.
- Header no-cache dipasang supaya browser HP tidak menyajikan versi lama.
  Kalau kamu mengedit file itu dari aplikasi lain, muat ulang halaman
  (link **🔄 Muat ulang**).
- Editor teks di halaman memakai penanda waktu. Kalau `daftar.csv` berubah
  sejak halaman dibuka (mis. diedit dari HP), tombol **Simpan** akan menolak
  dulu supaya edit eksternal tidak tertimpa. Muat ulang lalu simpan lagi.

> Di Android, mengedit `daftar.csv` langsung dari file manager sering tidak
> menemukan folder proyek (proot). Cara paling andal: pakai tombol
> **⬆ Timpa daftar** di halaman web, atau **📂 Ambil file** (lihat di bawah).

### Impor langsung dari folder HP (tanpa picker browser)
Kalau pemilih file di browser HP tidak bisa mengakses file (mis. file ada di
dalam storage yang tak terjangkau browser, atau filternya menyembunyikan
file), pakai kotak **Impor langsung dari folder HP**:

- Isi path absolut file CSV di HP, mis. `/sdcard/Download/daftar.csv`
  atau `/sdcard/Documents/daftar.csv`, lalu tekan **📂 Ambil file**.
- Aplikasi membaca file itu langsung dari penyimpanan HP (proot bisa melihat
  `/sdcard`), jadi tidak bergantung pada pemilih file browser.
- Demi keamanan, path dibatasi ke `/sdcard`, `/storage/emulated/0`,
  `/storage/self/primary`, dan folder proyek.

## Pelacakan "dibaca" (tracking pixel)

Email tidak punya laporan "penerima membuka" seperti WhatsApp. Satu-satunya cara
nyata adalah **tracking pixel**: gambar 1x1 tak terlihat yang disisipkan ke tiap
email. Saat penerima membuka email dan client-nya memuat gambar, server ini
mencatat kejadiannya.

Jalankan lewat skrip khusus (otomatis menyalakan tunnel publik):
```bash
./jalan-tunnel.sh
```
Skrip ini menyalakan cloudflared, mendapat URL publik, lalu menjalankan
aplikasi dengan `PECUT_PUBLIC_URL` diset. Tanpa URL publik, piksel tidak bisa
diakses penerima dan kolom **Baca** tidak akan terisi.

Hasilnya muncul di kolom **Baca** pada tabel: `🟡 dibuka? Nx` kalau piksel
pernah dimuat, `belum` kalau email terkirim tapi belum ada sinyal.

### Batasan penting (jujur)
- **Bukan bukti pasti.** Banyak email client memblokir gambar otomatis
  (Outlook kantor) → dibaca tapi tak tercatat. Sebaliknya, Gmail/Apple Mail
  kadang memuat gambar otomatis → tercatat padahal baru diproses mesin.
- **Hanya untuk email yang dikirim setelah fitur ini dipasang.** Email lama
  tak punya piksel, jadi tak bisa dilacak.
- **URL tunnel gratis berubah tiap restart** (`*.trycloudflare.com`), sehingga
  piksel di email lama jadi mati kalau tunnel dimatikan/di-restart. Untuk
  pemakaian serius, pakai named tunnel dengan domain tetap.
- Karena itu statusnya ditulis "kemungkinan dibuka", bukan "pasti dibaca".

Data pelacakan disimpan di `tracks.json` (id → email, waktu kirim, daftar waktu
piksel dimuat + user-agent).

## Menjalankan

| Perintah | Fungsi |
|---|---|
| `./run.sh` | Jalankan aplikasi saja (tanpa pelacakan baca) |
| `./jalan-tunnel.sh` | Jalankan + tunnel publik (pelacakan baca AKTIF) |
| `./stop.sh` | Hentikan aplikasi & tunnel (kalau nyangkut) |

Kalau muncul `Address already in use` / port 5000 dipakai program lain:
`jalan-tunnel.sh` sudah menanganinya sendiri — ia membersihkan sisa proses lama
milik aplikasi ini, dan kalau port masih terpakai program lain, otomatis pindah
ke port bebas berikutnya (5001, 5002, ...). Nomor port yang dipakai tertulis di
pesan pembuka. Untuk memaksa port tertentu:
```bash
PECUT_PORT=5050 ./jalan-tunnel.sh
```

## Tampilan (frontend)

Desain memakai sistem sendiri di `static/style.css` (vanilla CSS, tanpa framework):

- Palet: latar kertas hangat, aksen teal tunggal, tombol utama tinta gelap.
- Font: **Outfit** (judul & isi) + **JetBrains Mono** (angka/email), via Google Fonts
  dengan fallback sistem kalau offline.
- Ikon: satu set SVG (`templates/_icons.html`), stroke konsisten — dipakai via
  `<svg class="ic"><use href="#i-send"/></svg>`.
- Komponen: `.section`, `.stat`, `.badge`, `.btn`, `.notice`, `.table-wrap`,
  `.empty`, plus skip-link, focus ring, dan grain halus.

Template: `templates/index.html` (Kirim) dan `templates/replies.html` (Balasan),
keduanya meng-include `_icons.html` dan memuat `style.css`.

### Responsif (320px → desktop lebar)

Prinsipnya: **tidak ada scroll horizontal di level dokumen**. Yang lebar
(tabel) menggulir sendiri di dalam `.table-wrap`, sisanya menyusut.

- **Akar masalah yang dijaga:** anak grid/flex default `min-width: auto`, jadi
  `.section` di dalam `.stack` menolak menyusut lebih kecil dari tabel
  (dulu memaksa halaman jadi ~733px di HP). Aturan `.stack > * { min-width: 0 }`
  + `.section { min-width: 0 }` membuat `.table-wrap` yang menggulir, bukan halaman.
- **Tabel:** `.table-wrap` punya `overflow-x: auto`, momen inersia sentuh
  (`-webkit-overflow-scrolling: touch`), dan bayangan tepi CSS-only sebagai
  petunjuk bisa digeser. Token panjang (email, path) dibiarkan membungkus
  (`overflow-wrap: anywhere`) supaya tak menahan lebar minimum tabel.
- **Breakpoint:** `≤900px` baris teks penuh; `≤640px` rapatkan padding, judul,
  dan target sentuh (`.btn` ≥42px); `≤430px` topbar jadi dua baris dengan nav
  jadi dua tombol penuh; `≤340px` stat jadi satu kolom ringkas; `≥1600px`
  kontainer dibatasi 1240px.
- **Perangkat sentuh:** `@media (hover: none)` mematikan efek hover-saja dan
  menaikkan target sentuh (`.btn` ≥44px, `.btn--sm` ≥38px) — termasuk HP
  landscape dan tablet yang lebarnya di atas 640px.

Diverifikasi di browser sungguhan (Chrome, CDP) pada 320/360/390/430/431/480/
600/640/641/768/1024/1440/1920px untuk halaman Kirim dan Balasan: 0 overflow,
tabel menggulir di dalam, target sentuh ≥38px, tidak ada perubahan pada form/aksi.

## Catatan
Aplikasi tidak mencoba melewati batas/pembatasan Gmail. Angka 500 adalah
batas aplikasi yang kita pasang, bukan jaminan Google akan selalu
mengizinkan 500 pengiriman.
