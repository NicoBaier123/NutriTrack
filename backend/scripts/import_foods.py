import csv, sys
from pathlib import Path
from typing import List
from sqlmodel import Session, select
from app.db import engine, init_db
from app.models.foods import Food

def _to_float(x: str) -> float:
    # akzeptiert Dezimalpunkt UND Dezimalkomma
    return float(x.replace(",", ".").strip())

def upsert_foods(csv_path: Path):
    init_db()
    with Session(engine) as s, csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            print("Leere CSV.")
            return
        # Header normalisieren (wir akzeptieren beides: DictReader-Header oder gar keinen)
        # Wir parsen hier manuell, damit wir ungequotete Kommata im Namen tolerieren.
        line_no = 1  # nach Header
        for row in reader:
            line_no += 1
            if not row or all(not cell.strip() for cell in row):
                continue

            # Ziel: genau 5 Felder -> name,kcal,protein_g,carbs_g,fat_g
            if len(row) < 5:
                print(f"Übersprungen (zu wenig Spalten) in Zeile {line_no}: {row}")
                continue

            if len(row) == 5:
                name, kcal, prot, carbs, fat = row
            else:
                # Name enthält zusätzliche Kommata → alles bis auf die letzten 4 Spalten ist Name
                name = ",".join(row[0:len(row)-4])
                kcal, prot, carbs, fat = row[-4], row[-3], row[-2], row[-1]

            name = name.strip().strip('"').strip()  # Anführungszeichen/Spaces ab
            try:
                kcal_f  = _to_float(kcal)
                prot_f  = _to_float(prot)
                carbs_f = _to_float(carbs)
                fat_f   = _to_float(fat)
            except Exception as e:
                print(f"Fehler beim Parsen in Zeile {line_no}: {row} -> {e}")
                continue

            # Upsert (case-insensitive wäre optional)
            food = s.exec(select(Food).where(Food.name == name)).first()
            if not food:
                food = Food(name=name)

            food.kcal = kcal_f
            food.protein_g = prot_f
            food.carbs_g = carbs_f
            food.fat_g = fat_f

            s.add(food)

        s.commit()
    print("Foods import done.")

if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/foods.csv")
    upsert_foods(path)
