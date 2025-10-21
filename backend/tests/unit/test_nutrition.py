from app.utils.nutrition import macros_for_grams, sum_macros, round_macros, Macros


def test_macros_for_grams_basic():
    m = macros_for_grams(100, 10, 15, 5, grams=200)
    assert m.kcal == 200
    assert m.protein_g == 20
    assert m.carbs_g == 30
    assert m.fat_g == 10


def test_macros_for_grams_none_and_negative():
    m = macros_for_grams(None, None, None, None, grams=-50)
    assert m.kcal == 0
    assert m.protein_g == 0
    assert m.carbs_g == 0
    assert m.fat_g == 0


def test_sum_and_round_macros():
    a = macros_for_grams(120, 12.3, 10.3, 4.9, grams=150)
    b = macros_for_grams(80, 3.3, 17.7, 0.1, grams=50)
    total = sum_macros([a, b])
    r = round_macros(total, 1)

    # compute expected
    exp = Macros(
        kcal=120*1.5 + 80*0.5,
        protein_g=12.3*1.5 + 3.3*0.5,
        carbs_g=10.3*1.5 + 17.7*0.5,
        fat_g=4.9*1.5 + 0.1*0.5,
    )
    exp = round_macros(exp, 1)
    assert r.kcal == exp.kcal
    assert r.protein_g == exp.protein_g
    assert r.carbs_g == exp.carbs_g
    assert r.fat_g == exp.fat_g


def test_macros_to_dict_casts_numbers():
    m = Macros(kcal=123.456, protein_g="30", carbs_g=0, fat_g=7)
    data = m.to_dict()
    assert data == {
        "kcal": 123.456,
        "protein_g": 30.0,
        "carbs_g": 0.0,
        "fat_g": 7.0,
    }
