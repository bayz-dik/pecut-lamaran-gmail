import base64
import csv
import io
import json
import mimetypes
import os
import re
import threading
import time
import uuid
from datetime import datetime
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path

try:
    from flask import Flask, flash, redirect, render_template, request, url_for
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ModuleNotFoundError as e:
    print("=" * 60)
    print(f"Gagal memuat dependensi: {e.name}")
    print("Dependensi proyek ini hanya terpasang di dalam .venv,")
    print("bukan di Python sistem.")
    print()
    print("Cara benar (paling gampang):")
    print("    ./run.sh")
    print()
    print("Atau manual:")
    print("    source .venv/bin/activate")
    print("    python app.py")
    print()
    print("Kalau .venv belum ada / rusak:")
    print("    python3 -m venv .venv")
    print("    .venv/bin/pip install -r requirements.txt")
    print("=" * 60)
    raise SystemExit(1)

BASE = Path(__file__).resolve().parent
UPLOADS = BASE / "uploads"
UPLOADS.mkdir(exist_ok=True)

def resolve_daftar():
    """Path daftar.csv. Toleran huruf besar/kecil (Android sering menyimpan
    'Daftar.csv'). Kembalikan path kanonik kalau tak ada yang cocok."""
    target = "daftar.csv"
    try:
        for p in BASE.iterdir():
            if p.is_file() and p.name.lower() == target:
                return p
    except OSError:
        pass
    return BASE / target


def daftar_sig():
    """Tanda tangan (mtime) daftar.csv untuk mendeteksi perubahan dari luar."""
    p = resolve_daftar()
    try:
        return str(p.stat().st_mtime_ns)
    except OSError:
        return ""


DAFTAR = resolve_daftar()
SENT_LOG = BASE / "sent_log.csv"
DRY_LOG = BASE / "sent_log_dry.csv"
SCHEDULE_FILE = BASE / "schedule.json"
TRACK_FILE = BASE / "tracks.json"
CLIENT_SECRET = BASE / "credentials.json"
TOKEN_FILE = BASE / "token.json"          # scope: kirim
TOKEN_READ_FILE = BASE / "token_read.json"  # scope: baca/ubah label
DAILY_LIMIT = 500

HEADER = ["email", "subject", "cv"]

# Kirim dan baca pakai token terpisah supaya kirim tetap jalan walau
# izin baca belum pernah diberikan.
SCOPES_SEND = ["https://www.googleapis.com/auth/gmail.send"]
SCOPES_READ = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

# Mode uji: tidak mengirim email asli. Aktifkan dengan PECUT_DRY_RUN=1.
DRY_RUN = os.environ.get("PECUT_DRY_RUN") == "1"

# Google kadang mengembalikan gabungan scope (mis. send + read) walau kita
# minta satu jenis saja. Tanpa ini, oauthlib melempar error "Scope has changed".
# Kita terima saja (scope yang tersimpan tetap aman, cuma lebih luas).
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

# Validasi email: satu @, domain berlabel titik, TLD >= 2 huruf.
# Menolak kesalahan umum seperti titik di akhir ("gmail.co.") atau TLD kosong.
EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$"
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-local-secret")


@app.after_request
def _no_cache(resp):
    # Halaman selalu dinamis (baca daftar.csv/schedule.json tiap kali).
    # Tanpa ini, browser HP sering menyajikan versi lama dari cache.
    if resp.mimetype == "text/html":
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp


# ============================================================== daftar.csv

def write_daftar(rows):
    with open(resolve_daftar(), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        for r in rows:
            w.writerow({k: (r.get(k) or "").strip() for k in HEADER})


def _read_csv_rows(raw):
    """Parse teks CSV jadi list dict {email,subject,cv}.

    Tahan BOM, CRLF, dan delimiter , ; tab atau | — format umum hasil ekspor
    Excel / aplikasi HP. Lempar ValueError kalau kolom wajib tak ditemukan.
    """
    raw = (raw or "").lstrip("\ufeff")
    if not raw.strip():
        return []
    first_line = raw.splitlines()[0] if raw.splitlines() else ""
    delim = ","
    for cand in [",", ";", "\t", "|"]:
        if cand in first_line:
            delim = cand
            break
    reader = csv.DictReader(io.StringIO(raw), delimiter=delim)
    fields = [(x or "").strip().lower() for x in (reader.fieldnames or [])]
    if "email" not in fields or "subject" not in fields:
        raise ValueError(
            "CSV wajib punya kolom 'email' dan 'subject'. "
            f"Kolom yang terbaca: {reader.fieldnames} (delimiter '{delim}')."
        )
    rows = []
    for row in reader:
        norm = {}
        for k, v in row.items():
            if k is None:
                # Kolom berlebih (mis. pemisah di akhir baris) masuk ke key None
                # sebagai list. Abaikan, jangan sampai bikin error.
                continue
            if isinstance(v, list):
                v = " ".join(str(x) for x in v if x)
            norm[str(k).strip().lower()] = (v or "").strip()
        email = norm.get("email", "")
        subject = norm.get("subject", "")
        cv = norm.get("cv", "")
        if not email and not subject and not cv:
            continue
        rows.append({"email": email, "subject": subject, "cv": cv})
    return rows


def read_daftar():
    path = resolve_daftar()
    if not path.exists():
        write_daftar([])
        return []
    raw = path.read_text(encoding="utf-8-sig")
    try:
        return _read_csv_rows(raw)
    except Exception:
        # File ada tapi formatnya tak dikenali: jangan bikin aplikasi error,
        # kembalikan kosong. Peringatan ditampilkan lewat daftar_problem().
        return []


def daftar_problem():
    """Pesan kalau daftar.csv ada isinya tapi tak bisa dibaca."""
    path = resolve_daftar()
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8-sig").strip()
    if not raw:
        return None
    try:
        _read_csv_rows(raw)
        return None
    except Exception as e:
        return str(e)


def parse_csv_text(raw):
    return _read_csv_rows(raw)


def validate_rows(rows):
    """Periksa semua baris; kalau ada yang salah, tampilkan semuanya sekaligus."""
    problems = []
    for i, row in enumerate(rows, 1):
        if not EMAIL_RE.match(row["email"]):
            problems.append(f"baris {i}: email tidak valid -> {row['email']!r}")
        elif not row["subject"]:
            problems.append(f"baris {i}: subject kosong untuk {row['email']}")
    if problems:
        shown = "; ".join(problems[:10])
        more = "" if len(problems) <= 10 else f" (+{len(problems) - 10} lagi)"
        raise ValueError(
            f"{len(problems)} baris bermasalah, tidak ada yang dikirim. "
            f"Perbaiki dulu: {shown}{more}"
        )
    return rows


def daftar_text(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=HEADER, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: (r.get(k) or "") for k in HEADER})
    return buf.getvalue()


# ================================================================ helpers

def _load_creds(token_path, scopes):
    """Ambil kredensial valid dari file token (refresh kalau kedaluwarsa)."""
    if not token_path.exists():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
    except Exception:
        return None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")
            return creds
        except Exception:
            return None
    return None


def _build_service(token_path, scopes, label="Gmail"):
    """Bangun service Gmail dari token yang sudah ada.

    TIDAK membuka browser otomatis (gagal di Termux/proot). Kalau izin belum
    ada, lempar error yang mengarahkan pengguna ke halaman /oauth.
    """
    if not CLIENT_SECRET.exists():
        raise RuntimeError("credentials.json belum ada di folder proyek.")
    creds = _load_creds(token_path, scopes)
    if creds is None:
        raise RuntimeError(
            f"Izin {label} belum ada. Buka menu 'Izin Google' di halaman depan "
            "untuk menghubungkan akun (tanpa perlu browser otomatis)."
        )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def gmail_send_service():
    return _build_service(TOKEN_FILE, SCOPES_SEND, "kirim email")


def gmail_read_service():
    return _build_service(TOKEN_READ_FILE, SCOPES_READ, "baca kotak masuk")


# ----------------------------------------------------- OAuth lewat web

# State OAuth yang sedang berjalan: state -> (flow, token_path)
OAUTH_FLOWS = {}
OAUTH_KINDS = {
    "send": {"scopes": SCOPES_SEND, "token": TOKEN_FILE, "label": "Kirim email"},
    "read": {"scopes": SCOPES_READ, "token": TOKEN_READ_FILE, "label": "Baca kotak masuk"},
}


def _redirect_uri():
    """URI callback OAuth. Bisa diatur lewat PECUT_REDIRECT_URI."""
    env = os.environ.get("PECUT_REDIRECT_URI")
    if env:
        return env
    return "http://127.0.0.1:5000/oauth/callback"


def oauth_status():
    """Status izin tiap jenis (sudah/belum)."""
    out = {}
    for kind, cfg in OAUTH_KINDS.items():
        out[kind] = {
            "label": cfg["label"],
            "connected": _load_creds(cfg["token"], cfg["scopes"]) is not None,
        }
    return out


def resolve_attachment(cv_name, default_name):
    name = (cv_name or "").strip() or (default_name or "").strip()
    if not name:
        return None
    candidate = (UPLOADS / Path(name).name).resolve()
    if candidate.parent != UPLOADS.resolve():
        raise ValueError("Nama file lampiran tidak valid.")
    if not candidate.exists() or not candidate.is_file():
        raise ValueError(f"Lampiran tidak ditemukan: {name}")
    return candidate


def _html_with_pixel(body, tid):
    """Ubah isi teks jadi HTML + sisipkan piksel pelacakan tak terlihat."""
    safe = (body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace("\n", "<br>\n"))
    base = public_base()
    img = ""
    if base and tid:
        img = (f'<img src="{base}/track/{tid}.png" width="1" height="1" '
               f'alt="" style="display:none;border:0" />')
    return (f"<html><body style=\"font-family:sans-serif;font-size:14px\">"
            f"<div>{safe}</div>{img}</body></html>")


def build_message(to, subject, body, attachment, tid=None):
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    # Versi teks (fallback) + versi HTML dengan piksel pelacakan.
    msg.set_content(body)
    msg.add_alternative(_html_with_pixel(body, tid), subtype="html")
    if attachment:
        data = attachment.read_bytes()
        ctype, _ = mimetypes.guess_type(str(attachment))
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype,
                           filename=attachment.name)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def send_one(service, to, subject, body, attachment, tid=None):
    encoded = build_message(to, subject, body, attachment, tid=tid)
    return service.users().messages().send(userId="me", body={"raw": encoded}).execute()


def existing_files():
    return sorted([p.name for p in UPLOADS.iterdir() if p.is_file()])


# =========================================================== tracking pixel

# Alamat publik server (dari tunnel) supaya penerima email bisa memuat piksel.
# Set lewat env PECUT_PUBLIC_URL, mis. https://xxx.trycloudflare.com
def public_base():
    return (os.environ.get("PECUT_PUBLIC_URL") or "").rstrip("/")


def _load_tracks():
    if not TRACK_FILE.exists():
        return {}
    try:
        return json.loads(TRACK_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_tracks(data):
    TRACK_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                          encoding="utf-8")


def new_track(email, subject):
    """Buat id pelacakan baru untuk satu email yang dikirim."""
    tid = uuid.uuid4().hex[:16]
    with _sched_lock:
        data = _load_tracks()
        data[tid] = {
            "email": email,
            "subject": subject,
            "sent_at": datetime.now().isoformat(timespec="seconds"),
            "opens": [],       # daftar waktu dibuka
        }
        _save_tracks(data)
    return tid


def record_open(tid, user_agent=""):
    """Catat satu kejadian 'piksel dimuat' (indikasi email dibuka)."""
    with _sched_lock:
        data = _load_tracks()
        rec = data.get(tid)
        if rec is None:
            return False
        rec.setdefault("opens", []).append({
            "at": datetime.now().isoformat(timespec="seconds"),
            "ua": user_agent[:200],
        })
        _save_tracks(data)
    return True


def track_status_by_email():
    """email -> info pelacakan terakhir (jumlah buka + waktu buka terakhir)."""
    out = {}
    for rec in _load_tracks().values():
        email = (rec.get("email") or "").strip().lower()
        opens = rec.get("opens") or []
        cur = out.get(email)
        info = {
            "opens": len(opens),
            "last": opens[-1]["at"] if opens else "",
        }
        if cur is None or info["opens"] >= cur["opens"]:
            out[email] = info
    return out


# Piksel transparan 1x1 (PNG), dibuat sekali.
_PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


def sent_status():
    status = {}
    if SENT_LOG.exists():
        with open(SENT_LOG, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                status[(row.get("email") or "").strip()] = (row.get("status") or "").strip()
    return status


def _append_log(path, results):
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if f.tell() == 0:
            w.writerow(["status", "email", "subject", "message_id_or_error"])
        w.writerows(results)


def friendly_error(e):
    """Ubah pesan error Gmail jadi penjelasan singkat yang bisa dimengerti."""
    s = str(e)
    low = s.lower()
    if "invalid to header" in low:
        return "Alamat email tujuan tidak valid (periksa salah ketik / titik ekstra)."
    if "invalid argument" in low and "from" in low:
        return "Alamat pengirim tidak valid."
    if "quota" in low or "rate" in low and "limit" in low:
        return "Kuota/batas pengiriman Gmail tercapai. Coba lagi nanti."
    if "insufficient" in low or "permission" in low or "403" in low:
        return "Izin ditolak oleh Google. Coba hubungkan ulang izin di menu Izin Google."
    if "invalid_grant" in low or "token" in low and "expired" in low:
        return "Izin kedaluwarsa. Hubungkan ulang di menu Izin Google."
    return s


def do_send(rows, body, default_cv, dry=False):
    """Kirim daftar (atau simulasikan kalau dry). Return list hasil."""
    rows = validate_rows(rows)
    if len(rows) > DAILY_LIMIT:
        rows = rows[:DAILY_LIMIT]

    service = None
    if not dry:
        service = gmail_send_service()

    results = []
    for i, row in enumerate(rows, 1):
        try:
            attachment = resolve_attachment(row["cv"], default_cv)
            if dry:
                results.append(("DRY", row["email"], row["subject"], f"simulasi-{uuid.uuid4().hex[:8]}"))
            else:
                # Buat id pelacakan; piksel disisipkan ke dalam email.
                tid = new_track(row["email"], row["subject"])
                resp = send_one(service, row["email"], row["subject"], body,
                                attachment, tid=tid)
                results.append(("OK", row["email"], row["subject"], resp.get("id", "")))
        except Exception as e:
            results.append(("GAGAL", row["email"], row["subject"], friendly_error(e)))
        if i < len(rows):
            time.sleep(1)

    _append_log(DRY_LOG if dry else SENT_LOG, results)
    return results


# ============================================================== scheduler

_sched_lock = threading.Lock()
_scheduler_started = False


def load_jobs():
    if not SCHEDULE_FILE.exists():
        return []
    try:
        return json.loads(SCHEDULE_FILE.read_text(encoding="utf-8")).get("jobs", [])
    except Exception:
        return []


def save_jobs(jobs):
    SCHEDULE_FILE.write_text(json.dumps({"jobs": jobs}, indent=2, ensure_ascii=False),
                             encoding="utf-8")


def _job_public(job):
    j = dict(job)
    j["when_display"] = job.get("when", "").replace("T", " ")
    return j


def _run_job(job):
    with _sched_lock:
        job["status"] = "running"
        job["started"] = datetime.now().isoformat(timespec="seconds")
        save_jobs(load_jobs_updated(job))
    try:
        rows = read_daftar()
        if not rows:
            raise RuntimeError("daftar.csv kosong saat jadwal dijalankan.")
        dry = job.get("dry_run", DRY_RUN)
        results = do_send(rows, job.get("body", ""), job.get("default_cv", ""), dry=dry)
        ok = sum(1 for x in results if x[0] in ("OK", "DRY"))
        fail = len(results) - ok
        job["status"] = "done"
        job["result"] = f"{ok} terkirim, {fail} gagal" + (" (simulasi)" if dry else "")
    except Exception as e:
        job["status"] = "failed"
        job["result"] = str(e)
    finally:
        job["finished"] = datetime.now().isoformat(timespec="seconds")
        with _sched_lock:
            save_jobs(load_jobs_updated(job))


def load_jobs_updated(job):
    """Ambil daftar terbaru lalu ganti/append job dengan id yang sama."""
    jobs = load_jobs()
    for i, j in enumerate(jobs):
        if j.get("id") == job.get("id"):
            jobs[i] = job
            return jobs
    jobs.append(job)
    return jobs


def scheduler_loop():
    while True:
        try:
            now = datetime.now()
            for job in load_jobs():
                if job.get("status") != "pending":
                    continue
                try:
                    when = datetime.fromisoformat(job["when"])
                except Exception:
                    with _sched_lock:
                        job["status"] = "failed"
                        job["result"] = "Waktu jadwal tidak valid."
                        save_jobs(load_jobs_updated(job))
                    continue
                if when <= now:
                    _run_job(job)
        except Exception:
            pass
        time.sleep(5)


def start_scheduler():
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True
    t = threading.Thread(target=scheduler_loop, daemon=True, name="pecut-scheduler")
    t.start()


# ================================================================ balasan

def parse_headers(msg):
    """msg = dict hasil messages.get(format=metadata). -> dict info ringkas."""
    headers = {}
    payload = msg.get("payload", {}) or {}
    for h in payload.get("headers", []) or []:
        headers[h.get("name", "").lower()] = h.get("value", "")
    from_raw = headers.get("from", "")
    _, from_email = parseaddr(from_raw)
    labels = msg.get("labelIds", []) or []
    return {
        "id": msg.get("id", ""),
        "thread_id": msg.get("threadId", ""),
        "from": from_raw,
        "from_email": from_email.lower(),
        "subject": headers.get("subject", ""),
        "date": headers.get("date", ""),
        "snippet": msg.get("snippet", ""),
        "unread": "UNREAD" in labels,
    }


_replies_cache = {"at": 0.0, "data": None}
REPLIES_TTL = 60  # detik


def fetch_replies(max_results=30, use_cache=True):
    """Ambil pesan masuk (inbox) sebagai kandidat balasan.

    Cepat karena: (1) metadata semua pesan diambil dalam SATU permintaan batch
    (bukan satu-per-satu), dan (2) hasilnya di-cache beberapa detik supaya
    membuka ulang halaman tak perlu memanggil Gmail lagi.
    """
    if use_cache and _replies_cache["data"] is not None:
        if time.time() - _replies_cache["at"] < REPLIES_TTL:
            return _replies_cache["data"]

    service = gmail_read_service()
    listing = service.users().messages().list(
        userId="me", q="in:inbox", maxResults=max_results
    ).execute()
    ids = [m["id"] for m in (listing.get("messages") or [])]

    # Ambil semua metadata dalam satu batch (jauh lebih cepat dari N panggilan).
    fetched = {}

    def _cb(rid, resp, err):
        if err is None and resp is not None:
            fetched[rid] = resp

    if ids:
        batch = service.new_batch_http_request()
        for mid in ids:
            req = service.users().messages().get(
                userId="me", id=mid, format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            )
            # request_id = id pesan, supaya hasil bisa dicocokkan kembali.
            batch.add(req, request_id=mid, callback=_cb)
        batch.execute()

    out = [parse_headers(fetched[mid]) for mid in ids if mid in fetched]

    # Bandingkan email tanpa peduli huruf besar/kecil.
    known = {r["email"].lower() for r in read_daftar()}
    known |= {e.lower() for e, s in sent_status().items() if s == "OK"}
    for r in out:
        r["known"] = r["from_email"] in known

    _replies_cache["at"] = time.time()
    _replies_cache["data"] = out
    return out


def mark_read(message_id):
    service = gmail_read_service()
    service.users().messages().modify(
        userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}
    ).execute()


# ================================================================= routes

@app.route("/", methods=["GET"])
def index():
    rows = read_daftar()
    status = sent_status()
    tracks = track_status_by_email()
    rows_view = [
        {**row, "no": i, "status": status.get(row["email"], ""),
         "track": tracks.get(row["email"].lower())}
        for i, row in enumerate(rows, 1)
    ]
    jobs = [_job_public(j) for j in load_jobs()]
    jobs.sort(key=lambda j: j.get("when", ""))
    sent_ok = sum(1 for r in rows_view if r["status"] == "OK")
    opened = sum(1 for r in rows_view if r.get("track") and r["track"]["opens"])
    return render_template(
        "index.html",
        rows=rows_view,
        rows_text=daftar_text(rows),
        total=len(rows),
        files=existing_files(),
        daily_limit=DAILY_LIMIT,
        jobs=jobs,
        now=datetime.now().strftime("%Y-%m-%dT%H:%M"),
        dry_run=DRY_RUN,
        daftar_problem=daftar_problem(),
        daftar_sig=daftar_sig(),
        oauth=oauth_status(),
        redirect_uri=_redirect_uri(),
        public_url=public_base(),
        sent_ok=sent_ok,
        opened=opened,
    )


# --------------------------------------------------- routes: OAuth lewat web

@app.route("/oauth/<kind>", methods=["GET"])
def oauth_start(kind):
    """Mulai alur izin Google. Pengguna diarahkan ke halaman izin Google."""
    cfg = OAUTH_KINDS.get(kind)
    if not cfg:
        flash("Jenis izin tidak dikenal.", "error")
        return redirect(url_for("index"))
    if not CLIENT_SECRET.exists():
        flash("credentials.json belum ada di folder proyek.", "error")
        return redirect(url_for("index"))
    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(CLIENT_SECRET), cfg["scopes"], redirect_uri=_redirect_uri()
        )
        auth_url, state = flow.authorization_url(
            access_type="offline", prompt="consent", include_granted_scopes="false"
        )
    except Exception as e:
        flash(f"Gagal membuat URL izin: {e}", "error")
        return redirect(url_for("index"))
    OAUTH_FLOWS[state] = (flow, cfg["token"])
    # Arahkan browser (yang sedang dipakai) ke halaman izin Google.
    return redirect(auth_url)


@app.route("/oauth/callback", methods=["GET"])
def oauth_callback():
    """Google mengembalikan ke sini setelah pengguna menyetujui izin."""
    error = request.args.get("error")
    if error:
        flash(f"Izin ditolak/dibatalkan: {error}", "error")
        return redirect(url_for("index"))
    state = request.args.get("state", "")
    code = request.args.get("code", "")
    entry = OAUTH_FLOWS.pop(state, None)
    if not entry or not code:
        flash("Sesi izin tidak ditemukan atau kedaluwarsa. Coba lagi.", "error")
        return redirect(url_for("index"))
    flow, token_path = entry
    try:
        flow.fetch_token(code=code)
        creds = flow.credentials
        token_path.write_text(creds.to_json(), encoding="utf-8")
        flash("Berhasil terhubung ke Google.", "ok")
    except Exception as e:
        flash(f"Gagal menyimpan izin: {e}", "error")
    return redirect(url_for("index"))


@app.route("/daftar/save", methods=["POST"])
def daftar_save():
    raw = request.form.get("daftar_text", "")
    form_sig = request.form.get("daftar_sig", "")
    # Kalau file berubah sejak halaman dibuka (mis. diedit dari HP), jangan
    # timpa — supaya edit eksternal tidak hilang tanpa disadari.
    if form_sig and form_sig != daftar_sig():
        flash("daftar.csv sudah berubah sejak halaman ini dibuka (mungkin "
              "diedit dari HP atau tab lain). Muat ulang halaman dulu, "
              "lalu simpan lagi.", "error")
        return redirect(url_for("index"))
    try:
        rows = parse_csv_text(raw)
        write_daftar(rows)
        flash(f"daftar.csv disimpan ({len(rows)} baris).", "ok")
    except Exception as e:
        flash(f"Gagal simpan: {e}", "error")
    return redirect(url_for("index"))


@app.route("/daftar/add", methods=["POST"])
def daftar_add():
    email = (request.form.get("email") or "").strip()
    subject = (request.form.get("subject") or "").strip()
    cv = (request.form.get("cv") or "").strip()
    if not EMAIL_RE.match(email):
        flash(f"Email tidak valid: {email!r}", "error")
        return redirect(url_for("index"))
    if not subject:
        flash("Subject tidak boleh kosong.", "error")
        return redirect(url_for("index"))
    rows = read_daftar()
    rows.append({"email": email, "subject": subject, "cv": cv})
    write_daftar(rows)
    flash(f"Ditambahkan: {email}", "ok")
    return redirect(url_for("index"))


@app.route("/daftar/delete", methods=["POST"])
def daftar_delete():
    try:
        no = int(request.form.get("no", "0"))
    except ValueError:
        no = 0
    rows = read_daftar()
    if 1 <= no <= len(rows):
        removed = rows.pop(no - 1)
        write_daftar(rows)
        flash(f"Dihapus: {removed['email']}", "ok")
    else:
        flash("Baris tidak ditemukan.", "error")
    return redirect(url_for("index"))


def _import_csv_text(raw, source_label):
    """Parse teks CSV lalu timpa daftar.csv. Kembalikan (jumlah, contoh)."""
    rows = parse_csv_text(raw)
    if not rows:
        raise ValueError("tidak ada baris data (perlu kolom email dan subject "
                         "serta minimal satu baris)")
    write_daftar(rows)
    return len(rows), rows[0]["email"]


def _decode_bytes(data):
    """Decode byte CSV: coba UTF-8 (dengan BOM), lalu Latin-1."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


@app.route("/daftar/upload", methods=["POST"])
def daftar_upload():
    csv_file = request.files.get("csv_file")
    if not csv_file or not csv_file.filename:
        flash("Pilih file CSV dulu, lalu tekan Timpa daftar.", "error")
        return redirect(url_for("index"))
    try:
        raw = _decode_bytes(csv_file.read())
        n, contoh = _import_csv_text(raw, csv_file.filename)
        flash(f"daftar.csv diganti dari file: {n} baris (contoh: {contoh}).", "ok")
    except Exception as e:
        flash(f"Gagal impor: {e}", "error")
    return redirect(url_for("index"))


# Folder HP yang boleh dibaca untuk impor langsung (tanpa lewat picker browser).
IMPORT_ROOTS = ["/sdcard", "/storage/emulated/0", "/storage/self/primary"]


@app.route("/daftar/import-path", methods=["POST"])
def daftar_import_path():
    """Impor daftar.csv langsung dari path di HP (mis. /sdcard/Download/daftar.csv).

    Berguna kalau picker file di browser HP tidak bisa mengakses file.
    """
    path = (request.form.get("path") or "").strip().strip('"').strip("'")
    if not path:
        flash("Isi path file CSV dulu.", "error")
        return redirect(url_for("index"))
    p = Path(path).expanduser()
    try:
        real = p.resolve()
    except Exception:
        real = p
    if not real.is_absolute():
        flash("Path harus absolut, contoh: /sdcard/Download/daftar.csv", "error")
        return redirect(url_for("index"))
    allowed = any(str(real).startswith(r) for r in IMPORT_ROOTS) or real.parent == BASE
    if not allowed:
        flash(f"Demi keamanan, path harus di dalam {', '.join(IMPORT_ROOTS)} "
              "atau folder proyek.", "error")
        return redirect(url_for("index"))
    if not real.exists() or not real.is_file():
        flash(f"File tidak ditemukan: {real}", "error")
        return redirect(url_for("index"))
    try:
        raw = _decode_bytes(real.read_bytes())
        n, contoh = _import_csv_text(raw, real.name)
        flash(f"daftar.csv diganti dari {real}: {n} baris (contoh: {contoh}).", "ok")
    except Exception as e:
        flash(f"Gagal impor dari {real}: {e}", "error")
    return redirect(url_for("index"))


@app.route("/upload-files", methods=["POST"])
def upload_files():
    files = request.files.getlist("files")
    saved = 0
    for f in files:
        if not f or not f.filename:
            continue
        safe = Path(f.filename).name
        if safe in {"credentials.json", "token.json", "token_read.json"}:
            continue
        f.save(UPLOADS / safe)
        saved += 1
    flash(f"{saved} file berhasil disimpan ke uploads/.", "ok")
    return redirect(url_for("index"))


@app.route("/send", methods=["POST"])
def send():
    body = request.form.get("body", "").strip()
    default_cv = request.form.get("default_cv", "").strip()
    if not body:
        flash("Isi email belum diisi.", "error")
        return redirect(url_for("index"))
    # Kalau izin kirim belum ada, langsung arahkan ke halaman izin Google.
    if not DRY_RUN and not oauth_status()["send"]["connected"]:
        flash("Izin kirim email belum ada. Kamu akan diarahkan untuk "
              "menghubungkan akun Google dulu.", "error")
        return redirect(url_for("oauth_start", kind="send"))
    try:
        rows = read_daftar()
        if not rows:
            flash("daftar.csv masih kosong. Tambah tujuan dulu.", "error")
            return redirect(url_for("index"))
        results = do_send(rows, body, default_cv, dry=DRY_RUN)
        ok = sum(1 for x in results if x[0] in ("OK", "DRY"))
        fail = len(results) - ok
        tag = " (SIMULASI, tidak dikirim)" if DRY_RUN else ""
        flash(f"Selesai: {ok} terkirim, {fail} gagal{tag}.", "ok")
    except Exception as e:
        flash(str(e), "error")
    return redirect(url_for("index"))


@app.route("/schedule/add", methods=["POST"])
def schedule_add():
    when_raw = (request.form.get("when") or "").strip()
    body = request.form.get("body", "").strip()
    default_cv = request.form.get("default_cv", "").strip()
    if not when_raw:
        flash("Waktu jadwal belum diisi.", "error")
        return redirect(url_for("index"))
    if not body:
        flash("Isi email untuk jadwal belum diisi.", "error")
        return redirect(url_for("index"))
    try:
        when = datetime.fromisoformat(when_raw)
    except ValueError:
        flash("Format waktu tidak valid.", "error")
        return redirect(url_for("index"))
    if when <= datetime.now():
        flash("Waktu jadwal harus di masa depan.", "error")
        return redirect(url_for("index"))

    job = {
        "id": uuid.uuid4().hex[:12],
        "when": when.isoformat(timespec="seconds"),
        "body": body,
        "default_cv": default_cv,
        "status": "pending",
        "created": datetime.now().isoformat(timespec="seconds"),
        "result": "",
        "dry_run": DRY_RUN,
    }
    with _sched_lock:
        jobs = load_jobs()
        jobs.append(job)
        save_jobs(jobs)
    flash(f"Jadwal dibuat: {when.strftime('%Y-%m-%d %H:%M')}"
          + (" (SIMULASI)" if DRY_RUN else ""), "ok")
    return redirect(url_for("index"))


@app.route("/schedule/cancel", methods=["POST"])
def schedule_cancel():
    jid = request.form.get("id", "")
    with _sched_lock:
        jobs = load_jobs()
        for j in jobs:
            if j.get("id") == jid and j.get("status") == "pending":
                j["status"] = "cancelled"
                j["result"] = "dibatalkan"
        save_jobs(jobs)
    flash("Jadwal dibatalkan.", "ok")
    return redirect(url_for("index"))


@app.route("/schedule/delete", methods=["POST"])
def schedule_delete():
    jid = request.form.get("id", "")
    with _sched_lock:
        jobs = [j for j in load_jobs() if j.get("id") != jid]
        save_jobs(jobs)
    flash("Jadwal dihapus.", "ok")
    return redirect(url_for("index"))


@app.route("/track/<tid>.png", methods=["GET"])
def track_pixel(tid):
    """Piksel 1x1. Dimuat saat penerima membuka email → dicatat sebagai indikasi dibuka."""
    record_open(tid, request.headers.get("User-Agent", ""))
    resp = app.response_class(_PIXEL, mimetype="image/png")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


@app.route("/replies", methods=["GET"])
def replies():
    data = []
    error = None
    refresh = request.args.get("refresh") == "1"
    try:
        data = fetch_replies(use_cache=not refresh)
    except HttpError as e:
        if e.resp.status in (401, 403):
            error = ("Izin baca belum aktif atau kedaluwarsa. Buka halaman depan "
                     "→ menu 'Izin Google' → Hubungkan 'Baca kotak masuk', lalu "
                     "muat ulang halaman ini.")
        else:
            error = f"Gagal ambil balasan: {e}"
    except Exception as e:
        error = str(e)
    return render_template("replies.html", replies=data, error=error,
                           oauth=oauth_status(), refresh=refresh,
                           ttl=REPLIES_TTL)


@app.route("/replies/read", methods=["POST"])
def replies_read():
    mid = request.form.get("id", "")
    try:
        mark_read(mid)
        _replies_cache["data"] = None  # paksa muat ulang agar status terbaru
        flash("Pesan ditandai sudah dibaca.", "ok")
    except Exception as e:
        flash(f"Gagal menandai dibaca: {e}", "error")
    return redirect(url_for("replies"))


start_scheduler()

if __name__ == "__main__":
    port = int(os.environ.get("PECUT_PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=False)
