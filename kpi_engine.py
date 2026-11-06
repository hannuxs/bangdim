"""
Mesin KPI closing harian (tanpa UI).

Konsep
------
* SALDO AWAL (baseline) = posisi WK / MTD / QTD / YTD pada tanggal tertentu
  (default: closing 05-11-2026 dari AAAA.txt).
* Setiap closing harian disimpan sebagai 1 record per tanggal di data/kpi_db.json.
* Angka periode SELALU dihitung ulang = saldo awal (jika periodenya sama)
  + jumlah record harian setelah tanggal saldo awal.  Jadi closing ulang
  tanggal yang sama MENIMPA (tidak dobel), dan koreksi tanggal lama otomatis
  ikut memperbaiki total sesudahnya.
* Reset otomatis:  WK = minggu ISO (Senin-Minggu), MTD = tiap tanggal 1,
  QTD = Jan-Mar / Apr-Jun / Jul-Sep / Okt-Des, YTD = tiap 1 Januari.
"""
from __future__ import annotations

import calendar
import copy
import csv
import datetime as dt
import json
import os
import shutil
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent
MAX_BACKUPS = 90


def set_data_dir(path: str | Path) -> None:
    """Semua file data (database, backup, laporan, upload, log) ada di folder ini."""
    global DATA_DIR, DB_PATH, DRAFT_PATH, BACKUP_DIR, REPORT_DIR, UPLOAD_DIR
    global HISTORY_CSV, LOG_PATH
    DATA_DIR = Path(path).resolve()
    DB_PATH = DATA_DIR / "kpi_db.json"
    DRAFT_PATH = DATA_DIR / "draft.json"
    BACKUP_DIR = DATA_DIR / "backup"
    REPORT_DIR = DATA_DIR / "laporan"
    UPLOAD_DIR = DATA_DIR / "uploads"
    HISTORY_CSV = DATA_DIR / "riwayat_closing.csv"
    LOG_PATH = DATA_DIR / "log_aktivitas.jsonl"


set_data_dir(os.environ.get("KPI_DATA_DIR") or APP_DIR / "data")

PERIODS = ("wk", "mtd", "qtd", "ytd")
CATS = ("FW", "Textile", "ACC")
LY_MODES = {
    "calendar": "Tanggal sama tahun lalu (06-11-2026 vs 06-11-2025)",
    "weekday": "Hari sama tahun lalu / 364 hari (Jumat vs Jumat)",
}


# ------------------------------------------------------------------ util
def rnd(x: float | int | None) -> int:
    """Pembulatan normal (0,5 ke atas), bukan pembulatan bankir."""
    if x is None:
        return 0
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def s2d(s: str | dt.date) -> dt.date:
    return s if isinstance(s, dt.date) else dt.date.fromisoformat(str(s)[:10])


def d2s(d: dt.date) -> str:
    return d.isoformat()


def fmt_date(d: dt.date | str) -> str:
    return s2d(d).strftime("%d-%m-%Y")


def now_str() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def rp(n: float | int) -> str:
    """134630000 -> '134.630.000'"""
    v = rnd(n)
    return ("-" if v < 0 else "") + f"{abs(v):,}".replace(",", ".")


def signed(n: float | int) -> str:
    v = rnd(n)
    return ("+" if v >= 0 else "-") + rp(abs(v))


def pct_change(a: float, b: float) -> int | None:
    if not b:
        return None
    return rnd((a / b - 1) * 100)


def pct_gap(a: float, b: float, empty: str = "n/a") -> str:
    """'+57% / +76.878.700'  (a dibanding b)"""
    p = pct_change(a, b)
    if p is None:
        return empty
    return f"{p:+d}% / {signed(a - b)}"


def parse_amount(text: Any) -> int | None:
    """Terima '134.630.000', '134,630,000', '134630000', 'Rp 1.2' dsb."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return rnd(text)
    s = str(text).strip().replace("Rp", "").replace("rp", "").replace(" ", "")
    if not s:
        return None
    neg = s.startswith("-")
    s = s.lstrip("+-")
    if "," in s and "." in s:
        # format campuran: separator terakhir = desimal
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif s.count(".") > 1 or (s.count(".") == 1 and len(s.split(".")[1]) == 3):
        s = s.replace(".", "")
    elif s.count(",") > 1 or (s.count(",") == 1 and len(s.split(",")[1]) == 3):
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    return rnd(-v if neg else v)


def largest_remainder_pct(values: dict[str, float]) -> dict[str, int]:
    """Persen bulat yang jumlahnya pasti 100."""
    tot = sum(max(v, 0) for v in values.values())
    if tot <= 0:
        return {k: 0 for k in values}
    raw = {k: max(v, 0) / tot * 100 for k, v in values.items()}
    base = {k: int(v) for k, v in raw.items()}
    rest = 100 - sum(base.values())
    for k in sorted(raw, key=lambda k: raw[k] - base[k], reverse=True)[:rest]:
        base[k] += 1
    return base


# ------------------------------------------------------------------ periode
def period_key(p: str, d: dt.date) -> str:
    if p == "wk":
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    if p == "mtd":
        return f"{d.year}-{d.month:02d}"
    if p == "qtd":
        return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
    return f"{d.year}"


def period_start(p: str, d: dt.date) -> dt.date:
    if p == "wk":
        return d - dt.timedelta(days=d.weekday())
    if p == "mtd":
        return d.replace(day=1)
    if p == "qtd":
        return dt.date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)
    return dt.date(d.year, 1, 1)


def period_label(p: str, d: dt.date) -> str:
    if p == "wk":
        return f"WK {d.isocalendar()[1]}"
    if p == "qtd":
        return f"QTD {(d.month - 1) // 3 + 1}"
    return p.upper()


def daterange(a: dt.date, b: dt.date):
    d = a
    while d <= b:
        yield d
        d += dt.timedelta(days=1)


def ly_date(d: dt.date, mode: str) -> dt.date | None:
    if mode == "weekday":
        return d - dt.timedelta(days=364)
    try:
        return d.replace(year=d.year - 1)
    except ValueError:  # 29 Feb
        return None


def lm_date(d: dt.date) -> dt.date | None:
    prev_last = d.replace(day=1) - dt.timedelta(days=1)
    if d.day > calendar.monthrange(prev_last.year, prev_last.month)[1]:
        return None
    return prev_last.replace(day=d.day)


# ------------------------------------------------------------------ seed
def seed_db() -> dict:
    """Saldo awal dari laporan KPI 05-11-2026 (AAAA.txt)."""
    return {
        "schema": 1,
        "created_at": now_str(),
        "settings": {"store": "MKG", "ly_mode": "calendar"},
        "baseline": {
            "date": "2026-11-05",
            "note": "Saldo awal dari laporan KPI 05-11-2026 (AAAA.txt)",
            "wk": {"target": 483_671_000, "sales": 578_034_540, "ly": 631_405_000},
            "mtd": {"target": 723_015_000, "sales": 822_632_140, "ly": 946_933_700,
                    "lm": 895_035_808},
            "qtd": {"target": 5_472_029_000, "sales": 5_360_413_392, "ly": 5_909_377_300},
            "ytd": {"target": 48_942_678_000, "sales": 50_068_622_473,
                    "ly": 47_981_809_458},
        },
        "days": {
            "2026-11-05": {
                "target": 134_630_000, "sales": 211_508_700, "traffic": 760, "trx": 83,
                "qty": 164, "fw_unit": 90, "crep_unit": 10,
                "cat_amt": {}, "cat_pct": {"FW": 80, "Textile": 14, "ACC": 6},
                "ly_manual": 105_979_300, "lm_day": None, "lm_mtd_manual": None,
                "sources": [{"kind": "saldo_awal", "name": "AAAA.txt"}],
                "saved_at": now_str(), "is_baseline": True,
            }
        },
        "ly_daily": {},
    }


def new_day_record() -> dict:
    return {
        "target": 0, "sales": 0, "traffic": 0, "trx": 0, "qty": 0,
        "fw_unit": 0, "crep_unit": 0, "cat_amt": {c: 0 for c in CATS},
        "ly_manual": None, "lm_day": None, "lm_mtd_manual": None,
        "sources": [], "saved_at": None,
    }


# ------------------------------------------------------------------ IO
def _ensure_dirs() -> None:
    for p in (DATA_DIR, BACKUP_DIR, REPORT_DIR, UPLOAD_DIR):
        p.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, obj: Any) -> None:
    _ensure_dirs()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_db() -> dict:
    _ensure_dirs()
    if not DB_PATH.exists():
        db = seed_db()
        _atomic_write_json(DB_PATH, db)
        log_event("INIT", None, {"keterangan": "Database dibuat dari saldo awal AAAA.txt"})
        return db
    with open(DB_PATH, encoding="utf-8") as f:
        db = json.load(f)
    db.setdefault("settings", {}).setdefault("store", "MKG")
    db["settings"].setdefault("ly_mode", "calendar")
    db.setdefault("days", {})
    db.setdefault("ly_daily", {})
    return db


def backup_db(tag: str = "") -> Path | None:
    if not DB_PATH.exists():
        return None
    _ensure_dirs()
    name = f"kpi_db_{dt.datetime.now():%Y%m%d_%H%M%S}{'_' + tag if tag else ''}.json"
    dst = BACKUP_DIR / name
    shutil.copy2(DB_PATH, dst)
    olds = sorted(BACKUP_DIR.glob("kpi_db_*.json"))
    for p in olds[:-MAX_BACKUPS]:
        p.unlink(missing_ok=True)
    return dst


def write_db(db: dict, tag: str = "") -> None:
    backup_db(tag)
    db["updated_at"] = now_str()
    _atomic_write_json(DB_PATH, db)
    try:
        export_history_csv(db)
    except Exception:  # riwayat CSV hanya turunan, jangan gagalkan simpan
        pass


def log_event(action: str, date: str | None, detail: dict) -> None:
    _ensure_dirs()
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps({"waktu": now_str(), "aksi": action, "tanggal": date,
                            "detail": detail}, ensure_ascii=False) + "\n")


def read_log() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    out = []
    with open(LOG_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def load_draft() -> dict:
    if DRAFT_PATH.exists():
        try:
            with open(DRAFT_PATH, encoding="utf-8") as f:
                d = json.load(f)
            d.setdefault("files", [])
            d.setdefault("manual", {})
            return d
        except Exception:
            pass
    return {"files": [], "manual": {}}


def save_draft(draft: dict) -> None:
    _atomic_write_json(DRAFT_PATH, draft)


# ------------------------------------------------------------------ lookup
def baseline_date(db: dict) -> dt.date | None:
    b = db.get("baseline") or {}
    return s2d(b["date"]) if b.get("date") else None


def ly_lookup(db: dict, d: dt.date) -> tuple[int | None, dt.date | None, str]:
    """Sales LY untuk tanggal TY d -> (nilai, tanggal LY, sumber)."""
    ld = ly_date(d, db["settings"].get("ly_mode", "calendar"))
    if ld is None:
        return None, None, "tidak ada tanggal pembanding (29 Feb)"
    k = d2s(ld)
    if k in db.get("ly_daily", {}):
        return int(db["ly_daily"][k]["sales"]), ld, "data LY"
    rec = db.get("days", {}).get(k)
    if rec and rec.get("sales"):
        return int(rec["sales"]), ld, "riwayat closing"
    return None, ld, "belum ada data LY"


def ly_for(db: dict, d: dt.date, rec: dict | None) -> int | None:
    if rec and rec.get("ly_manual") is not None:
        return int(rec["ly_manual"])
    return ly_lookup(db, d)[0]


def lm_lookup(db: dict, d: dt.date) -> tuple[int | None, dt.date | None]:
    ld = lm_date(d)
    if ld is None:
        return 0, None  # bulan lalu tidak punya tanggal ini
    rec = db.get("days", {}).get(d2s(ld))
    if rec and rec.get("sales") is not None:
        return int(rec["sales"]), ld
    return None, ld


def lm_for(db: dict, d: dt.date, rec: dict | None) -> int | None:
    if rec and rec.get("lm_day") is not None:
        return int(rec["lm_day"])
    return lm_lookup(db, d)[0]


# ------------------------------------------------------------------ hitung
def compute(db: dict, date: dt.date | str, draft: dict | None = None) -> dict:
    """Hitung semua KPI untuk tanggal `date`.

    draft = record hari itu yang BELUM disimpan (untuk preview)."""
    D = s2d(date)
    days = dict(db.get("days", {}))
    if draft is not None:
        days[d2s(D)] = draft
    view = dict(db, days=days)
    B = baseline_date(db)
    base = db.get("baseline") or {}
    if B and D < B:
        raise ValueError(f"Tanggal {fmt_date(D)} sebelum saldo awal ({fmt_date(B)}).")

    rec = days.get(d2s(D))
    warnings: list[str] = []
    if rec is None:
        rec = new_day_record()
        warnings.append(f"Belum ada data closing untuk {fmt_date(D)}.")

    # ---------------- harian
    sales = rec.get("sales") or 0
    target = rec.get("target") or 0
    traffic = rec.get("traffic") or 0
    trx = rec.get("trx") or 0
    qty = rec.get("qty") or 0
    fw = rec.get("fw_unit") or 0
    crep = rec.get("crep_unit") or 0
    ly_d = ly_for(view, D, rec)
    cat_amt = rec.get("cat_amt") or {}
    if sum((cat_amt.get(c) or 0) for c in CATS) > 0:
        cat_pct = largest_remainder_pct({c: cat_amt.get(c) or 0 for c in CATS})
    else:
        cat_pct = {c: int((rec.get("cat_pct") or {}).get(c, 0)) for c in CATS}
    if crep > 0 and fw >= crep:
        sr = f"{rnd(fw / crep)}:1"
    elif crep > 0 and fw > 0:
        sr = f"1:{rnd(crep / fw)}"
    else:
        sr = f"{fw}:{crep}" if (fw or crep) else "-"
    daily = {
        "target": target, "sales": sales, "ly": ly_d,
        "traffic": traffic, "trx": trx, "qty": qty,
        "atv": sales / trx if trx else None,
        "upt": qty / trx if trx else None,
        "cr": trx / traffic * 100 if traffic else None,
        "fw_unit": fw, "crep_unit": crep, "sr": sr, "cat_pct": cat_pct,
    }
    if ly_d is None:
        warnings.append(f"LY harian {fmt_date(D)} belum ada -> LFL% harian n/a. "
                        f"Upload data LY atau isi manual.")

    # ---------------- periode
    out: dict[str, Any] = {"date": d2s(D), "store": db["settings"].get("store", "MKG"),
                           "daily": daily}
    for p in PERIODS:
        key = period_key(p, D)
        start = period_start(p, D)
        tot = {"target": 0, "sales": 0, "ly": 0, "lm": 0}
        used_base = False
        if B and period_key(p, B) == key and B <= D:
            pb = base.get(p, {})
            for k in tot:
                tot[k] = int(pb.get(k) or 0)
            start = B + dt.timedelta(days=1)
            used_base = True
        missing, ly_missing, lm_missing = [], [], []
        for d in daterange(start, D):
            r = days.get(d2s(d))
            if r is None:
                missing.append(d)
            else:
                tot["target"] += r.get("target") or 0
                tot["sales"] += r.get("sales") or 0
            ly = ly_for(view, d, r)
            if ly is None:
                ly_missing.append(d)
            else:
                tot["ly"] += ly
            if p == "mtd":
                lm = lm_for(view, d, r)
                if lm is None:
                    lm_missing.append(d)
                else:
                    tot["lm"] += lm
        if p == "mtd" and rec.get("lm_mtd_manual"):
            tot["lm"] = int(rec["lm_mtd_manual"])
            lm_missing = []
        out[p] = dict(tot, label=period_label(p, D), key=key, start=d2s(period_start(p, D)),
                      used_baseline=used_base, missing=[d2s(x) for x in missing],
                      ly_missing=[d2s(x) for x in ly_missing],
                      lm_missing=[d2s(x) for x in lm_missing])
    def _lst(xs: list[str]) -> str:
        xs = sorted(xs)
        return ", ".join(fmt_date(x) for x in xs[:6]) + (" ..." if len(xs) > 6 else "")

    miss = {x for p in PERIODS for x in out[p]["missing"]}
    if miss:
        warnings.append(f"{len(miss)} hari belum di-closing ({_lst(list(miss))}) -> total "
                        f"periode belum lengkap. Closing tanggal tsb (boleh mundur).")
    lymiss = {x for p in PERIODS for x in out[p]["ly_missing"]} - {d2s(D)}
    if lymiss:
        warnings.append(f"LY kosong untuk {len(lymiss)} hari TY ({_lst(list(lymiss))}) -> "
                        f"LFL periode belum lengkap. Upload data LY di menu Data LY.")
    if out["mtd"]["lm_missing"]:
        warnings.append(f"Sales LM (bulan lalu) belum ada untuk {len(out['mtd']['lm_missing'])} "
                        f"hari ({_lst(out['mtd']['lm_missing'])}) -> Acv vs LM belum lengkap. "
                        f"Isi 'Sales LM' saat closing.")
    out["warnings"] = warnings
    return out


# ------------------------------------------------------------------ laporan
def build_report(c: dict) -> str:
    d = c["daily"]
    D = s2d(c["date"])
    wk, mtd, qtd, ytd = c["wk"], c["mtd"], c["qtd"], c["ytd"]
    cp = d["cat_pct"]
    atv = rp(d["atv"]) if d["atv"] is not None else "-"
    upt = (str(Decimal(str(d["upt"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
           if d["upt"] is not None else "-")
    cr = f"{rnd(d['cr'])}%" if d["cr"] is not None else "-"
    mtd_vs_t = f"{rnd(mtd['sales'] / mtd['target'] * 100)}%" if mtd["target"] else "n/a"
    ly_d = d["ly"]
    lines = [
        f"DATE {fmt_date(D)}",
        "",
        f"Store      : {c['store']}",
        f"Target  : {rp(d['target'])}",
        f"Sales     : {rp(d['sales'])}",
        f"Ach%     : {pct_gap(d['sales'], d['target'])}",
        f"LFL%     : {pct_gap(d['sales'], ly_d or 0)}",
        "",
        f"Traffic : {rp(d['traffic'])}",
        f"Trx     : {rp(d['trx'])}",
        f"Qty     : {rp(d['qty'])}",
        "",
        f"ATV  : {atv}",
        f"UPT  : {upt}",
        f"CR   : {cr}",
        "",
        f"Crep Unit : {d['crep_unit']}",
        f"FW Unit   : {d['fw_unit']}",
        f"SR      : {d['sr']}",
        "",
        "ALL CONTRIBUTION:",
        f"FW  : {cp.get('FW', 0)}%",
        f"Text: {cp.get('Textile', 0)}%",
        f"ACC : {cp.get('ACC', 0)}%",
        "",
        f"{wk['label']} Target   : {rp(wk['target'])}",
        f"{wk['label']} Sales    : {rp(wk['sales'])}",
        f"LY            : {rp(wk['ly'])}",
        f"Acv%              : {pct_gap(wk['sales'], wk['target'])}",
        f"LFL            : {pct_gap(wk['sales'], wk['ly'])}",
        "",
        f"MTD Target     : {rp(mtd['target'])}",
        f"MTD vs Target  : {mtd_vs_t}",
        f"MTD Sales LY   : {rp(mtd['ly'])}",
        f"MTD Sales TY   : {rp(mtd['sales'])}",
        f"Acv MTD %      : {pct_gap(mtd['sales'], mtd['target'])}",
        f"Acv vs LM      : {pct_gap(mtd['sales'], mtd['lm'])}",
        f"LFL%            : {pct_gap(mtd['sales'], mtd['ly'])}",
        "",
        f"{qtd['label']} Target      : {rp(qtd['target'])}",
        f"{qtd['label']} Sales Ach : {rp(qtd['sales'])}",
        f"{qtd['label']} LY    : {rp(qtd['ly'])}",
        f"Acv%         : {pct_gap(qtd['sales'], qtd['target'])}",
        f"LFL%         : {pct_gap(qtd['sales'], qtd['ly'])}",
        "",
        f"YTD Target     : {rp(ytd['target'])}",
        f"YTD Sales Ach      : {rp(ytd['sales'])}",
        f"YTD LY         : {rp(ytd['ly'])}",
        f"Acv%        : {pct_gap(ytd['sales'], ytd['target'])}",
        f"LFL%        : {pct_gap(ytd['sales'], ytd['ly'])}",
    ]
    return "\n".join(lines)


def flat_row(c: dict) -> dict:
    """1 baris ringkasan (untuk riwayat CSV / tabel)."""
    d = c["daily"]
    row = {
        "tanggal": fmt_date(c["date"]), "target": d["target"], "sales": d["sales"],
        "ach_%": pct_change(d["sales"], d["target"]), "ly": d["ly"],
        "lfl_%": pct_change(d["sales"], d["ly"] or 0),
        "traffic": d["traffic"], "trx": d["trx"], "qty": d["qty"],
        "atv": rnd(d["atv"]) if d["atv"] is not None else None,
        "upt": round(d["upt"], 2) if d["upt"] is not None else None,
        "cr_%": rnd(d["cr"]) if d["cr"] is not None else None,
        "crep_unit": d["crep_unit"], "fw_unit": d["fw_unit"], "sr": d["sr"],
        "fw_%": d["cat_pct"].get("FW"), "text_%": d["cat_pct"].get("Textile"),
        "acc_%": d["cat_pct"].get("ACC"),
    }
    for p in PERIODS:
        x = c[p]
        row[f"{p}_label"] = x["label"]
        row[f"{p}_target"] = x["target"]
        row[f"{p}_sales"] = x["sales"]
        row[f"{p}_ly"] = x["ly"]
        row[f"{p}_acv_%"] = pct_change(x["sales"], x["target"])
        row[f"{p}_lfl_%"] = pct_change(x["sales"], x["ly"])
    row["mtd_lm"] = c["mtd"]["lm"]
    row["mtd_vs_lm_%"] = pct_change(c["mtd"]["sales"], c["mtd"]["lm"])
    return row


def history_rows(db: dict) -> list[dict]:
    B = baseline_date(db)
    rows = []
    for k in sorted(db.get("days", {})):
        d = s2d(k)
        if B and d < B:
            continue
        try:
            c = compute(db, d)
        except Exception:
            continue
        r = flat_row(c)
        r["disimpan"] = db["days"][k].get("saved_at")
        rows.append(r)
    return rows


def export_history_csv(db: dict) -> Path:
    rows = history_rows(db)
    _ensure_dirs()
    if not rows:
        return HISTORY_CSV
    with open(HISTORY_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(rows)
    return HISTORY_CSV


def report_path(db: dict, date: dt.date | str) -> Path:
    return REPORT_DIR / f"KPI_{db['settings'].get('store', 'MKG')}_{d2s(s2d(date))}.txt"


# ------------------------------------------------------------------ aksi
def _period_snapshot(c: dict) -> dict:
    return {c[p]["label"]: {"target": c[p]["target"], "sales": c[p]["sales"], "ly": c[p]["ly"]}
            for p in PERIODS}


def save_day(db: dict, date: dt.date | str, rec: dict) -> tuple[dict, str]:
    """Simpan closing 1 tanggal (menimpa jika sudah ada). Return (calc, teks laporan)."""
    D = s2d(date)
    B = baseline_date(db)
    if B and D <= B:
        raise ValueError(f"Tanggal {fmt_date(D)} <= saldo awal ({fmt_date(B)}). "
                         f"Ubah saldo awal di menu Pengaturan bila perlu.")
    k = d2s(D)
    existed = k in db["days"]
    before = None
    try:
        before = _period_snapshot(compute(db, D))
    except Exception:
        pass
    rec = copy.deepcopy(rec)
    rec["saved_at"] = now_str()
    rec.pop("is_baseline", None)
    db["days"][k] = rec
    calc = compute(db, D)
    text = build_report(calc)
    write_db(db, "timpa" if existed else "save")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path(db, D).write_text(text, encoding="utf-8")
    log_event("TIMPA" if existed else "SAVE", k, {
        "input": {x: rec.get(x) for x in ("target", "sales", "traffic", "trx", "qty",
                                           "fw_unit", "crep_unit", "cat_amt", "ly_manual",
                                           "lm_day", "lm_mtd_manual")},
        "ly_dipakai": calc["daily"]["ly"],
        "file": [s.get("name") for s in rec.get("sources", [])],
        "sebelum": before, "sesudah": _period_snapshot(calc),
    })
    return calc, text


def delete_day(db: dict, date: dt.date | str) -> None:
    k = d2s(s2d(date))
    rec = db["days"].get(k)
    if not rec:
        return
    if rec.get("is_baseline"):
        raise ValueError("Record saldo awal tidak bisa dihapus (ubah lewat Pengaturan).")
    del db["days"][k]
    write_db(db, "hapus")
    log_event("HAPUS", k, {"record": rec})


def upsert_ly(db: dict, rows: list[tuple[str, int, str]]) -> int:
    """rows = [(iso_date, sales, sumber)]; data terakhir menimpa."""
    n = 0
    for k, v, src in rows:
        db["ly_daily"][k] = {"sales": int(v), "source": src, "updated_at": now_str()}
        n += 1
    if n:
        write_db(db, "ly")
        log_event("LY_IMPORT", None, {"jumlah_hari": n,
                                      "rentang": [min(r[0] for r in rows), max(r[0] for r in rows)],
                                      "sumber": sorted({r[2] for r in rows})[:10]})
    return n


def set_ly_table(db: dict, mapping: dict[str, int | None]) -> int:
    """Ganti seluruh data LY dari editor tabel."""
    old = db.get("ly_daily", {})
    new = {}
    for k, v in mapping.items():
        if v is None:
            continue
        prev = old.get(k, {})
        new[k] = {"sales": int(v), "source": prev.get("source", "edit manual")
                  if prev.get("sales") == int(v) else "edit manual",
                  "updated_at": prev.get("updated_at", now_str()) if prev.get("sales") == int(v)
                  else now_str()}
    changed = sum(1 for k in set(old) | set(new) if old.get(k, {}).get("sales") != new.get(k, {}).get("sales"))
    if changed:
        db["ly_daily"] = new
        write_db(db, "ly_edit")
        log_event("LY_EDIT", None, {"jumlah_berubah": changed})
    return changed


def set_baseline(db: dict, baseline: dict, base_day: dict | None) -> None:
    old = copy.deepcopy(db.get("baseline"))
    db["baseline"] = baseline
    if base_day is not None:
        base_day = dict(base_day, is_baseline=True, saved_at=now_str())
        db["days"][baseline["date"]] = base_day
    write_db(db, "saldo_awal")
    log_event("SALDO_AWAL", baseline["date"], {"lama": old, "baru": baseline})


def set_settings(db: dict, **kw) -> None:
    old = dict(db["settings"])
    db["settings"].update(kw)
    if old != db["settings"]:
        write_db(db, "setting")
        log_event("SETTING", None, {"lama": old, "baru": db["settings"]})


def restore_db(raw: bytes) -> dict:
    db = json.loads(raw.decode("utf-8"))
    if not isinstance(db, dict) or "days" not in db or "baseline" not in db:
        raise ValueError("File bukan backup kpi_db.json yang valid.")
    write_db(db, "sebelum_restore")
    log_event("RESTORE", None, {"jumlah_hari": len(db["days"])})
    return load_db()
