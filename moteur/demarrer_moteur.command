#!/bin/sh
# Lance le moteur IA d'Anonymizer ; laissez cette fenêtre ouverte.
cd "$(dirname "$0")" || exit 1
[ -x venv/bin/python ] || { echo "Lancez d'abord installer.sh"; exit 1; }
exec venv/bin/python anonymizer_engine.py serve
