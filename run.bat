@echo off
REM ==================================================================
REM  KPI CLOSING MKG - JALANKAN SERVER
REM  Membuka aplikasi di browser: http://localhost:8501
REM  Tutup jendela hitam ini (atau tekan Ctrl+C) untuk mematikan server.
REM ==================================================================
setlocal EnableExtensions
cd /d "%~dp0"
title KPI CLOSING MKG - SERVER (jangan ditutup selama dipakai)

set "PY=%~dp0runtime\python\python.exe"
set "PORT=8501"
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "STREAMLIT_BROWSER_GATHER_USAGE_STATS=false"

if not exist "%PY%" (
  echo.
  echo  [!] Aplikasi belum ter-install. Jalankan install.bat dulu.
  echo.
  pause
  exit /b 1
)
"%PY%" -c "import streamlit, pandas, pypdfium2, openpyxl" >nul 2>&1
if errorlevel 1 (
  echo.
  echo  [!] Library belum lengkap. Jalankan install.bat lagi.
  echo.
  pause
  exit /b 1
)

REM ---- server sudah jalan? cukup buka browser
netstat -ano -p TCP | findstr /r /c:"127.0.0.1:%PORT% .*LISTENING" /c:"0.0.0.0:%PORT% .*LISTENING" >nul
if not errorlevel 1 (
  echo  Server sudah berjalan di port %PORT%. Membuka browser ...
  start "" "http://127.0.0.1:%PORT%"
  timeout /t 3 >nul
  exit /b 0
)

echo.
echo  ================================================
echo    KPI CLOSING MKG - SERVER RUNNING
echo    Buka di browser : http://127.0.0.1:%PORT%  (atau http://localhost:%PORT%)
echo    Data tersimpan  : %~dp0data
echo    Matikan server  : tutup jendela ini / Ctrl+C
echo  ================================================
echo.

REM ---- buka browser otomatis begitu server siap
start "" /b powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "for($i=0;$i -lt 120;$i++){try{$c=New-Object Net.Sockets.TcpClient('127.0.0.1',%PORT%);$c.Close();Start-Process 'http://127.0.0.1:%PORT%';break}catch{Start-Sleep -Milliseconds 500}}"

"%PY%" -m streamlit run "%~dp0app.py" --server.port %PORT%

echo.
echo  Server berhenti.
pause
