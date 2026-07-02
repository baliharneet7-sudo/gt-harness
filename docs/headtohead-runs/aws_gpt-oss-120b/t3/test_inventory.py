import os
import json
import pytest

from inventory import load_inventory, total_value


def test_total_value_correct():
    # Use the provided inventory.json file
    inventory = load_inventory(os.path.join(os.path.dirname(__file__), "inventory.json"))
    assert total_value(inventory) == 180.0


def test_total_value_missing_fields():
    inventory = {
        "items": [
            {"name": "widget", "price": 10},            # missing qty
            {"name": "gadget", "qty": 5},               # missing price
            {"name": "thing"},                           # missing both
        ]
    }
    # Expected: 10*0 + 0*5 + 0*0 = 0
    assert total_value(inventory) == 0


def test_load_inventory_missing_file(tmp_path):
    missing_path = tmp_path / "nonexistent.json"
    with pytest.raises(ValueError) as excinfo:
        load_inventory(str(missing_path))
    assert str(missing_path) in str(excinfo.value)


def test_load_inventory_invalid_json(tmp_path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{ this is not valid JSON }")
    with pytest.raises(ValueError) as excinfo:
        load_inventory(str(bad_file))
    assert str(bad_file) in str(excinfo.value)
