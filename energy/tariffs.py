"""Taryfa godzinowa i stałe."""

from datetime import datetime
from decimal import Decimal

CURRENCY = "EUR"

# Taryfa uproszczona: (godzina_od, godzina_do, cena €/kWh).
TARIFF_PERIODS = (
    (0, 6, Decimal("0.18")),
    (6, 17, Decimal("0.28")),
    (17, 22, Decimal("0.40")),
    (22, 24, Decimal("0.28")),
)

PV_COST_PER_KWP = Decimal("1300")
EXPORT_PRICE = Decimal("0.08")
PV_OPEX_RATE = Decimal("0.01")
PV_PERFORMANCE_RATIO = Decimal("0.8")


def price_for_hour(hour: int) -> Decimal:
    """Zwraca cenę energii dla konkretnej godziny w oparciu o taryfę godzinową."""
    if not 0 <= hour <= 23:
        raise ValueError(f"Godzina poza zakresem 0–23: {hour}")
    for start, end, price in TARIFF_PERIODS:
        if start <= hour < end:
            return price
    raise AssertionError("Taryfa nie pokrywa pełnej doby.")


def price_for_timestamp(ts: datetime, rce_prices: dict[datetime, Decimal] | None = None) -> Decimal:
    """Cena RCE dla danej godziny, a gdy jej brak — cena z taryfy godzinowej."""
    if rce_prices:
        price = rce_prices.get(ts.replace(minute=0, second=0, microsecond=0))
        if price is not None:
            return price
    return price_for_hour(ts.hour)


def energy_cost(timestamps: list[datetime], amounts_kwh: list[Decimal]) -> Decimal:
    """Oblicza koszt energii na podstawie godzinowej taryfy i zużycia w kWh."""
    if len(timestamps) != len(amounts_kwh):
        raise ValueError("Liczba znaczników czasu i wartości kWh musi być równa.")
    pairs = zip(timestamps, amounts_kwh, strict=True)
    return sum((price_for_hour(ts.hour) * amount for ts, amount in pairs), Decimal(0))
