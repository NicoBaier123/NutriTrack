# Tests und TDD für NutriTrack

## Schnellstart

1) Umgebung einrichten (einmalig oder bei Änderungen an requirements):

- VS Code Task: "Setup venv & deps" oder
- PowerShell im Ordner `backend` ausführen: `scripts/bootstrap.ps1`

2) Tests ausführen:

- Im Ordner `backend`:

```
.\.venv\Scripts\python.exe -m pytest
```

Coverage ist aktiviert und zeigt fehlende Zeilen an.

## Struktur

- tests/unit: reine Funktionstests (z.B. `app.utils.nutrition`)
- tests/integration: API-Tests mit In-Memory/Temp-DB
- tests/e2e: oberflächliche Smoke-Tests

Fixtures in `tests/conftest.py` stellen eine isolierte SQLite-DB pro Test bereit und binden die echte FastAPI-App mit Dependency Override.

## TDD-Vorschlag

- Schreibe zuerst Unit-Tests für Berechnungslogik (z.B. Portionen -> Makros)
- Schreibe Integrationstests für Endpunkte (`/foods`, `/meals`), die diese Logik verwenden
- Implementiere dann nur so viel Code, bis die Tests grün sind
- Refaktorierungen absichern, indem Tests unverändert grün bleiben

## Konventionen

- Rundungen nur an UI/DTO-Grenzen, intern mit vollen Fließkommazahlen arbeiten
- Negative Grammzahlen werden auf 0 geklemmt
- Fehlende/None-Werte werden als 0 interpretiert

## CI

Ein GitHub Actions Workflow kann leicht ergänzt werden, um `pytest` mit `--cov` in einer 3.11/3.12-Matrix laufen zu lassen.