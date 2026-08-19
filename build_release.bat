@echo off
setlocal
cd /d "%~dp0"

call build_orzip_exe.bat
if errorlevel 1 exit /b 1

call build_user_guide_pdf.bat
if errorlevel 1 exit /b 1

copy /Y "README.md" "DIST\DOCS\README.md" >nul
if errorlevel 1 (
    echo ERROR: Could not replace DIST\DOCS\README.md. It may be open or locked.
    exit /b 1
)
copy /Y "README-ORZIP.md" "DIST\DOCS\README-ORZIP.md" >nul
if errorlevel 1 (
    echo ERROR: Could not replace DIST\DOCS\README-ORZIP.md. It may be open or locked.
    exit /b 1
)
copy /Y "USER_GUIDE.md" "DIST\DOCS\USER_GUIDE.md" >nul
if errorlevel 1 (
    echo ERROR: Could not replace DIST\DOCS\USER_GUIDE.md. It may be open or locked.
    exit /b 1
)
if exist "DIST\DOCS\ORZIP_Documentation.pdf" (
    del /Q "DIST\DOCS\ORZIP_Documentation.pdf" >nul 2>nul
    if exist "DIST\DOCS\ORZIP_Documentation.pdf" (
        echo ERROR: Could not remove stale DIST\DOCS\ORZIP_Documentation.pdf.
        exit /b 1
    )
)

set "PYTHON=python"
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PYTHON=py -3"
%PYTHON% tools\write_release_checksums.py DIST -o DIST\SHA256SUMS.txt
if errorlevel 1 exit /b 1

echo Release artifacts built under: %CD%\DIST
exit /b 0
