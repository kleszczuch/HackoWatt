"""Wyjaśnienia godzin szczytu prostym językiem / Peak hours explained in plain language."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from energy.household import ConsumptionHour
from energy.weather import WeatherHour

_WEEKDAYS_PL = ("poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela")
_WEEKDAYS_EN = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

_CATEGORY_PHRASES_PL = (
    (1, "ogrzewanie (pompa ciepła)"),
    (3, "gotowanie"),
    (4, "elektronika (RTV i komputery)"),
    (5, "duże AGD (np. zmywarka lub pralka)"),
    (2, "oświetlenie"),
)
_CATEGORY_PHRASES_EN = (
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


def _temperature_phrase(temperature: float, lang: str = "pl") -> str:
    value = f"{temperature:.0f} °C".replace("-", "−")
    if lang == "en":
        if temperature < 5:
            return f"cold (about {value})"
        if temperature < 12:
            return f"cool (about {value})"
        if temperature > 24:
            return f"hot (about {value})"
        return f"mild (about {value})"

    if temperature < 5:
        return f"zimno (ok. {value})"
    if temperature < 12:
        return f"chłodno (ok. {value})"
    if temperature > 24:
        return f"gorąco (ok. {value})"
    return f"umiarkowana temperatura (ok. {value})"


def explain_peaks(
    forecast: list[ConsumptionHour],
    weather: list[WeatherHour],
    top: int = 3,
    lang: str = "pl",
) -> list[PeakExplanation]:
    """Tworzy czytelne wyjaśnienia dla najważniejszych szczytów zużycia w prognozie."""
    temperatures = {record.timestamp: record.temperature for record in weather}
    peaks = sorted(forecast, key=lambda record: record.total, reverse=True)[:top]
    peaks.sort(key=lambda record: record.timestamp)
    explanations = []

    weekdays = _WEEKDAYS_EN if lang == "en" else _WEEKDAYS_PL
    category_phrases = _CATEGORY_PHRASES_EN if lang == "en" else _CATEGORY_PHRASES_PL
    default_reason = "household base load" if lang == "en" else "zużycie podstawowe domu"

    for record in peaks:
        total = record.total
        reasons = [
            phrase
            for index, phrase in category_phrases
            if total > 0 and record.categories[index] / total >= Decimal("0.15")
        ]
        if not reasons:
            reasons = [default_reason]
        temperature = temperatures.get(record.timestamp)
        temp_phrase = _temperature_phrase(temperature, lang=lang) if temperature is not None else ""
        if lang == "en":
            weather_part = f" Outside, it is {temp_phrase}." if temperature is not None else ""
            day_kind = "weekend" if record.timestamp.weekday() >= 5 else "weekday"
            weekday = weekdays[record.timestamp.weekday()]
            joined = (
                reasons[0] if len(reasons) == 1 else ", ".join(reasons[:-1]) + f" and {reasons[-1]}"
            )
            total_text = str(total.quantize(Decimal("0.1")))
            sentence = (
                f"{weekday} {record.timestamp:%d.%m} at {record.timestamp:%H}:00 – "
                f"{total_text} kWh ({day_kind}). Main contributors: {joined}."
                f"{weather_part}"
            )
        else:
            weather_part = f" Na zewnątrz {temp_phrase}." if temperature is not None else ""
            day_kind = "weekend" if record.timestamp.weekday() >= 5 else "dzień roboczy"
            weekday = weekdays[record.timestamp.weekday()]
            joined = (
                reasons[0] if len(reasons) == 1 else ", ".join(reasons[:-1]) + f" i {reasons[-1]}"
            )
            total_text = str(total.quantize(Decimal("0.1"))).replace(".", ",")
            sentence = (
                f"{weekday.capitalize()} {record.timestamp:%d.%m}, "
                f"godz. {record.timestamp:%H}:00 – "
                f"{total_text} kWh ({day_kind}). Największe składniki zużycia: {joined}."
                f"{weather_part}"
            )
        explanations.append(PeakExplanation(record.timestamp, total, sentence, tuple(reasons)))
    return explanations
