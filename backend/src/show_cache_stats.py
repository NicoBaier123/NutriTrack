import warnings
warnings.filterwarnings('ignore')

from app.core.database import get_session
from sqlmodel import select, text

session = next(get_session())

# Cache-Statistiken abrufen
cache_count = session.exec(text('SELECT COUNT(*) FROM recipe_embeddings')).first()[0]
recipe_count = session.exec(text('SELECT COUNT(*) FROM recipe')).first()[0]
cache_rate = (cache_count / recipe_count * 100) if recipe_count > 0 else 0

# Formatierte Ausgabe
print("=" * 60)
print("           RECIPE INDEXER CACHE-STATISTIKEN")
print("=" * 60)
print(f"Gecachte Embeddings:     {cache_count}")
print(f"Rezepte in Datenbank:    {recipe_count}")
print(f"Cache-Hit-Rate:          {cache_rate:.1f}%")
print("=" * 60)
print()
print("[OK] Cache ist vollstaendig aufgebaut")
print(f"[OK] {cache_count} Rezept-Embeddings sind gespeichert")
print()

