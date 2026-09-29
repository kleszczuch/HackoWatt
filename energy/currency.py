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


def convert_plan_currency(plan: dict, currency: str) -> dict:
    """Przelicza kwoty planu rekomendacji z EUR na walutę prezentacji.

    Zwraca nowy słownik; pola kwot (saving_per_cycle, estimated_annual_saving,
    total_daily_saving) pozostają stringami zaokrąglonymi do 2 miejsc.
    """
    converted = {**plan, "currency": currency}
    converted["observed_events"] = []
    for item in plan.get("observed_events", []):
        entry = dict(item)
        if "advice" in entry:
            entry["advice"] = dict(entry["advice"])
            for field in ("saving_per_cycle", "estimated_annual_saving"):
                if field in entry["advice"]:
                    entry["advice"][field] = str(
                        from_eur(Decimal(entry["advice"][field]), currency).quantize(
                            Decimal("0.01")
                        )
                    )
        converted["observed_events"].append(entry)
    recommendations = []
    for item in plan.get("recommendations", []):
        entry = dict(item)
        for field in ("saving_per_cycle", "estimated_annual_saving"):
            if field in entry:
                entry[field] = str(
                    from_eur(Decimal(entry[field]), currency).quantize(Decimal("0.01"))
                )
        recommendations.append(entry)
    converted["recommendations"] = recommendations
    if "total_daily_saving" in plan:
        converted["total_daily_saving"] = str(
            from_eur(Decimal(plan["total_daily_saving"]), currency).quantize(Decimal("0.01"))
        )
    return converted
