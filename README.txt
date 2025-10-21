Projektüberblick

Lokal laufender FastAPI-Stack unter backend/src/app mit SQLite/SQLModel, konfiguriert über backend/src/app/core/config.py:1.
API-Einstiegspunkt backend/src/app/main.py:1 bündelt Router für Gesundheit, Foods, Meals, Wearables, Advisor, Summary, Demo-UI, Lookup und optionale Speech/NLP-Ingest.
Struktur & Schlüsselmodule

backend/src/app/core/
config.py:1 lädt .env, definiert Settings (App-Metadaten, DB-URL, Advisor-LLM-Flag).
database.py:1 initialisiert SQLModel-Engine, Session-Dependency und Tabellenaufbau.
backend/src/app/models/ enthält SQLModel-Datenklassen (Foods, Meals, Wearables, optionale Recipes) für DB-Schema.
backend/src/app/routers/
health.py:1 liefert /health-Ping.
foods.py:1 stellt /foods/search|detail für Lebensmittelbasis bereit.
foods_lookup.py:1 bietet /foods/lookup|confirm gegen FoodData Central / OpenFoodFacts mit Synonympflege.
meals.py:1 deckt CRUD/Reporting für tägliche Meal-Items (/meals/item|day|summary_by_food).
meals_ingest.py:1 verarbeitet Batch-Ingest (/meals/ingest) mit Fuzzy-Matching & Pending-Speicher.
wearables.py:1 verwaltet /wearables/daily (Upsert + Listing) zur Aktivitätsintegration.
summary.py:1 erzeugt /summary/day|week mit Trendanalyse und Kalorienziel-Heuristik.
advisor.py:1 bündelt Coach-Funktionen /advisor/gaps|recommendations|chat|compose, integriert lokale LLMs und Rezeptbibliothek.
ingest.py:1 (optional) transkribiert Audio via faster-whisper und legt Meals über LLM-Parsing an (/ingest/voice_meal).
demo_ui.py:1 rendert HTML-Demo (/demo).
backend/src/app/utils/
nutrition.py:1 Hilfsfunktionen zur Makroberechnung.
llm.py:1 abstrahiert lokale LLM-Aufrufe (JSON-Parsing etc.).
validators.py:1 enthält sichere Konvertierungen/Clamp-Logik für Advisor.
backend/src/app/web/templates/demo.html:1 Single-Page-Demo für Compose-/Chat-Flows und Meal-Übernahme.
backend/scripts/
seed_smoothie_bowls.py:1 füllt Foods/Recipes per Script (Nutzung über aktivierte venv).
backend/tests/unit/test_llm_utils.py:1 prüft JSON-Ausgabe/Parsing des LLM-Helfers.
Infrastruktur: .vscode/launch.json:1 startet uvicorn samt venv-Setup; Datenbasis backend/data/foods.csv.
Wichtige Schnittstellen

REST-Endpoints via FastAPI (obige Router) mit SQLModel-Sessions (get_session aus database.py).
Lokales LLM: Standard-Ollama (HTTP oder CLI) plus optionales llama.cpp-In-Process (advisor.py:120 ff), konfigurierbar über .env.
Speech-Ingest: ingest.py nutzt faster_whisper.WhisperModel, benötigt Zusatzpaket.
Externe Daten: USDA FoodData Central (API-Key) und OpenFoodFacts in foods_lookup.py.
Demo-Frontend kommuniziert per Fetch mit /advisor/compose, /advisor/chat, /meals/item, /summary/day etc.
Statushinweis

Backend funktionsfähig, SQLite-Datenbank inklusive automatischem Schemaaufbau.
Advisor & Compose laufen mit heuristischem Fallback; LLAMA/Ollama optional.
Wearable-Upserts vorhanden, externe Integrationen noch manuell.
Voice-Ingest und RAG in experimentellem Stadium; vollständiges Frontend fehlt.