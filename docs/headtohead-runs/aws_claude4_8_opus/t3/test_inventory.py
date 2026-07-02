import json

import pytest

from inventory import load_inventory, total_value


def test_total_value_of_inventory_json():
    inventory = load_inventory("inventory.json")
    assert total_value(inventory) == pytest.approx(0.10 * 500 + 0.05 * 800 + 4.50 * 20)


def test_missing_price_treated_as_zero():
    inventory = {"items": [{"name": "bolt", "qty": 500}]}
    assert total_value(inventory) == 0


def test_missing_qty_treated_as_zero():
    inventory = {"items": [{"name": "bolt", "price": 0.10}]}
    assert total_value(inventory) == 0


def test_missing_file_raises_value_error():
    with pytest.raises(ValueError) as exc_info:
        load_inventory("does_not_exist.json")
    assert "does_not_exist.json" in str(exc_info.value)


def test_invalid_json_raises_value_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    with pytest.raises(ValueError) as exc_info:
        load_inventory(str(bad))
    assert str(bad) in str(exc_info.value)
