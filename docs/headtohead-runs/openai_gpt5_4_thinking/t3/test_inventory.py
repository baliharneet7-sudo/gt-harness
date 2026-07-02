import re

import pytest

from inventory import load_inventory, total_value


def test_total_value_for_inventory_json():
    inventory = load_inventory("inventory.json")

    assert total_value(inventory) == pytest.approx(180.0)


def test_total_value_treats_missing_price_or_qty_as_zero():
    inventory = {
        "items": [
            {"name": "bolt", "price": 0.10, "qty": 500},
            {"name": "washer", "qty": 10},
            {"name": "sprocket", "price": 2.5},
            {"name": "pin"},
        ]
    }

    assert total_value(inventory) == pytest.approx(50.0)


def test_load_inventory_missing_file_raises_value_error():
    path = "missing_inventory.json"

    with pytest.raises(ValueError, match=path):
        load_inventory(path)



def test_load_inventory_invalid_json_raises_value_error(tmp_path):
    path = tmp_path / "invalid_inventory.json"
    path.write_text("{invalid json", encoding="utf-8")

    with pytest.raises(ValueError, match=re.escape(str(path))):
        load_inventory(path)
