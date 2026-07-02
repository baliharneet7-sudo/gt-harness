import pytest
import json
import tempfile
import os
from inventory import load_inventory, total_value


def test_total_value_correct_total():
    """Test that total_value calculates the correct total for inventory.json"""
    inventory = load_inventory("inventory.json")
    # bolt: 0.10 * 500 = 50
    # nut: 0.05 * 800 = 40
    # gear: 4.50 * 20 = 90
    # total: 50 + 40 + 90 = 180
    assert total_value(inventory) == 180


def test_total_value_missing_price():
    """Test that total_value treats missing price as 0"""
    inventory = {
        "items": [
            {"name": "bolt", "qty": 100},  # missing price
            {"name": "nut", "price": 0.05, "qty": 50}
        ]
    }
    # bolt: 0 * 100 = 0
    # nut: 0.05 * 50 = 2.5
    # total: 0 + 2.5 = 2.5
    assert total_value(inventory) == 2.5


def test_total_value_missing_qty():
    """Test that total_value treats missing qty as 0"""
    inventory = {
        "items": [
            {"name": "bolt", "price": 0.10},  # missing qty
            {"name": "nut", "price": 0.05, "qty": 50}
        ]
    }
    # bolt: 0.10 * 0 = 0
    # nut: 0.05 * 50 = 2.5
    # total: 0 + 2.5 = 2.5
    assert total_value(inventory) == 2.5


def test_total_value_missing_both():
    """Test that total_value treats both missing price and qty as 0"""
    inventory = {
        "items": [
            {"name": "bolt"},  # missing both price and qty
            {"name": "nut", "price": 0.05, "qty": 50}
        ]
    }
    # bolt: 0 * 0 = 0
    # nut: 0.05 * 50 = 2.5
    # total: 0 + 2.5 = 2.5
    assert total_value(inventory) == 2.5


def test_load_inventory_missing_file():
    """Test that load_inventory raises ValueError for missing file"""
    with pytest.raises(ValueError) as exc_info:
        load_inventory("nonexistent_file.json")
    assert "not found" in str(exc_info.value).lower()
    assert "nonexistent_file.json" in str(exc_info.value)


def test_load_inventory_invalid_json():
    """Test that load_inventory raises ValueError for invalid JSON"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write("{invalid json content")
        temp_path = f.name
    
    try:
        with pytest.raises(ValueError) as exc_info:
            load_inventory(temp_path)
        assert "invalid json" in str(exc_info.value).lower()
        assert temp_path in str(exc_info.value)
    finally:
        os.unlink(temp_path)
