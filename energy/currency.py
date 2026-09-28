"""Waluta prezentacji; obliczenia scenariusza pozostają w EUR."""

from decimal import Decimal

from energy.tariffs import EURPLN_RATE

CURRENCY_COOKIE = "display_currency"
RATES = {"EUR": Decimal("1"), "PLN": EURPLN_RATE, "DKK": Decimal("7.46038")}
SYMBOLS = {"EUR": "€", "PLN": "zł", "DKK": "kr"}


def selected_currency(request) -> str:
    value = request.session.get(CURRENCY_COOKIE) or request.COOKIES.get(CURRENCY_COOKIE)
    return value if value in RATES else "EUR"


def from_eur(value: Decimal, currency: str) -> Decimal:
    return Decimal(str(value)) * RATES[currency]


def to_eur(value: Decimal, currency: str) -> Decimal:
    return Decimal(str(value)) / RATES[currency]
