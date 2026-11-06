"""
KPI CLOSING HARIAN - Streamlit
Jalankan lewat run.bat  (atau: python -m streamlit run app.py)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import datetime as dt  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import kpi_engine as K  # noqa: E402
import parsers as P  # noqa: E402

st.set_page_config(page_title="KPI Closing", page_icon="📊", layout="wide")

SALES_FIELDS = ("sales", "qty", "fw_unit", "crep_unit", "cat_amt", "item_total", "pay_total")
ss = st.session_state
ss.setdefault("up_n", 0)
ss.setdefault("ly_up_n", 0)
ss.setdefault("ly_pending", {})


# ================================================================== helper
def fd(d) -> str:
    return K.fmt_date(d)


def short(v) -> str:
    """Angka ringkas untuk kartu metrik: 822,6 jt / 5,36 M."""
    v = v or 0
    if abs(v) >= 1e9:
        return f"{v / 1e9:,.2f} M".replace(",", "#").replace(".", ",").replace("#", ".")
    if abs(v) >= 1e6:
        return f"{v / 1e6:,.1f} jt".replace(",", "#").replace(".", ",").replace("#", ".")
    return K.rp(v)


def money(v) -> str:
    return "-" if v is None else "Rp " + K.rp(v)


def last_closing(db: dict) -> dt.date | None:
    ks = [k for k in db["days"]]
    return K.s2d(max(ks)) if ks else None


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", s)[:120]


def store_raw(date: str | None, name: str, data: bytes, seq: int) -> str:
    folder = K.UPLOAD_DIR / (date or "tanpa_tanggal")
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"{dt.datetime.now():%H%M%S}_{seq:04d}_{safe_name(name)}"
    p.write_bytes(data)
    return str(p.relative_to(K.DATA_DIR))


def draft_files_for(draft: dict, D: str) -> list[dict]:
    return sorted([f for f in draft["files"] if f.get("date") == D], key=lambda f: f["seq"])


def merged_values(draft: dict, D: str) -> tuple[dict, set]:
    """Gabungkan file draft 1 tanggal. Aturan: file TERAKHIR yang menyediakan angka tsb dipakai."""
    files = draft_files_for(draft, D)
    vals: dict = {}
    used: set = set()
    sales_files = [f for f in files if f["kind"] == "sales_item"]
    if sales_files:
        f = sales_files[-1]
        for k in SALES_FIELDS:
            if k in f["values"]:
                vals[k] = f["values"][k]
        used.add(f["id"])
    else:
        cf = [f for f in files if f["values"].get("cash_total")]
        if cf:
            vals["sales"] = cf[-1]["values"]["cash_total"]
            used.add(cf[-1]["id"])
    for field in ("traffic", "trx"):
        prov = [f for f in files if f["values"].get(field) is not None]
        if prov:
            vals[field] = prov[-1]["values"][field]
            used.add(prov[-1]["id"])
    return vals, used


def bump_rev(draft: dict, D: str) -> None:
    draft.setdefault("rev", {})
    draft["rev"][D] = draft["rev"].get(D, 0) + 1


def _store_manual(field: str, D: str, key: str) -> None:
    dr = K.load_draft()
    raw = ss.get(key, "")
    dr["manual"].setdefault(D, {})[field] = K.parse_amount(raw) if str(raw).strip() else None
    K.save_draft(dr)


def amount_input(col, label: str, field: str, D: str, auto, draft: dict, rev_extra: str = "",
                 help: str | None = None) -> int | None:
    rev = draft.get("rev", {}).get(D, 0)
    key = f"in_{field}_{D}_{rev}{rev_extra}"
    man = draft["manual"].get(D, {})
    init = man[field] if field in man else auto
    if key not in ss:
        ss[key] = "" if init is None else K.rp(init)
    col.text_input(label, key=key, on_change=_store_manual, args=(field, D, key), help=help)
    raw = ss.get(key, "")
    v = K.parse_amount(raw) if str(raw).strip() else None
    if str(raw).strip() and v is None:
        col.error("Angka tidak valid")
    elif field in man and auto is not None and v != auto:
        col.caption(f"✏️ manual (dari file/otomatis: {K.rp(auto)})")
    return v


def handle_uploads(files, draft: dict, D: str) -> tuple[list[str], str | None]:
    msgs: list[str] = []
    goto = None
    draft.setdefault("seq", 0)
    parsed = [(uf, uf.getvalue()) for uf in files]
    parsed = [(uf, data, P.parse_upload(uf.name, data, "closing")) for uf, data in parsed]
    # file tanpa tanggal ikut tanggal file lain di upload yang sama (jika hanya 1 tanggal)
    batch_dates = {r["date"] for _, _, r in parsed if r["date"] and r["kind"] != "ly_table"}
    batch_dates |= {e["date"] for _, _, r in parsed if r["kind"] != "ly_table" for e in r["entries"]}
    if len(batch_dates) == 1:
        D = next(iter(batch_dates))
    for uf, data, res in parsed:
        draft["seq"] += 1
        seq = draft["seq"]
        sha = hashlib.sha256(data).hexdigest()[:12]
        if res["kind"] == "ly_table":
            msgs.append(f"⚠️ **{uf.name}** berisi data LY -> upload di menu **Data LY**.")
            continue
        if res["kind"] == "unknown" and not res["values"]:
            msgs.append(f"❌ **{uf.name}**: " + "; ".join(res["warnings"]))
            continue
        targets = res["entries"] or [{"date": res["date"], "values": {}}]
        for e in targets:
            date = e["date"] or D
            vals = dict(res["values"], **e["values"])
            item = {
                "id": f"{seq}-{sha}-{date}", "seq": seq, "name": uf.name, "kind": res["kind"],
                "kind_label": res["kind_label"], "date": date,
                "date_from": "file" if e["date"] else ("file lain di upload yg sama"
                                                       if len(batch_dates) == 1 else
                                                       "tanggal closing dipilih"),
                "uploaded_at": K.now_str(), "sha": sha, "values": vals,
                "info": res["info"], "warnings": res["warnings"],
                "stored": store_raw(date, uf.name, data, seq),
            }
            draft["files"].append(item)
            # angka dari file terbaru menggantikan koreksi manual sebelumnya
            man = draft["manual"].get(date, {})
            for k in list(vals.keys()) + (["sales_detail"] if res["kind"] == "sales_item" else []):
                man.pop(k, None)
            if res["kind"] == "sales_item":
                for k in ("qty", "fw_unit", "crep_unit", "cat_FW", "cat_Textile", "cat_ACC"):
                    man.pop(k, None)
            bump_rev(draft, date)
            goto = date
        tgl = ", ".join(fd(e["date"] or D) for e in targets[:4])
        msgs.append(f"✅ **{uf.name}** -> {res['kind_label']} · tanggal {tgl}"
                    + ("" if res["date"] or res["entries"] else " (tanggal tidak ada di file -> ikut "
                       + ("file lain di upload yang sama)" if len(batch_dates) == 1
                          else "tanggal closing yang dipilih)")))
        for w in res["warnings"]:
            msgs.append(f"⚠️ {uf.name}: {w}")
    K.save_draft(draft)
    return msgs, goto


# ================================================================== halaman: closing
def page_closing(db: dict, draft: dict) -> None:
    B = K.baseline_date(db)
    last = last_closing(db)
    if "_goto_date" in ss:
        ss["closing_date"] = K.s2d(ss.pop("_goto_date"))
    if "closing_date" not in ss:
        pend = sorted({f["date"] for f in draft["files"] if f["date"] not in db["days"]})
        ss["closing_date"] = K.s2d(pend[-1]) if pend else (last + dt.timedelta(days=1)
                                                            if last else dt.date.today())

    st.title("🧾 Closing Harian")
    if ss.get("_saved"):
        sd, txt = ss.pop("_saved")
        st.success(f"✅ Closing **{fd(sd)}** TERSIMPAN. WK / MTD / QTD / YTD sudah ter-update. "
                   f"Laporan disimpan di `data/laporan/`.")
        with st.expander(f"Laporan {fd(sd)} (klik ikon copy di pojok kanan untuk WA)", expanded=True):
            st.code(txt, language=None)
            st.download_button("⬇️ Download .txt", txt, file_name=K.report_path(db, sd).name,
                               mime="text/plain", key="dl_saved")

    c1, c2, c3 = st.columns([1.2, 1, 1])
    D_date = c1.date_input("📅 Tanggal closing", key="closing_date", format="DD-MM-YYYY")
    D = K.d2s(D_date)
    c2.metric("Closing terakhir", fd(last) if last else "-")
    c3.metric("Saldo awal", fd(B) if B else "-")
    if B and D_date <= B:
        st.error(f"Tanggal {fd(D)} <= saldo awal ({fd(B)}). Pilih tanggal setelah {fd(B)}, "
                 f"atau ubah saldo awal di menu ⚙️ Pengaturan.")
        return
    if D in db["days"]:
        st.warning(f"⚠️ Tanggal {fd(D)} SUDAH pernah disimpan ({db['days'][D].get('saved_at')}). "
                   f"Jika disimpan lagi, data akan DITIMPA (tidak dijumlah dua kali).")

    # ---------------- upload
    st.subheader("1 · Upload file")
    st.caption("Sales per Item (PDF/CSV) · Daily Cashier Report / file Trx (PDF/CSV) · Traffic "
               "(CSV/PDF) · bisa beberapa file sekaligus. Tanggal dideteksi otomatis dari file. "
               "Jika tanggal yang sama di-upload lebih dari 1 kali, **file TERAKHIR yang dipakai** "
               "sampai Anda klik **OK & SAVE**.")
    ups = st.file_uploader("Upload", type=["pdf", "csv", "txt", "tsv", "xlsx", "xlsm"],
                           accept_multiple_files=True, key=f"up_{ss.up_n}",
                           label_visibility="collapsed")
    if ups:
        msgs, goto = handle_uploads(ups, draft, D)
        ss["_up_msgs"] = msgs
        ss.up_n += 1
        if goto and goto != D:
            ss["_goto_date"] = goto
        st.rerun()
    for m in ss.pop("_up_msgs", []):
        st.markdown(m)

    files = draft_files_for(draft, D)
    vals, used = merged_values(draft, D)
    other = sorted({f["date"] for f in draft["files"] if f["date"] != D})
    if other:
        st.info("Ada file draft untuk tanggal lain (belum disimpan): "
                + ", ".join(fd(x) for x in other) + " -> pilih tanggalnya di atas untuk memproses.")
    if files:
        rows = []
        for f in files:
            v = f["values"]
            ringkas = []
            if "sales" in v:
                ringkas.append(f"Sales {K.rp(v['sales'])}")
            if "qty" in v:
                ringkas.append(f"Qty {v['qty']}")
            if v.get("trx") is not None:
                ringkas.append(f"Trx {v['trx']}")
            if v.get("traffic") is not None:
                ringkas.append(f"Traffic {v['traffic']}")
            rows.append({"Status": "✅ DIPAKAI" if f["id"] in used else "↩️ diganti file terbaru",
                         "Jam upload": f["uploaded_at"][11:], "File": f["name"],
                         "Jenis": f["kind_label"], "Angka terbaca": " · ".join(ringkas),
                         "Tanggal dari": f["date_from"]})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        with st.expander("Detail pembacaan file / hapus file draft"):
            for f in reversed(files):
                cA, cB = st.columns([5, 1])
                cA.markdown(f"**{f['name']}** · {f['kind_label']} · {f['uploaded_at']}")
                for line in f["info"]:
                    cA.caption(line)
                for w in f["warnings"]:
                    cA.caption("⚠️ " + w)
                if cB.button("🗑️ hapus", key=f"del_{f['id']}"):
                    dr = K.load_draft()
                    dr["files"] = [x for x in dr["files"] if x["id"] != f["id"]]
                    bump_rev(dr, D)
                    K.save_draft(dr)
                    st.rerun()

    # ---------------- input
    st.subheader("2 · Input & cek angka")
    ly_auto, ly_d, ly_src = K.ly_lookup(db, D_date)
    lm_auto, lm_d = K.lm_lookup(db, D_date)
    ly_rev = f"_{len(db['ly_daily'])}"
    c = st.columns(5)
    target = amount_input(c[0], "🎯 Target hari ini (Rp) *", "target", D, None, draft)
    traffic = amount_input(c[1], "🚶 Traffic", "traffic", D, vals.get("traffic"), draft)
    trx = amount_input(c[2], "🧾 Trx", "trx", D, vals.get("trx"), draft)
    ly_help = (f"Otomatis dari {ly_src} tanggal {fd(ly_d)}" if ly_d else ly_src)
    ly_v = amount_input(c[3], "📆 Sales LY hari ini", "ly_manual", D, ly_auto, draft, ly_rev,
                        help=ly_help + ". Boleh diisi/ubah manual.")
    c[3].caption(f"LY = {fd(ly_d)} · {ly_src}" if ly_d else ly_src)
    lm_help = (f"Sales tanggal {fd(lm_d)} (bulan lalu). Otomatis jika tanggal tsb sudah ada di "
               f"riwayat closing; jika belum, isi manual." if lm_d else
               "Bulan lalu tidak punya tanggal ini -> 0")
    lm_v = amount_input(c[4], "🗓️ Sales LM (tgl sama bln lalu)", "lm_day", D, lm_auto, draft,
                        help=lm_help)
    c[4].caption(f"LM = {fd(lm_d)}" + ("" if lm_auto is not None else " · belum ada, isi manual")
                 if lm_d else "tidak ada tanggal pembanding")

    has_sales_file = any(f["kind"] == "sales_item" for f in files)
    with st.expander("🛍️ Angka dari file Sales per Item (bisa dikoreksi manual)",
                     expanded=not has_sales_file):
        if not has_sales_file:
            st.info("Belum ada file Sales per Item untuk tanggal ini -> upload file, "
                    "atau isi manual di bawah.")
        cc = st.columns(4)
        sales = amount_input(cc[0], "💰 Sales (Rp) *", "sales", D, vals.get("sales"), draft)
        qty = amount_input(cc[1], "Qty", "qty", D, vals.get("qty"), draft)
        fw_u = amount_input(cc[2], "FW Unit", "fw_unit", D, vals.get("fw_unit"), draft)
        crep_u = amount_input(cc[3], "Crep Unit", "crep_unit", D, vals.get("crep_unit"), draft)
        ca = vals.get("cat_amt") or {}
        cc = st.columns(4)
        cat = {}
        for i, (k, lab) in enumerate((("FW", "Sales FW (Rp)"), ("Textile", "Sales Textile (Rp)"),
                                      ("ACC", "Sales ACC (Rp)"))):
            cat[k] = amount_input(cc[i], lab, f"cat_{k}", D, ca.get(k), draft) or 0
        lm_mtd = amount_input(cc[3], "LM MTD total (opsional, timpa)", "lm_mtd_manual", D, None,
                              draft, help="Isi hanya jika ingin langsung memakai total MTD bulan "
                                          "lalu (s/d tanggal sama). Kosongkan = dihitung otomatis.")

    rec = K.new_day_record()
    rec.update(target=target or 0, sales=sales or 0, traffic=traffic or 0, trx=trx or 0,
               qty=qty or 0, fw_unit=fw_u or 0, crep_unit=crep_u or 0, cat_amt=cat,
               ly_manual=(ly_v if ly_v != ly_auto else None),
               lm_day=(lm_v if lm_v != lm_auto else None),
               lm_mtd_manual=lm_mtd or None,
               sources=[{"kind": f["kind"], "name": f["name"], "uploaded_at": f["uploaded_at"],
                         "sha": f["sha"], "stored": f["stored"]} for f in files if f["id"] in used])
    if ly_v is None and ly_auto is None:
        rec["ly_manual"] = None

    # ---------------- preview
    st.subheader("3 · Preview laporan")
    try:
        calc = K.compute(db, D_date, draft=rec)
    except ValueError as e:
        st.error(str(e))
        return
    text = K.build_report(calc)
    left, right = st.columns([1.1, 1])
    with left:
        st.code(text, language=None)
    with right:
        d = calc["daily"]
        m = st.columns(3)
        m[0].metric("Sales", short(d["sales"]),
                    K.pct_gap(d["sales"], d["target"], "target belum diisi"),
                    delta_color="normal" if d["target"] else "off")
        m[1].metric("MTD", short(calc["mtd"]["sales"]),
                    K.pct_gap(calc["mtd"]["sales"], calc["mtd"]["target"]))
        m[2].metric(calc["wk"]["label"], short(calc["wk"]["sales"]),
                    K.pct_gap(calc["wk"]["sales"], calc["wk"]["target"]))
        m = st.columns(3)
        m[0].metric(calc["qtd"]["label"], short(calc["qtd"]["sales"]),
                    K.pct_gap(calc["qtd"]["sales"], calc["qtd"]["target"]))
        m[1].metric("YTD", short(calc["ytd"]["sales"]),
                    K.pct_gap(calc["ytd"]["sales"], calc["ytd"]["target"]))
        m[2].metric("SR (FW:Crep)", d["sr"])
        with st.expander("Rincian penjumlahan periode"):
            rows = []
            for p in K.PERIODS:
                x = calc[p]
                rows.append({"Periode": x["label"], "Mulai": fd(x["start"]),
                             "Saldo awal dipakai": "ya" if x["used_baseline"] else "tidak (reset)",
                             "Target": K.rp(x["target"]), "Sales": K.rp(x["sales"]),
                             "LY": K.rp(x["ly"]), "LM": K.rp(x["lm"]) if p == "mtd" else ""})
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        for w in calc["warnings"]:
            st.warning(w)

    # ---------------- save
    st.subheader("4 · OK & SAVE")
    errs = []
    if not target:
        errs.append("Target hari ini belum diisi.")
    if not sales:
        errs.append("Sales masih 0 / belum ada file Sales per Item.")
    for e in errs:
        st.error(e)
    force = st.checkbox("Tetap simpan walau ada yang kosong", key=f"force_{D}") if errs else True
    overwrite_ok = True
    if D in db["days"]:
        overwrite_ok = st.checkbox(f"Ya, TIMPA data closing {fd(D)}", key=f"ow_{D}")
    if st.button("✅ OK & SAVE", type="primary", disabled=not (force and overwrite_ok),
                 width="stretch"):
        try:
            _, txt = K.save_day(db, D_date, rec)
        except ValueError as e:
            st.error(str(e))
            return
        dr = K.load_draft()
        dr["files"] = [f for f in dr["files"] if f["date"] != D]
        dr["manual"].pop(D, None)
        K.save_draft(dr)
        ss["_saved"] = (D, txt)
        ss["_goto_date"] = K.d2s(D_date + dt.timedelta(days=1))
        st.rerun()


# ================================================================== halaman: LY
def page_ly(db: dict) -> None:
    st.title("📆 Data LY (tahun lalu) harian")
    mode = db["settings"].get("ly_mode", "calendar")
    st.caption(f"Pembanding LY: **{K.LY_MODES[mode]}** (ubah di ⚙️ Pengaturan). "
               "LY dipakai untuk LFL harian, WK, MTD, QTD, YTD.")
    lyd = db["ly_daily"]
    last = last_closing(db) or dt.date.today()
    B = K.baseline_date(db)
    need_from = (B + dt.timedelta(days=1)) if B else dt.date(last.year, 1, 1)
    need_to = max(last + dt.timedelta(days=7), need_from)
    miss = [d for d in K.daterange(need_from, need_to) if K.ly_lookup(db, d)[0] is None]
    c = st.columns(3)
    c[0].metric("Hari LY tersimpan", len(lyd))
    c[1].metric("Rentang", f"{fd(min(lyd))} – {fd(max(lyd))}" if lyd else "-")
    c[2].metric(f"LY kosong {fd(need_from)}–{fd(need_to)}", len(miss))
    if miss:
        st.warning("Tanggal TY yang LY-nya belum ada: " + ", ".join(fd(x) for x in miss[:15])
                   + (" ..." if len(miss) > 15 else ""))

    st.subheader("Upload data LY")
    st.caption("Format yang diterima: (1) CSV/XLSX kolom **date** + **sales** (banyak tanggal "
               "sekaligus), (2) PDF/CSV **REPORT SALES PER ITEM** periode **1 hari** (boleh banyak "
               "file). File tahunan (01-01 s/d 31-12) tidak bisa dipecah per hari. Tanggal yang "
               "di-upload berulang -> **file terakhir yang dipakai** sampai klik OK & SAVE.")
    yr = (last.year - 1)
    tmpl = "date,sales\r\n" + "".join(f"{K.fmt_date(d)},\r\n" for d in
                                      K.daterange(dt.date(yr, 1, 1), dt.date(yr, 12, 31)))
    st.download_button(f"⬇️ Template CSV LY {yr}", tmpl, file_name=f"template_LY_{yr}.csv",
                       mime="text/csv")
    ups = st.file_uploader("Upload LY", type=["csv", "txt", "tsv", "xlsx", "xlsm", "pdf"],
                           accept_multiple_files=True, key=f"lyup_{ss.ly_up_n}",
                           label_visibility="collapsed")
    if ups:
        msgs = []
        for uf in ups:
            res = P.parse_upload(uf.name, uf.getvalue(), "ly")
            got = 0
            if res["kind"] == "ly_table":
                for e in res["entries"]:
                    ss.ly_pending[e["date"]] = (e["values"]["sales"], uf.name)
                    got += 1
            elif res["kind"] == "sales_item" and res["date"]:
                ss.ly_pending[res["date"]] = (res["values"]["sales"], uf.name)
                got = 1
            msgs.append((f"✅ **{uf.name}**: {got} tanggal" if got else f"❌ **{uf.name}**: tidak ada "
                         f"data LY harian") + ("" if got else " — " + "; ".join(res["warnings"])))
        ss["_ly_msgs"] = msgs
        ss.ly_up_n += 1
        st.rerun()
    for m in ss.pop("_ly_msgs", []):
        st.markdown(m)
    if ss.ly_pending:
        rows = [{"Tanggal LY": fd(k), "Sales": K.rp(v), "File": n,
                 "Status": f"menimpa {K.rp(lyd[k]['sales'])}" if k in lyd else "baru"}
                for k, (v, n) in sorted(ss.ly_pending.items())]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        a, b = st.columns(2)
        if a.button(f"✅ OK & SAVE {len(rows)} tanggal LY", type="primary",
                    width="stretch"):
            n = K.upsert_ly(db, [(k, v, f) for k, (v, f) in ss.ly_pending.items()])
            ss.ly_pending = {}
            st.toast(f"{n} tanggal LY tersimpan")
            st.rerun()
        if b.button("Batal", width="stretch"):
            ss.ly_pending = {}
            st.rerun()

    st.subheader("Edit manual data LY")
    df = pd.DataFrame([{"tanggal": K.s2d(k), "sales": v["sales"], "sumber": v.get("source", "")}
                       for k, v in sorted(lyd.items())],
                      columns=["tanggal", "sales", "sumber"])
    if df.empty:
        df = pd.DataFrame({"tanggal": pd.Series(dtype="object"), "sales": pd.Series(dtype="int64"),
                           "sumber": pd.Series(dtype="object")})
    ed = st.data_editor(df, num_rows="dynamic", width="stretch", hide_index=True,
                        key="ly_editor",
                        column_config={
                            "tanggal": st.column_config.DateColumn("Tanggal LY", format="DD-MM-YYYY"),
                            "sales": st.column_config.NumberColumn("Sales LY", format="%d", min_value=0),
                            "sumber": st.column_config.TextColumn("Sumber", disabled=True)})
    if st.button("💾 Simpan perubahan tabel LY"):
        mp = {}
        for _, r in ed.iterrows():
            if pd.isna(r["tanggal"]) or pd.isna(r["sales"]):
                continue
            mp[K.d2s(pd.Timestamp(r["tanggal"]).date())] = int(r["sales"])
        n = K.set_ly_table(db, mp)
        st.toast(f"{n} baris LY berubah")
        st.rerun()


# ================================================================== halaman: riwayat
def page_history(db: dict) -> None:
    st.title("📚 Riwayat closing & log")
    rows = K.history_rows(db)
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df, hide_index=True, width="stretch")
        c = st.columns(2)
        c[0].download_button("⬇️ Riwayat (CSV)", df.to_csv(index=False, sep=";").encode("utf-8-sig"),
                             file_name="riwayat_closing.csv", mime="text/csv")
        bio = io.BytesIO()
        df.to_excel(bio, index=False, sheet_name="riwayat")
        c[1].download_button("⬇️ Riwayat (Excel)", bio.getvalue(), file_name="riwayat_closing.xlsx",
                             mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.subheader("Lihat / hapus laporan per tanggal")
    keys = sorted(db["days"], reverse=True)
    if keys:
        k = st.selectbox("Tanggal", keys, format_func=fd)
        rec = db["days"][k]
        calc = K.compute(db, k)
        txt = K.build_report(calc)
        c1, c2 = st.columns([1.1, 1])
        c1.code(txt, language=None)
        c1.download_button("⬇️ Download .txt", txt, file_name=K.report_path(db, k).name,
                           mime="text/plain")
        with c2:
            st.markdown(f"**Disimpan:** {rec.get('saved_at')}")
            if rec.get("is_baseline"):
                st.info("Ini record SALDO AWAL (ubah lewat ⚙️ Pengaturan).")
            st.markdown("**File sumber:** " + (", ".join(s.get("name", "") for s in
                                                       rec.get("sources", [])) or "-"))
            for w in calc["warnings"]:
                st.warning(w)
            if not rec.get("is_baseline"):
                ok = st.checkbox(f"Saya yakin hapus closing {fd(k)}", key=f"cdel_{k}")
                if st.button("🗑️ Hapus closing tanggal ini", disabled=not ok):
                    K.delete_day(db, k)
                    st.toast(f"Closing {fd(k)} dihapus")
                    st.rerun()

    st.subheader("Log aktivitas (semua penyimpanan & penjumlahan)")
    log = K.read_log()
    if log:
        lr = []
        for e in reversed(log[-500:]):
            det = e.get("detail", {})
            ring = ""
            if "sesudah" in det:
                ring = " | ".join(f"{p}: {K.rp(v['sales'])}" for p, v in det["sesudah"].items())
            else:
                ring = json.dumps(det, ensure_ascii=False)[:200]
            lr.append({"Waktu": e["waktu"], "Aksi": e["aksi"],
                       "Tanggal": fd(e["tanggal"]) if e.get("tanggal") else "", "Ringkasan": ring})
        st.dataframe(pd.DataFrame(lr), hide_index=True, width="stretch")
        with st.expander("Detail log (JSON) terakhir"):
            st.json(log[-1])
    st.caption(f"Folder data: `{K.DATA_DIR}`")


# ================================================================== halaman: pengaturan
def page_settings(db: dict) -> None:
    st.title("⚙️ Pengaturan")
    s = db["settings"]
    c = st.columns(2)
    store = c[0].text_input("Kode / nama store", s.get("store", "MKG"))
    modes = list(K.LY_MODES)
    mode = c[1].radio("Pembanding LY (LFL)", modes, index=modes.index(s.get("ly_mode", "calendar")),
                      format_func=lambda m: K.LY_MODES[m])
    if st.button("💾 Simpan pengaturan"):
        K.set_settings(db, store=store.strip() or "MKG", ly_mode=mode)
        st.toast("Pengaturan tersimpan")
        st.rerun()

    st.divider()
    st.subheader("Saldo awal (posisi periode pada 1 tanggal)")
    st.caption("Angka ini adalah titik awal penjumlahan. Closing setelah tanggal ini akan "
               "ditambahkan otomatis. Ubah hanya bila saldo awal salah / mulai ulang.")
    b = db["baseline"]
    bd = b.get("date")
    with st.form("baseline"):
        nd = st.date_input("Tanggal saldo awal", K.s2d(bd), format="DD-MM-YYYY")
        newb = {"date": None, "note": b.get("note", "")}
        labels = {"wk": "WEEK", "mtd": "MTD", "qtd": "QTD", "ytd": "YTD"}
        for p in K.PERIODS:
            st.markdown(f"**{labels[p]}** ({K.period_label(p, nd)})")
            cols = st.columns(4)
            pb = b.get(p, {})
            newb[p] = {}
            for i, f in enumerate(("target", "sales", "ly") + (("lm",) if p == "mtd" else ())):
                v = cols[i].text_input(f"{labels[p]} {f.upper()}", K.rp(pb.get(f, 0)),
                                       key=f"b_{p}_{f}")
                newb[p][f] = K.parse_amount(v) or 0
        st.markdown("**Data harian pada tanggal saldo awal** (untuk laporan tanggal itu & pembanding LM)")
        brec = db["days"].get(bd, {})
        cols = st.columns(4)
        fields = [("target", "Target"), ("sales", "Sales"), ("ly_manual", "Sales LY"),
                  ("traffic", "Traffic"), ("trx", "Trx"), ("qty", "Qty"), ("fw_unit", "FW Unit"),
                  ("crep_unit", "Crep Unit")]
        day = {}
        for i, (f, lab) in enumerate(fields):
            v = cols[i % 4].text_input(lab, K.rp(brec.get(f) or 0), key=f"bd_{f}")
            day[f] = K.parse_amount(v) or 0
        cols = st.columns(3)
        cp = brec.get("cat_pct") or {}
        pct = {}
        for i, k in enumerate(K.CATS):
            pct[k] = cols[i].number_input(f"Kontribusi {k} %", 0, 100, int(cp.get(k, 0)),
                                          key=f"bp_{k}")
        sure = st.checkbox("Saya yakin mengubah saldo awal")
        if st.form_submit_button("💾 Simpan saldo awal", disabled=False):
            if not sure:
                st.error("Centang konfirmasi dulu.")
            else:
                newb["date"] = K.d2s(nd)
                rec = K.new_day_record()
                rec.update(day, cat_amt={}, cat_pct=pct,
                           sources=[{"kind": "saldo_awal", "name": "input manual"}])
                if bd != newb["date"] and bd in db["days"] and db["days"][bd].get("is_baseline"):
                    db["days"][bd]["is_baseline"] = False
                K.set_baseline(db, newb, rec)
                st.toast("Saldo awal tersimpan")
                st.rerun()

    st.divider()
    st.subheader("Backup & restore")
    c = st.columns(2)
    c[0].download_button("⬇️ Download backup database (kpi_db.json)",
                         json.dumps(db, ensure_ascii=False, indent=1).encode("utf-8"),
                         file_name=f"kpi_db_backup_{dt.date.today():%Y%m%d}.json",
                         mime="application/json")
    c[0].caption(f"Backup otomatis setiap simpan: `{K.BACKUP_DIR}` "
                 f"({len(list(K.BACKUP_DIR.glob('*.json')))} file, maks {K.MAX_BACKUPS}).")
    rf = c[1].file_uploader("Restore dari backup (.json)", type=["json"], key="restore")
    if rf is not None:
        sure = c[1].checkbox("Saya yakin menimpa database dengan backup ini")
        if c[1].button("♻️ Restore", disabled=not sure):
            try:
                K.restore_db(rf.getvalue())
                st.toast("Database dipulihkan")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                c[1].error(f"Gagal: {e}")


# ================================================================== main
def main() -> None:
    db = K.load_db()
    draft = K.load_draft()
    with st.sidebar:
        st.markdown(f"## 📊 KPI Closing · {db['settings'].get('store', 'MKG')}")
        page = st.radio("Menu", ["🧾 Closing Harian", "📆 Data LY", "📚 Riwayat & Log",
                                 "⚙️ Pengaturan"], label_visibility="collapsed")
        last = last_closing(db)
        st.divider()
        st.caption(f"Closing terakhir: **{fd(last) if last else '-'}**")
        st.caption(f"Saldo awal: **{fd(db['baseline']['date'])}**")
        st.caption(f"Data LY: **{len(db['ly_daily'])} hari**")
        pend = sorted({f["date"] for f in draft["files"]})
        if pend:
            st.caption("Draft belum disimpan: " + ", ".join(fd(x) for x in pend))
        st.caption(f"LY: {K.LY_MODES[db['settings'].get('ly_mode', 'calendar')]}")
    if page.startswith("🧾"):
        page_closing(db, draft)
    elif page.startswith("📆"):
        page_ly(db)
    elif page.startswith("📚"):
        page_history(db)
    else:
        page_settings(db)


main()
