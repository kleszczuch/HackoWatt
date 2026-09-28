"""Wyjaśnienia godzin szczytu prostym językiem.

Budowane z udziałów kategorii w prognozie, temperatury i typu dnia —
bez żargonu i bez obiecywania dokładności.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from energy.household import ConsumptionHour
from energy.weather import WeatherHour

_WEEKDAYS_PL = ("poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela")
_CATEGORY_PHRASES = (
    (1, "ogrzewanie (pompa ciepła)"),
    (3, "gotowanie"),
    (4, "elektronika (RTV i komputery)"),
    (5, "duże AGD (np. zmywarka lub pralka)"),
    (2, "oświetlenie"),
)


@dataclass(frozen=True)
class PeakExplanation:
    timestamp: datetime
    total: Decimal
    sentence: str


def _temperature_phrase(temperature: float) -> str:
    value = f"{temperature:.0f} °C".replace("-", "−")
    if temperature < 5:
        return f"zimno (ok. {value})"
    if temperature < 12:
        return f"chłodno (ok. {value})"
    if temperature > 24:
        return f"gorąco (ok. {value})"
    return f"umiarkowana temperatura (ok. {value})"


def explain_peaks(
    forecast: list[ConsumptionHour], weather: list[WeatherHour], top: int = 3
) -> list[PeakExplanation]:
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
            reasons = ["zużycie podstawowe domu"]
        temperature = temperatures.get(record.timestamp)
        weather_part = (
            f" Na zewnątrz {_temperature_phrase(temperature)}." if temperature is not None else ""
        )
        day_kind = "weekend" if record.timestamp.weekday() >= 5 else "dzień roboczy"
        weekday = _WEEKDAYS_PL[record.timestamp.weekday()]
        joined = reasons[0] if len(reasons) == 1 else ", ".join(reasons[:-1]) + f" i {reasons[-1]}"
        total_text = str(total.quantize(Decimal("0.1"))).replace(".", ",")
        sentence = (
            f"{weekday.capitalize()} {record.timestamp:%d.%m}, godz. {record.timestamp:%H}:00 — "
            f"ok. {total_text} kWh ({day_kind}). "
            f"Główne przyczyny: {joined}.{weather_part}"
        )
        explanations.append(PeakExplanation(record.timestamp, total, sentence))
    return explanations
