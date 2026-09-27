from shop.pricing import apply_tax, total


def test_total():
    assert total([], 0.1) == 0


def test_apply_tax_inside_callback():
    check = lambda: apply_tax(10, 0.1)  # noqa: E731
    assert check() == 11
