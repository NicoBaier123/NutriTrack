import csv, sys
from pathlib import Path
from sqlmodel import Session, select
from app.db import engine, init_db
from app.models.foods import Food

def upsert_foods(csv_path: Path):
    init_db()
    with Session(engine) as s, csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["name"].strip()
            food = s.exec(select(Food).where(Food.name == name)).first()
            if not food:
                food = Food(name=name)
            food.kcal = float(row["kcal"])
            food.protein_g = float(row["protein_g"])
            food.carbs_g = float(row["carbs_g"])
            food.fat_g = float(row["fat_g"])
            s.add(food)
        s.commit()

if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/foods.csv")
    upsert_foods(path)
    print("Foods import done.")
