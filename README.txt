NutriTrack – Intelligenter Ernährungs- & Fitness-Tracker mit KI-Unterstützung

Überblick
NutriTrack ist ein KI-basiertes Ernährungssystem, das deine täglichen Mahlzeiten, Aktivitäten und Gesundheitsdaten automatisch analysiert.
Es hilft dir, deine individuellen Ernährungsziele zu erreichen – egal ob Muskelaufbau, Fettverlust oder Gewichtserhalt.

Du kannst einfach ins Handy sprechen, und die App erkennt, was du gegessen hast, berechnet die Nährwerte und empfiehlt passende Mahlzeiten oder Supplements.
Optional synchronisiert sich das System mit Strava oder deiner Fitnessuhr, um deine Aktivität und Kalorienbilanz dynamisch anzupassen.

Hauptfunktionen

Sprachbasierte Ernährungserfassung (Speech-to-Text und KI-Parsing)

Automatische Nährwertberechnung über eine Food-Datenbank

Dynamische Zielanpassung je nach Aktivität (z. B. Strava, Fitnessuhr)

Empfehlungen für Makro- und Mikronährstoffe

Personalisierte Vorschläge nach Präferenzen und Zielen

Optionale Bluttest-Analyse für individuelle Ernährungsempfehlungen

Lokale Ausführung mit Ollama und FastAPI

Projektstruktur

NutriTrack/
│
├── backend/ FastAPI-Server (Python, Datenbank, Logik)
│ ├── app/
│ │ ├── main.py
│ │ ├── db.py
│ │ ├── routers/
│ │ └── models/
│ └── scripts/
│
├── mobile/ React Native / Expo App (Frontend)
│
├── data/ CSV-Daten (Foods, Nutrients, Recipes)
│
├── infra/ Docker, Deployment, Configs
│
└── README.md

Setup-Schritte

Git und Python vorbereiten
Stelle sicher, dass Git und Python 3.11 oder höher installiert sind.
Prüfen:
git --version
python --version

Virtuelle Umgebung und Abhängigkeiten
cd backend
python -m venv .venv
.venv\Scripts\activate (Windows)
oder
source .venv/bin/activate (macOS/Linux)
pip install fastapi uvicorn[standard]

Server starten
uvicorn app.main:app --reload
Browser öffnen: http://127.0.0.1:8000/health

Erwartete Ausgabe: {"ok": true, "message": "NutriTrack backend läuft!"}

Daten hinzufügen
Später werden Food-CSV-Dateien, Rezepte und Wearable-Daten importiert.
Beispiele: data/foods.csv, data/nutrients.csv, data/recipes.csv

Geplante Module

Database & Models: Foods, Nutrients, Wearables, Biomarker

Voice Input: Speech-to-Text (Whisper / Faster-Whisper)

AI Parser: LLM via Ollama (Llama 3.1)

Recommendation Engine: Zielgesteuerte Vorschläge

Integration: Strava, Apple Health, Google Fit, Garmin

Tech-Stack
Backend: Python, FastAPI
KI-Modelle: Llama 3.1 (Ollama), Whisper
Frontend: React Native / Expo
Datenbank: SQLite → PostgreSQL
Integration: Strava API, HealthKit, Health Connect
Deployment: Docker Compose

Projektziel
Ein funktionsfähiger Prototyp, der Sprach-Logging, Nährwertanalyse und smarte Empfehlungen in Echtzeit ermöglicht – komplett lokal lauffähig.

Autor
Name: [dein Name]
Studiengang: Duale Angewandte Informatik
Projektmodul: KI-Systemintegration & Sprachmodelle