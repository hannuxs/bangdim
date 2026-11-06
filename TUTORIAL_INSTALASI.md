# KPI Closing Harian MKG: Instalasi sampai Server Running

Aplikasi web lokal (Streamlit) untuk closing KPI harian. Anda upload file sales, traffic, dan trx, lalu isi target. Aplikasi menghitung Daily, WK, MTD, QTD, dan YTD secara otomatis, menyimpan semuanya, dan membuat teks laporan siap kirim ke WA.

> **Tidak mengubah sistem PC.** Python portable dan semua library dipasang di dalam folder ini (`runtime\`). Tidak ada perubahan ke PATH, registry, atau Python bawaan. Untuk menghapus aplikasi, cukup hapus foldernya.

---

## 1. Isi folder

| File / folder | Fungsi |
|---|---|
| `install.bat` | **Install sekali jalan.** Mengunduh Python portable dan library ke `runtime\` |
| `run.bat` | **Menjalankan server** dan membuka browser otomatis |
| `app.py` | Tampilan aplikasi (Streamlit) |
| `kpi_engine.py` | Rumus dan penjumlahan KPI, penyimpanan, backup, log |
| `parsers.py` | Pembaca file PDF / CSV / XLSX |
| `requirements.txt` | Daftar library |
| `.streamlit\config.toml` | Setting server (port 8501, hanya bisa diakses dari PC ini) |
| `data\` | **Semua data Anda** (dibuat otomatis, lihat bagian 6) |
| `runtime\` | Python portable dan library (dibuat oleh install.bat) |

## 2. Syarat

- Windows 10/11 64-bit. Tidak perlu hak Administrator.
- Internet **hanya saat install**, sekitar 150 MB unduhan. Untuk pemakaian harian tidak perlu internet.
- Browser apa saja (Chrome / Edge).

## 3. Install (sekali saja)

1. Buka folder `D:\bangdim`.
2. **Double-click `install.bat`.**
3. Tunggu sampai muncul tulisan:
   ```
   INSTALL SELESAI.
   Jalankan  run.bat  untuk membuka aplikasi.
   ```
   Waktunya sekitar 2–5 menit, tergantung kecepatan internet. Tekan tombol apa saja untuk menutup jendela.

Yang dikerjakan `install.bat`:

| Langkah | Isi |
|---|---|
| [1/4] | Unduh **Python 3.12 portable** (embeddable, resmi python.org) ke `runtime\python` |
| [2/4] | Pasang `pip` khusus untuk Python portable tersebut |
| [3/4] | Pasang library: streamlit, pandas, pypdfium2 (pembaca PDF), openpyxl (Excel). Cache pip juga disimpan di `runtime\pip-cache` |
| [4/4] | Cek instalasi dan buat database awal `data\kpi_db.json` berisi **saldo awal dari laporan 05-11-2026** |

`install.bat` aman dijalankan ulang. Langkah yang sudah selesai akan dilewati, dan library di-update bila perlu.

> Jika Windows SmartScreen muncul ("Windows protected your PC"), klik **More info → Run anyway**. Ini wajar untuk file .bat buatan sendiri.

## 4. Menjalankan server (setiap hari)

1. **Double-click `run.bat`.**
2. Jendela hitam muncul:
   ```
   KPI CLOSING MKG - SERVER RUNNING
   Buka di browser : http://127.0.0.1:8501
   ```
3. Browser terbuka otomatis ke aplikasi. Kalau tidak terbuka, ketik `http://127.0.0.1:8501` (atau `http://localhost:8501`) di browser.
4. **Jangan tutup jendela hitam** selama aplikasi dipakai.
5. Untuk mematikan server, tutup jendela hitam atau tekan `Ctrl + C`.

Kalau `run.bat` di-klik lagi saat server masih jalan, `run.bat` tidak menyalakan server kedua. Browser langsung dibuka ke server yang sudah berjalan.

## 5. Cara pakai

### 5.1 Closing Harian (menu 🧾)
1. **Tanggal closing** terisi otomatis: tanggal file yang di-upload, atau sehari setelah closing terakhir.
2. **Upload file.** Bisa beberapa file sekaligus, termasuk drag & drop:
   - **REPORT SALES PER ITEM** (PDF/CSV) menghasilkan Sales (Total Payment), Qty, FW Unit, Crep Unit, dan kontribusi FW/Text/ACC.
   - **Daily Cashier Report** (PDF/CSV) menghasilkan Trx (jumlah nomor order SJ/CJ unik).
   - **Traffic sensor** (CSV/PDF dengan kolom jam dan baris "Total Daily") menghasilkan Traffic (jam 10:00–22:00).
   - **CSV / PDF manual traffic & trx**, contoh CSV:
     ```
     tanggal,traffic,trx
     06-11-2026,812,95
     ```
   - Tanggal dibaca dari isi file (PERIODE / Periode / kolom tanggal) atau dari nama file. File tanpa tanggal ikut tanggal file lain yang di-upload bersamaan.
   - **Tanggal sama di-upload lebih dari 1 kali → file TERAKHIR yang dipakai** (status ✅ DIPAKAI). File lama tetap tersimpan sebagai arsip.
3. **Isi Target hari ini.** Format bebas: `134.630.000`, `134630000`, atau `134,630,000`.
4. Cek angka **Traffic, Trx, Sales LY, dan Sales LM**. Semuanya bisa dikoreksi manual. Angka dari file juga bisa dikoreksi di bagian "Angka dari file Sales per Item".
5. Lihat **Preview laporan** dan peringatan (LY kosong, hari terlewat, dll).
6. Klik **✅ OK & SAVE**. Setelah disimpan:
   - Total WK, MTD, QTD, dan YTD langsung ter-update.
   - Laporan tersimpan di `data\laporan\KPI_MKG_YYYY-MM-DD.txt`.
   - Klik ikon **copy** di pojok kanan kotak laporan untuk menempel ke WA.
   - Tanggal pindah otomatis ke hari berikutnya.
7. Tanggal yang sudah disimpan bisa di-closing ulang. Data akan **DITIMPA, tidak dijumlah dua kali**. Ada konfirmasi sebelum menimpa.

### 5.2 Data LY (menu 📆)
- Upload LY harian sekali untuk setahun. Format yang diterima:
  - **CSV/XLSX** dengan kolom `date` dan `sales`. Template 1 tahun bisa diunduh dari tombol **Template CSV LY**.
  - **REPORT SALES PER ITEM** periode 1 hari. Boleh banyak file sekaligus.
- Klik **OK & SAVE**. Data LY juga bisa diedit langsung di tabel.
- Catatan: `FILE LY (1).pdf` yang ada sekarang adalah periode **01-01-2025 s/d 31-12-2025 dalam 1 laporan** (total Rp 59.508.777.248). File ini tidak bisa dipecah per hari, jadi perlu file LY **per hari**.
- Mulai November 2027, LY otomatis diambil dari riwayat closing aplikasi ini sendiri.

### 5.3 Riwayat & Log (menu 📚)
- Tabel semua closing beserta seluruh angka periodenya. Bisa diunduh sebagai CSV / Excel.
- Laporan tanggal mana pun bisa dilihat dan diunduh ulang, atau dihapus dengan konfirmasi.
- **Log aktivitas** mencatat setiap SAVE / TIMPA / HAPUS / import LY / ubah saldo awal, lengkap dengan total periode **sebelum dan sesudah** penjumlahan.

### 5.4 Pengaturan (menu ⚙️)
- Kode store.
- **Pembanding LY**:
  - "Tanggal sama" (default): 06-11-2026 dibanding 06-11-2025.
  - "Hari sama / 364 hari": Jumat dibanding Jumat.
- **Saldo awal**: titik awal penjumlahan (default posisi 05-11-2026). Ubah hanya bila angkanya salah.
- **Backup / Restore** database.

## 6. Rumus & aturan yang dipakai

| KPI | Rumus |
|---|---|
| Ach% | Sales ÷ Target − 1 (beserta selisih Rp) |
| LFL% | Sales ÷ Sales LY − 1 |
| ATV | Sales ÷ Trx |
| UPT | Qty ÷ Trx (2 desimal) |
| CR | Trx ÷ Traffic |
| SR | FW Unit : Crep Unit, **dibulatkan** (90:10 menjadi 9:1, 87:10 menjadi 9:1) |
| Kontribusi | Sales FW / Textile / ACC ÷ total ketiganya, dibulatkan dengan jumlah pasti 100% |
| WK / MTD / QTD / YTD Target, Sales, LY | Saldo awal + jumlah semua closing harian dalam periode |
| MTD vs Target | Sales MTD berjalan ÷ Target MTD berjalan |
| Acv vs LM | Sales MTD ÷ Sales bulan lalu sampai tanggal yang sama |

Aturan lainnya:
- **Reset periode:**
  - WK = minggu ISO Senin–Minggu. Senin 09-11-2026 menjadi **WK 46** dan mulai dari 0.
  - MTD reset tiap tanggal 1.
  - QTD reset tiap kuartal: Jan–Mar, Apr–Jun, Jul–Sep, Okt–Des.
  - YTD reset tiap 1 Januari.
- **Pembulatan:** persen tanpa koma (0,5 dibulatkan ke atas), rupiah dengan titik ribuan.
- **Paper bag / Marketing Goods** tidak dihitung di Qty.
- **Crep Unit** = artikel dengan kata "CREP" utuh. Celana "CREPE" tidak ikut dihitung.

## 7. Lokasi data & backup

| Lokasi | Isi |
|---|---|
| `data\kpi_db.json` | Database utama: saldo awal, closing harian, LY, setting |
| `data\backup\` | Backup otomatis **setiap kali simpan** (90 terakhir) |
| `data\laporan\` | Teks laporan WA per tanggal |
| `data\uploads\` | Arsip semua file yang pernah di-upload, per tanggal |
| `data\riwayat_closing.csv` | Ringkasan semua closing (bisa dibuka di Excel) |
| `data\log_aktivitas.jsonl` | Log semua aktivitas |
| `data\draft.json` | Upload yang belum di-SAVE. Tetap ada walau browser / PC ditutup |

**Pindah PC:** copy seluruh folder `D:\bangdim` (termasuk `runtime\`) ke PC lain lalu jalankan `run.bat`. Cara lain: copy folder `data\` saja, lalu jalankan `install.bat` di PC baru.

## 8. Masalah umum

| Masalah | Solusi |
|---|---|
| `[GAGAL] Tidak bisa mengunduh` saat install | Cek internet / proxy kantor, lalu jalankan `install.bat` lagi |
| Install terhenti di tengah | Hapus folder `runtime\`, jalankan `install.bat` lagi |
| `Aplikasi belum ter-install` saat run | Jalankan `install.bat` dulu |
| Browser tidak terbuka otomatis | Buka manual `http://127.0.0.1:8501` |
| Port 8501 dipakai program lain | Ganti `PORT=8501` di `run.bat` dan `port = 8501` di `.streamlit\config.toml` ke angka lain (mis. 8510) |
| Halaman blank / error setelah update file | Tutup jendela hitam, jalankan `run.bat` lagi, lalu refresh browser (F5) |
| PDF tidak terbaca ("hasil scan / gambar") | Minta file PDF asli dari sistem (bukan hasil scan), atau isi angka manual |
| Ingin dibuka dari HP di WiFi yang sama | Di `.streamlit\config.toml` ubah `address = "0.0.0.0"`. Windows akan menanyakan izin firewall, dan izin ini **mengubah setting firewall** PC. Buka `http://IP-PC:8501` dari HP |
| Hapus aplikasi | Tutup server, hapus folder `D:\bangdim`. Tidak ada sisa di sistem |
