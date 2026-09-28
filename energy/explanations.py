"""Wyjaśnienia godzin szczytu prostym językiem.

Budowane z udziałów kategorii w prognozie, temperatury i typu dnia –
bez żargonu i bez obiecywania dokładności.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from energy.household import ConsumptionHour
from energy.weather import WeatherHour

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_CATEGORY_PHRASES = (
    (1, "heating (heat pump)"),
    (3, "cooking"),
    (4, "TV and computers"),
    (5, "major appliances (such as the dishwasher or washing machine)"),
    (2, "lighting"),
)


@dataclass(frozen=True)
class PeakExplanation:
    """Krótka odpowiedź opisująca szczytowe zużycie w czytelnym języku."""
    timestamp: datetime
    total: Decimal
    sentence: str
    components: tuple[str, ...]


def _temperature_phrase(temperature: float) -> str:
    """Zamienia temperaturę na prosty opis typu: zimno, chłodno, umiarkowanie, gorąco."""
    value = f"{temperature:.0f} °C".replace("-", "−")
    if temperature < 5:
        return f"cold (about {value})"
    if temperature < 12:
        return f"cool (about {value})"
    if temperature > 24:
        return f"hot (about {value})"
    return f"mild (about {value})"


def explain_peaks(
    forecast: list[ConsumptionHour], weather: list[WeatherHour], top: int = 3
) -> list[PeakExplanation]:
    """Tworzy czytelne wyjaśnienia dla najważniejszych szczytów zużycia w prognozie."""
    temperatures = {record.timestamp: record.temperature for record in weather}
    peaks = sorted(forecast, key=lambda record: record.total, reverse=True)[:top]
    peaks.sort(key=lambda record: record.timestamp)
    explanations = []
    for record in peaks:
        total = record.total
        reasons = [
            phrase
            for index, phrase in _CATEGORY_PHRASES
            if total > 0 and record.categories[index] / total >= Decimal("0.15")
        ]
        if not reasons:
            reasons = ["household base load"]
        temperature = temperatures.get(record.timestamp)
        weather_part = (
            f" Outside, it is {_temperature_phrase(temperature)}."
            if temperature is not None
            else ""
        )
        day_kind = "weekend" if record.timestamp.weekday() >= 5 else "weekday"
        weekday = _WEEKDAYS[record.timestamp.weekday()]
        joined = (
            reasons[0] if len(reasons) == 1 else ", ".join(reasons[:-1]) + f" and {reasons[-1]}"
        )
        total_text = str(total.quantize(Decimal("0.1")))
        sentence = (
            f"{weekday} {record.timestamp:%d.%m} at {record.timestamp:%H}:00 – "
            f"{total_text} kWh ({day_kind}). Main contributors: {joined}."
            f"{weather_part}"
        )
        explanations.append(PeakExplanation(record.timestamp, total, sentence, tuple(reasons)))
    return explanations
