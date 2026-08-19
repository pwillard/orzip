@echo off
setlocal
cd /d "%~dp0"
set "SOURCE_DATE_EPOCH=946684800"
set "PYTHONHASHSEED=0"

set "PYTHON="
python -c "import PyInstaller" >nul 2>nul
if not errorlevel 1 set "PYTHON=python"
if not defined PYTHON (
    py -3 -c "import PyInstaller" >nul 2>nul
    if not errorlevel 1 set "PYTHON=py -3"
)
if not defined PYTHON (
    echo ERROR: No Python interpreter with PyInstaller was found.
    echo Install it with: python -m pip install pyinstaller
    exit /b 1
)

set "TMPROOT=%TEMP%\orzip-pyinstaller-%RANDOM%-%RANDOM%"
set "TMPDIST=%TMPROOT%\dist"
set "TMPWORK=%TMPROOT%\work"
set "TMPSPEC=%TMPROOT%\spec"
mkdir "%TMPDIST%" "%TMPWORK%" "%TMPSPEC%" >nul 2>nul

echo Building ORZIP executable...
%PYTHON% -m PyInstaller --noconfirm --clean --onefile --console --name orzip --hidden-import orzip_defs --paths "%CD%" --distpath "%TMPDIST%" --workpath "%TMPWORK%" --specpath "%TMPSPEC%" orzip.py
if errorlevel 1 (
    echo ERROR: PyInstaller build failed. Build files remain at:
    echo %TMPROOT%
    exit /b 1
)

if not exist "DIST" mkdir "DIST"
copy /Y "%TMPDIST%\orzip.exe" "DIST\orzip.exe" >nul
if errorlevel 1 (
    echo ERROR: Could not replace DIST\orzip.exe. It may be open or locked.
    echo Fresh executable: %TMPDIST%\orzip.exe
    exit /b 1
)

"DIST\orzip.exe" --version
if errorlevel 1 (
    echo ERROR: Built executable failed its version smoke test.
    exit /b 1
)

rmdir /S /Q "%TMPROOT%" >nul 2>nul
echo Built: %CD%\DIST\orzip.exe
exit /b 0
