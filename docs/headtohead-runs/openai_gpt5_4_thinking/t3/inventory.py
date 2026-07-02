import json


def load_inventory(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError as exc:
        raise ValueError(f"Inventory file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in inventory file: {path}") from exc


def total_value(inventory):
    total = 0
    for item in inventory["items"]:
        total += item.get("price", 0) * item.get("qty", 0)
    return total
