import json

def load_inventory(path):
    """Load inventory from a JSON file.

    Args:
        path (str): Path to the JSON file.

    Returns:
        dict: Parsed inventory data.

    Raises:
        ValueError: If the file does not exist or contains invalid JSON.
    """
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError as e:
        raise ValueError(f"Inventory file not found: {path}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in inventory file: {path}") from e


def total_value(inventory):
    """Calculate the total value of all items in the inventory.

    Missing ``price`` or ``qty`` fields are treated as ``0``.
    """
    total = 0
    for item in inventory.get("items", []):
        price = item.get("price", 0)
        qty = item.get("qty", 0)
        total += price * qty
    return total
