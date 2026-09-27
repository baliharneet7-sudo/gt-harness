def round_money(value):
    return round(value, 2)


def apply_tax(amount, rate):
    taxed = amount * (1 + rate)
    return round_money(taxed)


def total(items, rate):
    subtotal = 0
    for item in items:
        subtotal = subtotal + item.price
    result = apply_tax(subtotal, rate)
    return result


def make_formatter(prefix):
    def format_line(text):
        return prefix + text
    return format_line
