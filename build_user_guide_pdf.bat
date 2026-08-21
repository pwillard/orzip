@echo off
setlocal
cd /d "%~dp0"

set "PYTHON="
python -c "import reportlab, pypdf" >nul 2>nul
if not errorlevel 1 set "PYTHON=python"
if not defined PYTHON (
    py -3 -c "import reportlab, pypdf" >nul 2>nul
    if not errorlevel 1 set "PYTHON=py -3"
)
if not defined PYTHON (
    echo ERROR: No Python interpreter with reportlab and pypdf was found.
    echo Install them with: python -m pip install reportlab pypdf
    exit /b 1
)

if not exist "DIST\DOCS" mkdir "DIST\DOCS"
%PYTHON% tools\build_user_guide_pdf.py USER_GUIDE.md -o DIST\DOCS\ORZIP_EXE_User_Guide.pdf
if errorlevel 1 exit /b 1

copy /Y "USER_GUIDE.md" "DIST\DOCS\USER_GUIDE.md" >nul
if errorlevel 1 (
    echo ERROR: Could not replace DIST\DOCS\USER_GUIDE.md. It may be open or locked.
    exit /b 1
)
copy /Y "USER_GUIDE.md" "DIST\DOCS\ORZIP_EXE_User_Guide.md" >nul
if errorlevel 1 (
    echo ERROR: Could not replace DIST\DOCS\ORZIP_EXE_User_Guide.md. It may be open or locked.
    exit /b 1
)

%PYTHON% -c "from pypdf import PdfReader; p='DIST/DOCS/ORZIP_EXE_User_Guide.pdf'; r=PdfReader(p); text='\n'.join((x.extract_text() or '') for x in r.pages); assert 'ORZIP 1.0.4 User Guide' in text; assert 'model.s.bak.1' in text; print(f'Verified PDF: {len(r.pages)} pages, {len(text)} extracted characters')"
if errorlevel 1 exit /b 1

echo Built: %CD%\DIST\DOCS\ORZIP_EXE_User_Guide.pdf
exit /b 0
