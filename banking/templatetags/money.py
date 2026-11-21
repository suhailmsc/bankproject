from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


def _indian_group(integer_part: str) -> str:
    if len(integer_part) <= 3:
        return integer_part
    head, tail = integer_part[:-3], integer_part[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail])


@register.filter
def inr(value, with_symbol=True):
    """1234567.5 -> ₹12,34,567.50"""
    try:
        amount = Decimal(value).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return value
    sign = "-" if amount < 0 else ""
    whole, frac = f"{abs(amount):.2f}".split(".")
    text = f"{sign}{_indian_group(whole)}.{frac}"
    return f"\u20b9{text}" if with_symbol else text


@register.filter
def mask(number):
    number = str(number or "")
    return "\u2022\u2022\u2022\u2022 " + number[-4:]
