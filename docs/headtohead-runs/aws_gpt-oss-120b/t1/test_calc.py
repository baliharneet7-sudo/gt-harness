from calc import average

def test_average_basic():
    assert average([2, 4, 6]) == 4

def test_average_empty_returns_zero():
    assert average([]) == 0.0
