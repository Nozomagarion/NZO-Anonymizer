@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Anonymizer - moteur IA (laisser ouvert)
if not exist "venv\Scripts\python.exe" goto noinstall
"venv\Scripts\python.exe" anonymizer_engine.py serve
pause
exit /b 0
:noinstall
echo Lancez d abord installer.bat
pause
exit /b 1
