@echo off
REM ==================================================================
REM  KPI CLOSING MKG - INSTALLER (sekali jalan)
REM  Semua dipasang di folder ini (runtime\). Tidak mengubah Python,
REM  PATH, registry, atau setting bawaan PC.
REM ==================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title KPI CLOSING MKG - INSTALL

set "ROOT=%~dp0"
set "RT=%ROOT%runtime"
set "PYDIR=%RT%\python"
set "PY=%PYDIR%\python.exe"
set "PYVER=3.12.10"
set "PIP_CACHE_DIR=%RT%\pip-cache"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "PIP_NO_WARN_SCRIPT_LOCATION=1"
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"

set "ARCH=amd64"
if /i "%PROCESSOR_ARCHITECTURE%"=="x86" if not defined PROCESSOR_ARCHITEW6432 set "ARCH=win32"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "ARCH=arm64"

echo.
echo  ================================================
echo    KPI CLOSING MKG  -  INSTALL
echo    Folder : %ROOT%
echo  ================================================
echo.

if not exist "%RT%" mkdir "%RT%"

REM ---------- 1. Python portable (embeddable) ----------
if exist "%PY%" (
  echo [1/4] Python portable sudah ada, dilewati.
  goto :pip
)
echo [1/4] Mengunduh Python %PYVER% portable ^(%ARCH%^) ...
set "ZIP=%RT%\python-embed.zip"
set "URL=https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-embed-%ARCH%.zip"
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri '%URL%' -OutFile '%ZIP%'"
if errorlevel 1 goto :fail_download
if not exist "%ZIP%" goto :fail_download

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Expand-Archive -Force -Path '%ZIP%' -DestinationPath '%PYDIR%'"
if errorlevel 1 goto :fail_extract
del /q "%ZIP%" >nul 2>&1

REM aktifkan "import site" agar pip / site-packages bisa dipakai
for %%F in ("%PYDIR%\python*._pth") do (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "(Get-Content -LiteralPath '%%~fF') -replace '^#\s*import site','import site' | Set-Content -LiteralPath '%%~fF' -Encoding ASCII"
)
if not exist "%PY%" goto :fail_extract

:pip
REM ---------- 2. pip ----------
"%PY%" -m pip --version >nul 2>&1
if not errorlevel 1 (
  echo [2/4] pip sudah ada, dilewati.
  goto :deps
)
echo [2/4] Memasang pip ke Python portable ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile '%RT%\get-pip.py'"
if errorlevel 1 goto :fail_download
"%PY%" "%RT%\get-pip.py" --no-warn-script-location
if errorlevel 1 goto :fail_pip
del /q "%RT%\get-pip.py" >nul 2>&1

:deps
REM ---------- 3. library ----------
echo [3/4] Memasang library (streamlit, pandas, pypdfium2, openpyxl) ...
"%PY%" -m pip install --upgrade pip --no-warn-script-location
"%PY%" -m pip install -r "%ROOT%requirements.txt" --no-warn-script-location
if errorlevel 1 goto :fail_pip

REM ---------- 4. cek ----------
echo [4/4] Mengecek instalasi ...
"%PY%" -c "import streamlit, pandas, pypdfium2, openpyxl; print('      streamlit', streamlit.__version__, '| pandas', pandas.__version__)"
if errorlevel 1 goto :fail_pip
"%PY%" -c "import sys; sys.path.insert(0, r'%ROOT%.'); import kpi_engine as k; k.load_db(); print('      database :', k.DB_PATH)"
if errorlevel 1 goto :fail_pip

echo.
echo  ================================================
echo    INSTALL SELESAI.
echo    Jalankan  run.bat  untuk membuka aplikasi.
echo  ================================================
echo.
pause
exit /b 0

:fail_download
echo.
echo  [GAGAL] Tidak bisa mengunduh file. Cek koneksi internet / proxy,
echo          lalu jalankan install.bat lagi.
goto :end_fail
:fail_extract
echo.
echo  [GAGAL] Ekstrak Python portable gagal. Hapus folder "runtime" lalu ulangi.
goto :end_fail
:fail_pip
echo.
echo  [GAGAL] Pemasangan library gagal. Cek koneksi internet lalu ulangi.
echo          Jika tetap gagal, hapus folder "runtime" dan jalankan ulang.
goto :end_fail
:end_fail
echo.
pause
exit /b 1
