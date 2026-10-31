@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Anonymizer - installation du moteur
echo === Anonymizer pour EffectCraft : installation du moteur IA ===
echo.
set "PY=py -3"
%PY% --version >nul 2>nul
if errorlevel 1 set "PY=python"
%PY% --version
if errorlevel 1 goto nopython
if not exist "venv\Scripts\python.exe" %PY% -m venv venv
if not exist "venv\Scripts\python.exe" goto novenv
"venv\Scripts\python.exe" -m pip install --upgrade pip
"venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 "venv\Scripts\python.exe" -m pip install numpy opencv-python onnx onnxruntime
echo.
echo Telechargement des modeles IA, environ 1,1 Go, une seule fois...
"venv\Scripts\python.exe" anonymizer_engine.py setup
echo.
echo Installation terminee. Lancez demarrer_moteur.bat avant d utiliser le panneau.
pause
exit /b 0
:nopython
echo Python 3.10 a 3.13 est introuvable.
echo Installez-le depuis https://www.python.org/downloads/ en cochant "Add python.exe to PATH", puis relancez ce fichier.
pause
exit /b 1
:novenv
echo Impossible de creer l environnement Python dans ce dossier. Placez le dossier moteur dans Documents et relancez.
pause
exit /b 1
