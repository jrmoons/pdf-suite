@echo off
rem Lanceur PDF Suite (application PDF de bureau) utilisable depuis n'importe quel dossier.
set "PYW=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=%~dp0.venv\Scripts\python.exe"
"%PYW%" -c "import sys; sys.path.insert(0, r'%~dp0.'); from pdfsuite.main import main; main()" %*
