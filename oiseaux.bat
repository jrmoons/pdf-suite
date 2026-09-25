@echo off
rem Lanceur du generateur d oiseaux animes (utilise le .venv du projet).
set "PYW=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=%~dp0.venv\Scripts\python.exe"
"%PYW%" "%~dp0oiseaux\oiseaux.py" %*
