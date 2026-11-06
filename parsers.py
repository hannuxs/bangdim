"""
Pembaca file upload: PDF / CSV / TXT / XLSX.

Jenis yang dikenali
  sales_item : REPORT SALES PER ITEM (PDF/CSV)   -> sales, qty, FW unit, crep, kontribusi
  cashier    : DAILY CASHIER REPORT (PDF/CSV)    -> trx (nomor order SJ/CJ unik)
  traffic    : laporan traffic sensor (kolom jam, baris "Total Daily")
  kpi_table  : CSV/XLSX manual  (date, traffic, trx)
  kpi_text   : PDF/TXT berisi "Traffic : 760", "Trx : 83"
  ly_table   : CSV/XLSX LY harian (date, sales)
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
from typing import Any

from kpi_engine import parse_amount

KIND_LABEL = {
    "sales_item": "Sales per Item",
    "cashier": "Daily Cashier Report (Trx)",
    "traffic": "Traffic Sensor",
    "kpi_table": "Tabel Traffic/Trx (manual)",
    "kpi_text": "Teks Traffic/Trx",
    "ly_table": "Tabel LY harian",
    "unknown": "Tidak dikenali",
}

MONTHS = {
    "jan": 1, "januari": 1, "january": 1, "feb": 2, "februari": 2, "february": 2,
    "mar": 3, "maret": 3, "march": 3, "apr": 4, "april": 4, "mei": 5, "may": 5,
    "jun": 6, "juni": 6, "june": 6, "jul": 7, "juli": 7, "july": 7,
    "agu": 8, "agt": 8, "agustus": 8, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9, "okt": 10, "oktober": 10, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "des": 12, "desember": 12, "dec": 12, "december": 12,
}

RE_TRAFFIC = re.compile(r"traffic|footfall|visitor|pengunjung|people\s*in|\bin\s*count", re.I)
RE_TRX = re.compile(r"\btrx\b|transaksi|transaction|\bbills?\b|struk|receipt|\bnota\b", re.I)
RE_DATE_H = re.compile(r"date|tanggal|\btgl\b|hari", re.I)
RE_SALES_H = re.compile(r"sales|amount|netto|\bnett?\b|penjualan|omzet|omset|\bly\b|total", re.I)


# ------------------------------------------------------------------ tanggal & angka
def _mk(y: int, m: int, d: int) -> dt.date | None:
    if y < 100:
        y += 2000
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def parse_date_any(v: Any) -> dt.date | None:
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, (int, float)) and 20000 < float(v) < 80000:  # serial Excel
        return dt.date(1899, 12, 30) + dt.timedelta(days=int(v))
    s = str(v).strip()
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        return _mk(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", s)
    if m:  # format Indonesia: hari-bulan-tahun
        return _mk(int(m[3]), int(m[2]), int(m[1]))
    m = re.search(r"(\d{1,2})[\s\-]+([A-Za-z]{3,9})[\s\-,]+(\d{2,4})", s)
    if m and m[2].lower() in MONTHS:
        return _mk(int(m[3]), MONTHS[m[2].lower()], int(m[1]))
    m = re.search(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", s)
    if m:
        return _mk(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"(?<!\d)(\d{2})(\d{2})(20\d{2})(?!\d)", s)
    if m:
        return _mk(int(m[3]), int(m[2]), int(m[1]))
    return None


def date_from_name(name: str) -> dt.date | None:
    return parse_date_any(name)


def numbers_in(s: str) -> list[int]:
    out = []
    for t in re.findall(r"[-+]?\d[\d.,]*", str(s)):
        v = parse_amount(t.rstrip(".,"))
        if v is not None:
            out.append(v)
    return out


# ------------------------------------------------------------------ ekstraksi
def pdf_text(data: bytes) -> str:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    parts = []
    try:
        for page in pdf:
            tp = page.get_textpage()
            parts.append(tp.get_text_bounded())
            tp.close()
            page.close()
    finally:
        pdf.close()
    return "\n".join(parts).replace("\r\n", "\n").replace("\r", "\n")


def decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            t = data.decode(enc)
            if enc == "utf-16" and "\x00" in t:
                continue
            return t
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="ignore")


def csv_rows(text: str) -> list[list[str]]:
    sample = text[:5000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delim = dialect.delimiter
    except csv.Error:
        delim = max(",;\t|", key=sample.count)
    return [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), delimiter=delim)
            if any(c.strip() for c in r)]


def xlsx_rows(data: bytes) -> list[list[Any]]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    rows: list[list[Any]] = []
    for ws in wb.worksheets:
        for r in ws.iter_rows(values_only=True):
            if r and any(c not in (None, "") for c in r):
                rows.append(["" if c is None else c for c in r])
        if rows:
            break
    wb.close()
    return rows


def extract(name: str, data: bytes) -> tuple[str, list[list[Any]] | None]:
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if ext == "pdf" or data[:5] == b"%PDF-":
        return pdf_text(data), None
    if ext in ("xlsx", "xlsm"):
        rows = xlsx_rows(data)
        return "\n".join("\t".join(str(c) for c in r) for r in rows), rows
    if ext == "xls":
        raise ValueError("Format .xls lama belum didukung - simpan ulang sebagai .xlsx atau .csv")
    text = decode_text(data)
    if ext in ("csv", "tsv") or (text.count("\n") > 1 and re.search(r"[,;\t]", text[:2000])):
        return text, csv_rows(text)
    return text, None


# ------------------------------------------------------------------ kategori
def cat_of(x: str) -> str:
    if re.search(r"MarketingGoods|MARKETING\s*GOODS|GIFT\s*CARD|PAPER\s*BAG|SHOPPING\s*BAG", x, re.I):
        return "X"
    if re.search(r"FOOTWEAR|\bFTWR?\b|\b[MWCJK]FW\b|SANDAL", x, re.I):
        return "FW"
    if re.search(r"\bACC\b|ACCESSOR|\bCREP\b|\bCAP\b|\bBAG\b|\bSOCKS?\b|BACKPACK|WAISTPACK|DUFFEL", x, re.I):
        return "ACC"
    if re.search(r"JERSEY|T-SHIRT|\bTEE\b|\bSHORTS?\b|\bSHRT\b|\bDRESS\b|TXTLS|TEXTILE|\b[RJMWK]TX\b"
                 r"|\bTEX\b|\bTXT|HOODIE|HOOD|HODD|DENIM|CARGO|\bPNT\b|SKORT|TANKLE|\bTANK\b|JACKET"
                 r"|\bJKT\b|SWEAT|SKIRT|SKRT|PANTS|JEAN|POLO|TRACKTOP|\bL/S\b|\bS/S\b", x, re.I):
        return "Textile"
    return "?"


# ------------------------------------------------------------------ sales per item
RE_ITEM = re.compile(
    r"^(\d[\d.]*)\s+(\d{6,})\s+(.+?)\s+(-?\d[\d.]*)\s+(-?\d[\d.]*)\s+(-?\d[\d.]*)"
    r"\s+(-?\d[\d.]*)\s+(-?\d[\d.]*)\s+(-?\d[\d.]*)$")
RE_PERIODE = re.compile(r"PERIODE\s*:?\s*(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})"
                        r"(?:\s*(?:to|s/?d|-|sampai)\s*(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}))?", re.I)


def _periode(text: str) -> tuple[dt.date | None, dt.date | None]:
    m = RE_PERIODE.search(text)
    if not m:
        return None, None
    a = parse_date_any(m[1])
    b = parse_date_any(m[2]) if m[2] else a
    return a, b


def _summarize_items(items: list[tuple[str, int, int]], res: dict) -> None:
    cat_amt = {"FW": 0, "Textile": 0, "ACC": 0}
    cat_qty = {"FW": 0, "Textile": 0, "ACC": 0}
    qty = crep = item_total = skip_qty = 0
    unk: list[str] = []
    for desc, q, a in items:
        item_total += a
        c = cat_of(desc)
        if c == "X":
            skip_qty += q
            continue
        qty += q
        if re.search(r"\bCREP\b", desc, re.I):
            crep += q
        if c in cat_amt:
            cat_amt[c] += a
            cat_qty[c] += q
        else:
            unk.append(desc)
    v = res["values"]
    v.update(qty=qty, fw_unit=cat_qty["FW"], crep_unit=crep, cat_amt=cat_amt,
             cat_qty=cat_qty, item_total=item_total)
    res["info"].append(f"{len(items)} artikel dibaca; {skip_qty} pcs paper bag / marketing goods "
                       f"tidak dihitung di Qty.")
    for c in cat_amt:
        res["info"].append(f"{c:8s}: {cat_qty[c]:>5} pcs   Rp {cat_amt[c]:,}".replace(",", "."))
    if unk:
        res["warnings"].append(f"{len(unk)} artikel tidak masuk kategori FW/Text/ACC: "
                               + "; ".join(unk[:4]) + (" ..." if len(unk) > 4 else ""))


RE_CODE_ONLY = re.compile(r"^(?:\d[\d.]*\s+)?(\d{6,})\s+(\D.*)$")
RE_NUMS_ONLY = re.compile(r"^(?:\d[\d.]*\s+)?(-?\d[\d.]*)\s+(-?\d[\d.]*)\s+(-?\d[\d.]*)"
                          r"\s+(-?\d[\d.]*)\s+(-?\d[\d.]*)\s+(-?\d[\d.]*)$")


def parse_sales_item_text(text: str, res: dict) -> bool:
    """Baris normal: No Code Desc Group Qty Amount QtyRet RetAmt QtyNett AmountNetto.
    Baris panjang kadang terpecah (kode di 1 baris, angka di baris berikutnya)."""
    items: dict[tuple, tuple[str, int, int]] = {}
    pending: tuple[str, str] | None = None
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.split("\n")]

    def group_tail(j: int) -> str:
        # potongan Article Group yang terlipat ke baris berikutnya ("TEXTILESHOODE")
        nxt = lines[j + 1] if j + 1 < len(lines) else ""
        return " " + nxt if re.fullmatch(r"[A-Za-z][A-Za-z /&\-]{1,40}", nxt) else ""

    for i, line in enumerate(lines):
        m = RE_ITEM.match(line)
        if m:
            # pdfium tidak menduplikasi baris lengkap (yang dobel hanya potongan
            # kode tanpa angka) -> setiap baris lengkap dihitung
            items[("F", i)] = (m[3] + group_tail(i), parse_amount(m[8]) or 0,
                               parse_amount(m[9]) or 0)
            pending = None
            continue
        m = RE_CODE_ONLY.match(line)
        if m and not re.search(r"\d[\d.]*\s+\d[\d.]*\s+\d[\d.]*$", line):
            pending = (m[1], m[2])
            continue
        m = RE_NUMS_ONLY.match(line)
        if m and pending:
            items[("L", i)] = (pending[1], parse_amount(m[5]) or 0, parse_amount(m[6]) or 0)
            pending = None
    if not items:
        return False
    a, b = _periode(text)
    res["period"] = [a.isoformat() if a else None, b.isoformat() if b else None]
    _summarize_items(list(items.values()), res)
    pm = re.search(r"Total\s*Payment\s*:?\s*(-?\d[\d.]*)", text, re.I)
    v = res["values"]
    pay = parse_amount(pm[1]) if pm else None
    v["pay_total"] = pay
    v["sales"] = pay if pay is not None else v["item_total"]
    if pay is not None and abs(pay - v["item_total"]) > 1:
        res["warnings"].append(f"Total item ({v['item_total']:,}) berbeda dengan Total Payment "
                               f"({pay:,}) -> dipakai Total Payment.".replace(",", "."))
    res["info"].insert(0, f"Sales (Total Payment) = Rp {v['sales']:,}".replace(",", "."))
    return True


def parse_sales_item_rows(rows: list[list[Any]], text: str, res: dict) -> bool:
    hi = None
    for i, r in enumerate(rows[:30]):
        j = " ".join(str(c) for c in r).lower()
        if "article" in j and ("netto" in j or "amount" in j):
            hi = i
            break
    if hi is None:
        return False
    h = [str(c).lower() for c in rows[hi]]

    def col(*pats):
        for p in pats:
            for i, c in enumerate(h):
                if re.search(p, c):
                    return i
        return None

    ci_desc, ci_grp = col(r"desc"), col(r"group")
    ci_q, ci_a = col(r"qty\s*nett"), col(r"amount\s*nett", r"netto")
    if ci_q is None:
        ci_q = col(r"qty")
    if ci_a is None:
        ci_a = col(r"amount")
    if ci_q is None or ci_a is None:
        return False
    items = []
    for r in rows[hi + 1:]:
        if len(r) <= max(ci_q, ci_a):
            continue
        q, a = parse_amount(r[ci_q]), parse_amount(r[ci_a])
        if q is None or a is None:
            continue
        first = str(r[0]).strip().lower()
        if first.startswith("total") or "summary" in first:
            break
        desc = " ".join(str(r[i]) for i in (ci_desc, ci_grp) if i is not None)
        items.append((desc, q, a))
    if not items:
        return False
    a, b = _periode(text)
    res["period"] = [a.isoformat() if a else None, b.isoformat() if b else None]
    _summarize_items(items, res)
    pm = re.search(r"Total\s*Payment\s*:?\s*[\t ]*(-?\d[\d.,]*)", text, re.I)
    pay = parse_amount(pm[1]) if pm else None
    res["values"]["pay_total"] = pay
    res["values"]["sales"] = pay if pay is not None else res["values"]["item_total"]
    res["info"].insert(0, f"Sales = Rp {res['values']['sales']:,}".replace(",", "."))
    return True


# ------------------------------------------------------------------ cashier
def parse_cashier(text: str, res: dict) -> bool:
    orders = set()
    for line in text.split("\n"):
        m = re.match(r"^(?:\d+\s+)?((?:SJ|CJ)\d{8,})\b", line.replace("\t", " ").strip())
        if m:
            orders.add(m[1])
    if not orders:
        orders = set(re.findall(r"\b(?:SJ|CJ)\d{8,}\b", text))
    if not orders:
        return False
    m = re.search(r"Periode\s*:?\s*(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})", text, re.I)
    if m:
        d = parse_date_any(m[1])
        res["period"] = [d.isoformat(), d.isoformat()] if d else None
    res["values"]["trx"] = len(orders)
    tm = re.search(r"^\s*Total\s+(\d{1,3}(?:\.\d{3})+)", text.replace("\t", " "), re.M)
    if tm:
        res["values"]["cash_total"] = parse_amount(tm[1])
    res["info"].append(f"Trx = {len(orders)} nomor order unik (SJ/CJ); nomor referensi retur "
                       f"& split payment tidak dihitung dobel.")
    return True


# ------------------------------------------------------------------ traffic
RE_TIME = re.compile(r"^(\d{1,2})[:.]\d{2}$")
RE_TOT_ROW = re.compile(r"total\s*daily|total\s*today|total\s*hari\s*ini", re.I)
RE_YEST_ROW = re.compile(r"yesterday|kemarin", re.I)


def parse_traffic_rows(rows: list[list[Any]], res: dict) -> bool:
    for hi, h in enumerate(rows[:10]):
        cols = []
        for i, x in enumerate(h):
            m = RE_TIME.match(str(x).strip())
            if m and 10 <= int(m[1]) <= 22:
                cols.append(i)
        if len(cols) >= 2:
            break
    else:
        return False

    def ssum(r):
        return sum((numbers_in(r[i])[:1] or [0])[0] for i in cols if i < len(r))

    tot = yest = None
    for r in rows[hi + 1:]:
        lab = str(r[0]).lower() if r else ""
        if RE_TOT_ROW.search(lab):
            tot = ssum(r)
        elif RE_YEST_ROW.search(lab):
            yest = ssum(r)
    if tot is None:
        data_rows = [r for r in rows[hi + 1:] if any(numbers_in(r[i]) for i in cols if i < len(r))]
        if len(data_rows) == 1:
            tot = ssum(data_rows[0])
    if tot is None:
        return False
    res["values"]["traffic"] = tot
    if yest is not None:
        res["values"]["traffic_yesterday"] = yest
    res["info"].append(f"Traffic = jumlah baris 'Total Daily' jam {rows[hi][cols[0]]}-"
                       f"{rows[hi][cols[-1]]} ({len(cols)} slot jam).")
    return True


def parse_traffic_text(text: str, res: dict) -> bool:
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.split("\n")]
    hours: list[int] = []
    for ln in lines:
        ts = re.findall(r"\b(\d{1,2})[:.]00\b", ln)
        if len(ts) >= 4:
            hours = [int(t) for t in ts]
            break
    for ln in lines:
        if RE_TOT_ROW.search(ln):
            nums = numbers_in(RE_TOT_ROW.sub("", ln))
            if not nums:
                continue
            if hours and len(nums) >= len(hours):
                tot = sum(n for h, n in zip(hours, nums) if 10 <= h <= 22)
            elif len(nums) > 1 and nums[-1] == sum(nums[:-1]):
                tot = nums[-1]
            else:
                tot = sum(nums)
            res["values"]["traffic"] = tot
            res["info"].append("Traffic dari baris 'Total Daily' di PDF/teks - mohon cek angkanya.")
            return True
    return False


# ------------------------------------------------------------------ tabel manual
def _header_index(rows: list[list[Any]], need) -> int | None:
    for i, r in enumerate(rows[:15]):
        if need([str(c) for c in r]):
            return i
    return None


def parse_kpi_table(rows: list[list[Any]], res: dict) -> bool:
    def need(h):
        return any(RE_TRAFFIC.search(c) for c in h) or any(RE_TRX.search(c) for c in h)

    hi = _header_index(rows, need)
    if hi is None:
        return False
    h = [str(c) for c in rows[hi]]
    ci_d = next((i for i, c in enumerate(h) if RE_DATE_H.search(c)), None)
    ci_t = next((i for i, c in enumerate(h) if RE_TRAFFIC.search(c)), None)
    ci_x = next((i for i, c in enumerate(h) if RE_TRX.search(c) and i != ci_t), None)
    entries: dict[str, dict] = {}
    nodate: dict = {}
    for r in rows[hi + 1:]:
        vals = {}
        if ci_t is not None and ci_t < len(r) and numbers_in(r[ci_t]):
            vals["traffic"] = numbers_in(r[ci_t])[0]
        if ci_x is not None and ci_x < len(r) and numbers_in(r[ci_x]):
            vals["trx"] = numbers_in(r[ci_x])[0]
        if not vals:
            continue
        d = parse_date_any(r[ci_d]) if ci_d is not None and ci_d < len(r) else None
        if d:
            e = entries.setdefault(d.isoformat(), {})
            for k, v in vals.items():
                e[k] = e.get(k, 0) + v
        else:
            for k, v in vals.items():
                nodate[k] = nodate.get(k, 0) + v
    if not entries and not nodate:
        return False
    res["entries"] = [{"date": k, "values": v} for k, v in sorted(entries.items())]
    if nodate:
        res["values"].update(nodate)
    res["info"].append(f"Tabel manual: {len(entries)} tanggal" +
                       (" + baris tanpa tanggal" if nodate else "") + ".")
    return True


def parse_kpi_text(text: str, res: dict) -> bool:
    got = False
    m = re.search(r"\b(?:traffic|footfall|visitors?|pengunjung)\b[^\d\n]{0,20}(\d[\d.,]*)", text, re.I)
    if m:
        res["values"]["traffic"] = parse_amount(m[1])
        got = True
    m = re.search(r"\b(?:trx|transaksi|transactions?|total\s*bills?|jumlah\s*struk|struk)\b"
                  r"[^\d\n]{0,20}(\d[\d.,]*)", text, re.I)
    if m:
        res["values"]["trx"] = parse_amount(m[1])
        got = True
    if got:
        res["info"].append("Angka dibaca dari teks (Traffic / Trx) - mohon cek.")
    return got


def parse_ly_table(rows: list[list[Any]], res: dict) -> bool:
    def need(h):
        return any(RE_DATE_H.search(c) for c in h) and any(RE_SALES_H.search(c) for c in h)

    hi = _header_index(rows, need)
    if hi is None:
        return False
    h = [str(c) for c in rows[hi]]
    ci_d = next(i for i, c in enumerate(h) if RE_DATE_H.search(c))
    pref = [i for i, c in enumerate(h) if i != ci_d and re.search(r"sales|netto|penjualan|omzet|omset|\bly\b", c, re.I)]
    ci_s = pref[0] if pref else next(i for i, c in enumerate(h) if i != ci_d and RE_SALES_H.search(c))
    entries = {}
    for r in rows[hi + 1:]:
        if max(ci_d, ci_s) >= len(r):
            continue
        d = parse_date_any(r[ci_d])
        v = parse_amount(r[ci_s]) if str(r[ci_s]).strip() != "" else None
        if d and v is not None:
            entries[d.isoformat()] = entries.get(d.isoformat(), 0) + v
    if not entries:
        return False
    res["entries"] = [{"date": k, "values": {"sales": v}} for k, v in sorted(entries.items())]
    res["info"].append(f"LY harian: {len(entries)} tanggal ({min(entries)} s/d {max(entries)}).")
    return True


# ------------------------------------------------------------------ utama
def parse_upload(name: str, data: bytes, prefer: str = "closing") -> dict:
    """prefer = 'closing' atau 'ly' (urutan deteksi tabel)."""
    res: dict[str, Any] = {"name": name, "kind": "unknown", "period": None, "date": None,
                           "values": {}, "entries": [], "info": [], "warnings": []}
    try:
        text, rows = extract(name, data)
    except Exception as e:  # noqa: BLE001
        res["warnings"].append(f"Gagal membaca file: {e}")
        return res
    if len(text.replace(" ", "").replace("\n", "")) < 10 and not rows:
        res["warnings"].append("File kosong / PDF hasil scan (gambar) - tidak ada teks yang bisa dibaca.")
        return res

    ok = False
    if re.search(r"sales\s*per\s*item", text, re.I):
        ok = (parse_sales_item_rows(rows, text, res) if rows else False) or \
             parse_sales_item_text(text, res)
        if ok:
            res["kind"] = "sales_item"
    if not ok and (re.search(r"daily\s*cashier\s*report", text, re.I)
                   or re.search(r"\b(?:SJ|CJ)\d{8,}\b", text)):
        if parse_cashier(text, res):
            res["kind"], ok = "cashier", True
    if not ok and rows and parse_traffic_rows(rows, res):
        res["kind"], ok = "traffic", True
    if not ok and rows:
        order = [("ly_table", parse_ly_table), ("kpi_table", parse_kpi_table)]
        if prefer != "ly":
            order.reverse()
        for kind, fn in order:
            if fn(rows, res):
                res["kind"], ok = kind, True
                break
    if not ok and not rows and parse_traffic_text(text, res):
        res["kind"], ok = "traffic", True
    if not ok and parse_kpi_text(text, res):
        res["kind"], ok = "kpi_text", True

    # tanggal
    d = None
    if res.get("period") and res["period"][0]:
        a, b = res["period"]
        if b and a != b:
            res["warnings"].append(f"File berisi periode {a} s/d {b} (lebih dari 1 hari) - "
                                   f"tidak bisa dipakai sebagai data 1 hari.")
        else:
            d = a
    if d is None and not res["entries"] and not res.get("period"):
        m = re.search(r"(?:tanggal|date|periode|period|tgl)\D{0,15}"
                      r"(\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})", text, re.I)
        dd = parse_date_any(m[1]) if m else None
        dd = dd or date_from_name(name)
        d = dd.isoformat() if dd else None
    res["date"] = d
    if not ok:
        res["warnings"].append("Jenis file tidak dikenali. Isi angka secara manual.")
    res["kind_label"] = KIND_LABEL[res["kind"]]
    return res
