from pathlib import Path
text = Path("backend/app/routers/demo_ui.py").read_text(encoding="utf-8")
if '\x07' in text:
    print('contains bell char')
    for i,ch in enumerate(text):
        if ch=='\x07':
            start=max(0,i-40)
            end=min(len(text),i+40)
            snippet=text[start:end]
            print(i, repr(snippet))
else:
    print('no bell char')
