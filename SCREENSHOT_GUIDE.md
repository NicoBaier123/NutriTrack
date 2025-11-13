# Screenshot-Guide - Wo welche Screenshots benötigt werden

**Erstellt:** 10. November 2025  
**Zweck:** Übersicht aller Platzhalter für Screenshots in den Dokumenten

---

## Übersicht

In den überarbeiteten Dokumenten wurden **Platzhalter** für Screenshots markiert. Diese Datei listet alle Stellen auf, wo Screenshots eingefügt werden sollten.

**Format der Platzhalter:**
```markdown
[SCREENSHOT: Beschreibung was hier gezeigt werden soll]
```

---

## 1. concept_draft.md (Konzeptentwurf)

### Screenshot 1: Systemarchitektur-Diagramm HAB
**Location:** Seite 3, Section 1.2  
**Platzhalter:** `[SCREENSHOT: Systemarchitektur-Diagramm mit allen Komponenten]`  
**Was zeigen:**
- Gesamtübersicht der RAG-Pipeline
- Komponenten: QueryPreprocessor, RecipeIndexer, PostProcessor, Embedding Service
- Datenfluss zwischen Komponenten
- Optional: Nutze das existierende Flowchart aus `fchart.drawio`

**Empfehlung:** Draw.io Diagramm exportieren als PNG und hier einfügen

---

### Screenshot 2: RecipeIndexer Cache-Statistiken HAB
Section 3.2.2
**Location:** Seite 11, Section 6.1  
**Platzhalter:** `[SCREENSHOT: RecipeIndexer Cache-Statistiken aus Datenbank]`  
**Was zeigen:**
- SQL-Query: `SELECT COUNT(*) FROM recipe_embeddings;`
- Cache-Hit-Rate Statistiken
- Beispiel-Embedding aus Datenbank (verkürzt)

**Wie erstellen:**
```bash
cd backend
python -c "
from app.core.database import get_session
from sqlmodel import select, text

session = next(get_session())
count = session.exec(text('SELECT COUNT(*) FROM recipe_embeddings')).first()
print(f'Gecachte Embeddings: {count[0]}')
"
```

Screenshot des Terminal-Outputs machen.

---

### Screenshot 3: Cache-Performance-Vergleich HAB
**Location:** Seite 12, Section 6.3  
**Platzhalter:** `[SCREENSHOT: Cache-Performance-Vergleich (mit vs. ohne Cache)]`  
**Was zeigen:**
- Zwei Durchläufe des Evaluation-Scripts
- Run 1: Cache leer → Latenz ~2,2s
- Run 2: Cache voll → Latenz ~2,0s
- Vergleichstabelle oder Balkendiagramm

**Wie erstellen:**
1. Cache leeren: `python scripts/run_rag_eval.py` (erstes Mal)
2. Mit Cache: `python scripts/run_rag_eval.py` (zweites Mal)
3. Screenshot beider Outputs nebeneinander

---

### Screenshot 4: Metriken-Vergleich
**Location:** Seite 18, Section 10.2  
**Platzhalter:** `[SCREENSHOT: Metriken-Vergleich (Ist vs. Ziel) als Balkendiagramm]`  
**Was zeigen:**
- Balkendiagramm mit allen 5 Haupt-KPIs
- Für jeden KPI: Ist-Wert (rot) vs. Ziel-Wert (grün)
- X-Achse: Hit Rate, Precision@3, Nutrition Compliance, Latency, Embeddings Usage
- Y-Achse: Prozentwert oder Zeitwert

**Wie erstellen:**
- Excel/Google Sheets Diagramm aus Metriken erstellen
- Oder Python matplotlib Script:

```python
import matplotlib.pyplot as plt

metrics = ['Hit Rate', 'Precision@3', 'Nutr. Compliance', 'Latency (norm)', 'Macro Compliance']
ist = [36.67, 26.67, 80, 100 - (2.08/0.3)*10, 100]  # Latency normalisiert
ziel = [70, 80, 95, 100, 100]

x = range(len(metrics))
plt.bar([i-0.2 for i in x], ist, width=0.4, label='Ist-Wert', color='red', alpha=0.7)
plt.bar([i+0.2 for i in x], ziel, width=0.4, label='Ziel-Wert', color='green', alpha=0.7)
plt.xticks(x, metrics, rotation=45, ha='right')
plt.ylabel('Wert (%)')
plt.legend()
plt.title('KPIs: Ist vs. Ziel')
plt.tight_layout()
plt.savefig('metrics_comparison.png', dpi=300)
```

---

## 2. test_log.md (Testprotokoll)

### Screenshot 5: pytest Unit-Tests
**Location:** Seite 3, Eintrag 4  
**Platzhalter:** `[SCREENSHOT: pytest Ausgabe mit grünen Checkmarks]`  
**Was zeigen:**
- Terminal-Output von `pytest tests/rag_metrics_test.py -v`
- Grüne PASSED-Markierungen
- Zeitangabe (~0.24s)

**Wie erstellen:**
```bash
cd backend
python -m pytest tests/rag_metrics_test.py -v -m "not slow" --tb=short
```

Screenshot des Terminals machen.

---

### Screenshot 6: Integration-Test mit Metriken
**Location:** Seite 5, Eintrag 6  
**Platzhalter:** `[SCREENSHOT: Pytest Ausgabe mit Metriken-Tabelle]`  
**Was zeigen:**
- Output von `test_rag_pipeline_evaluation`
- Tabelle mit Hit Rate, Precision@3, Latency für jeden Testfall
- Aggregierte Durchschnittswerte

**Wie erstellen:**
```bash
python -m pytest tests/rag_metrics_test.py::TestRAGMetrics::test_rag_pipeline_evaluation -v -s
```

Screenshot des Outputs (inkl. Tabelle).

---

### Screenshot 7: Evaluation-Script Komplettausgabe
**Location:** Seite 7, Eintrag 7  
**Platzhalter:** `[SCREENSHOT: Komplette Evaluation-Script Ausgabe mit Tabelle]`  
**Was zeigen:**
- Vollständiger Output von `python scripts/run_rag_eval.py`
- Summary-Tabelle mit allen Test-Cases
- Aggregierte KPIs am Ende
- Pro-Test Details

**Wie erstellen:**
```bash
cd backend
python scripts/run_rag_eval.py | tee eval_output.txt
```

Screenshot des Terminal-Outputs oder Text in Markdown Code-Block.

---

### Screenshot 8: API Response JSON
**Location:** Seite 9, Eintrag 8  
**Platzhalter:** `[SCREENSHOT: Postman/curl Response mit JSON-Daten]`  
**Was zeigen:**
- Postman oder curl Request an `/advisor/compose`
- Body mit Query-Parametern
- Response JSON mit Rezepten
- Optional: HTTP Status 200

**Wie erstellen:**
- Postman verwenden für schöne Darstellung
- Oder curl mit `jq` für formatiertes JSON:

```bash
curl -X POST "http://127.0.0.1:8000/advisor/compose" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "vegan smoothie bowl",
    "servings": 1,
    "preferences": ["vegan"]
  }' | jq .
```

Screenshot des Terminal-Outputs.

---

### Screenshot 9: Lange Query
**Location:** Seite 12, Eintrag 13  
**Platzhalter:** `[SCREENSHOT: Curl Request mit langem Query-String]`  
**Was zeigen:**
- Curl-Command mit sehr langem message-Text
- Response (gekürzt)
- Zeigt dass System lange Queries handhabt

**Wie erstellen:**
- Siehe Eintrag 13 im test_log.md für genauen Command
- Screenshot des Terminals mit Command und Response

---

### Screenshot 10: Performance-Test Ausgabe
**Location:** Seite 14, Eintrag 14  
**Platzhalter:** `[SCREENSHOT: Performance-Test Ausgabe mit Latenz-Werten]`  
**Was zeigen:**
- Python-Script Output mit 10 Runs
- Zeitwerte für jeden Run
- Durchschnitt, Min, Max, Std Dev

**Wie erstellen:**
- Siehe Eintrag 14 im test_log.md für Python-Script
- Screenshot des Terminal-Outputs mit Statistiken

---

### Screenshot 11: Post-Workout Query
**Location:** Seite 18, Eintrag 20  
**Platzhalter:** `[SCREENSHOT: Post-Workout Query mit Rezept-Response]`  
**Was zeigen:**
- Curl/Postman Request mit "nach dem gym" Query
- Response mit High-Protein Rezept
- Makronährstoff-Daten sichtbar (25+ g Protein)

**Wie erstellen:**
- Siehe Eintrag 20 im test_log.md für Command
- Screenshot mit Fokus auf Protein-Wert

---

### Screenshot 12: Metriken-Dashboard
**Location:** Seite 23, Zusammenfassung  
**Platzhalter:** `[SCREENSHOT: Metriken-Dashboard mit Ist/Ziel Vergleich]`  
**Was zeigen:**
- Übersichts-Dashboard aller KPIs
- Tabelle oder Diagramm: Ist vs. Ziel
- Status-Indikatoren (✅ ⚠️)

**Wie erstellen:**
- Kann gleiches Diagramm wie Screenshot 4 sein
- Oder Excel-Tabelle mit Conditional Formatting (rot/grün)

---

## 3. VALIDATION_REPORT.md (optional)

Dieses Dokument hat keine expliziten Screenshot-Platzhalter, kann aber von folgenden Screenshots profitieren:

### Optional Screenshot 13: System-Status-Übersicht
**Was zeigen:**
- Dashboard mit allen 51 Tests (bestanden/fehlgeschlagen)
- Cache-Statistiken
- Service-Status (Embedding-Service, Main API)

---

## Zusammenfassung

**Gesamt Screenshot-Bedarf:**

| Dokument | Anzahl Screenshots |
|----------|-------------------|
| concept_draft.md | 4 |
| test_log.md | 8 |
| VALIDATION_REPORT.md | 0 (optional 1) |
| **GESAMT** | **12 (+ 1 optional)** |

**Priorität:**

- **HOCH:** Screenshots 7, 8, 12 (Evaluation, API, Metriken) - zentral für Verständnis
- **MITTEL:** Screenshots 5, 6, 10 (Tests, Performance) - zeigen Funktionalität
- **NIEDRIG:** Screenshots 1-4, 9, 11 (Architektur, Edge-Cases) - ergänzend

---

## Tipps für gute Screenshots

1. **Auflösung:** Mindestens 1920x1080 oder höher
2. **Lesbarkeit:** Text muss gut lesbar sein (Font-Size erhöhen falls nötig)
3. **Fokus:** Nur relevanten Teil des Bildschirms zeigen
4. **Beschriftung:** Optional mit Pfeilen/Markierungen wichtige Teile highlighten
5. **Format:** PNG bevorzugt (lossless), JPG akzeptabel
6. **Dateiname:** Beschreibend, z.B. `evaluation_script_output.png`

---

## Screenshots in Markdown einfügen

**Syntax:**
```markdown
![Beschreibung](pfad/zur/datei.png)
```

**Beispiel:**
```markdown
![Evaluation Script Ausgabe mit Metriken-Tabelle](screenshots/eval_output.png)
```

**Dateien organisieren:**
```
docs/
  concept_draft.md
  test_log.md
  screenshots/
    system_architecture.png
    cache_stats.png
    metrics_comparison.png
    pytest_unit_tests.png
    eval_script_output.png
    api_response_json.png
    ...
```

---

**Hinweis:** Alle Platzhalter sind als `[SCREENSHOT: Beschreibung]` markiert und können später durch die tatsächlichen Markdown-Bild-Referenzen ersetzt werden.

---

**Dokument-Ende**

**Erstellt:** 10. November 2025  
**Version:** 1.0

