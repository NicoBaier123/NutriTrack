from app.utils.validators import clamp, safe_float


def test_clamp_within_bounds():
    assert clamp(5, 0, 10) == 5
    assert clamp(-2, 0, 10) == 0
    assert clamp(12, 0, 10) == 10


def test_safe_float_handles_invalid_input():
    assert safe_float("3.14") == 3.14
    assert safe_float(None) == 0.0
    assert safe_float(object()) == 0.0
