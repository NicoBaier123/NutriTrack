from pathlib import Path
text = Path("backend/app/routers/demo_ui.py").read_bytes()
for i,b in enumerate(text):
    if b<32 and b not in (9,10,13):
        print(i, b)
