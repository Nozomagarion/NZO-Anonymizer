#!/bin/sh
# Anonymizer pour EffectCraft : installation du moteur IA (macOS / Linux)
cd "$(dirname "$0")" || exit 1
PY=python3
command -v $PY >/dev/null 2>&1 || { echo "Python 3.10+ introuvable (https://www.python.org/downloads/)"; exit 1; }
[ -x venv/bin/python ] || $PY -m venv venv || exit 1
venv/bin/python -m pip install --upgrade pip
venv/bin/python -m pip install -r requirements.txt || exit 1
echo "Téléchargement des modèles IA (environ 1,1 Go, une seule fois)…"
venv/bin/python anonymizer_engine.py setup
echo "Installation terminée. Lancez demarrer_moteur.command (macOS) ou demarrer_moteur.sh."
