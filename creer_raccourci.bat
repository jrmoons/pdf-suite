@echo off
rem Construit PDFSuite.exe (si besoin) et cree un raccourci "PDF Suite" sur le Bureau.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creation de l'environnement virtuel .venv ...
    python -m venv .venv || goto :erreur
    ".venv\Scripts\pip" install -r requirements.txt || goto :erreur
)

if not exist "dist\PDFSuite.exe" (
    echo Construction de PDFSuite.exe, patientez 1 a 2 minutes ...
    ".venv\Scripts\pip" install pyinstaller || goto :erreur
    ".venv\Scripts\pyinstaller" --noconfirm --onefile --windowed --name PDFSuite launcher.py || goto :erreur
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$exe = Join-Path (Get-Location) 'dist\PDFSuite.exe';" ^
  "$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'PDF Suite.lnk';" ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk);" ^
  "$s.TargetPath = $exe; $s.WorkingDirectory = Split-Path $exe; $s.IconLocation = $exe; $s.Save();" ^
  "Write-Host ('Raccourci cree : ' + $lnk)" || goto :erreur

echo.
echo Termine. Double-cliquez sur "PDF Suite" sur votre Bureau.
pause
exit /b 0

:erreur
echo.
echo Une erreur est survenue, voir les messages ci-dessus.
pause
exit /b 1
