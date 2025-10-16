# backend/app/utils/validators.py
def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def safe_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0
