import secrets
from decimal import ROUND_HALF_UP, Decimal

TWO_PLACES = Decimal("0.01")


def money(value):
    """Normalise to 2 decimal places (banker-safe, never float)."""
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def luhn_check_digit(payload: str) -> str:
    total = 0
    for i, ch in enumerate(reversed(payload)):
        digit = int(ch)
        if i % 2 == 0:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return str((10 - total % 10) % 10)


def is_valid_account_number(number: str) -> bool:
    return len(number) == 12 and number.isdigit() and luhn_check_digit(number[:-1]) == number[-1]


def new_account_number() -> str:
    body = "5" + "".join(str(secrets.randbelow(10)) for _ in range(10))
    return body + luhn_check_digit(body)


def csv_safe(value) -> str:
    """Neutralise spreadsheet formula injection in exported statements."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text
