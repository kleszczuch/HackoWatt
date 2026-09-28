"""Deterministyczny symulator zużycia energii dla 5 scenariuszy HackoWatt.

Modeluje konkretne zdarzenia domowników (posiłki, pranie, praca zdalna,
goście, wyjazdy) oraz parametry specyficzne dla domostwa (np. basen/sauna w Barcelonie,
pies w Lizbonie, singielka w Warszawie czy dom pokoleń w Kopenhadze).
"""

import csv
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import numpy as np

from energy.weather import WeatherHour

SEED = 78
CATEGORIES = (
    "Baza_kWh",
    "Ogrzewanie_kWh",
    "Oswietlenie_kWh",
    "Gotowanie_kWh",
    "RTV_PC_kWh",
    "Duze_AGD_kWh",
)
TOTAL_COLUMN = "Calkowite_Zuzycie_kWh"
EVENTS_COLUMN = "Zdarzenia"
CONSUMPTION_COLUMNS = (
    "Data_Czas",
    "Dzien_Tygodnia",
    "Godzina",
    *CATEGORIES,
    TOTAL_COLUMN,
    EVENTS_COLUMN,
)

HISTORY_FILENAME = "historia_zuzycie.csv"
FLEX_EVENTS_FILENAME = "zdarzenia_elastyczne.csv"
ANNUAL_CONSUMPTION_FILENAME = "roczne_zuzycie.csv"
ANNUAL_EVENTS_FILENAME = "roczne_zdarzenia.csv"

EVENT_COLUMNS = ("Data", "Urzadzenie", "Start_Godzina", "Czas_h", "Energia_kWh")
DEVICE_PROFILES = {
    "Zmywarka": {"energy": (0.8, 1.2), "duration": (1, 2)},
    "Pralka": {"energy": (0.6, 1.0), "duration": (1, 2)},
    "Suszarka": {"energy": (1.5, 2.5), "duration": (1, 2)},
}

# Przybliżona jasna pora dnia (granica godziny).
_DAWN = {1: 8, 2: 7.5, 3: 6.5, 4: 6, 5: 5, 6: 4, 7: 4.5, 8: 5.5, 9: 6.5, 10: 7, 11: 7.5, 12: 8.5}
_DUSK = {
    1: 16,
    2: 17,
    3: 18,
    4: 20,
    5: 21,
    6: 22,
    7: 21.5,
    8: 20.5,
    9: 19.5,
    10: 18,
    11: 16,
    12: 15.5,
}


@dataclass(frozen=True)
class ConsumptionHour:
    timestamp: datetime
    categories: tuple[Decimal, ...]
    events: str

    @property
    def total(self) -> Decimal:
        return sum(self.categories, Decimal(0))


@dataclass(frozen=True)
class FlexEvent:
    device: str
    day: date
    start_hour: int
    duration_h: int
    energy_kwh: Decimal


def _q3(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def _draw_day_plan(rng: np.random.RandomState, day: date, scenario_id: int) -> dict:
    weekend = day.weekday() >= 5
    trip_chance = 0.07 if weekend else 0.03
    if scenario_id == 1:
        trip_chance = 0.25 if weekend else 0.12
    elif scenario_id == 3:
        trip_chance = 0.02

    plan = {
        "weekend": weekend,
        "wfh": not weekend and rng.rand() < (0.4 if scenario_id in (1, 5) else 0.12),
        "guests": rng.rand() < (0.12 if weekend else 0.04),
        "trip": rng.rand() < trip_chance,
        "grandparents_out": scenario_id == 4 and not weekend and rng.rand() < 0.18,
        "wash": False,
        "dryer": False,
        "dishwasher": rng.rand() < (0.9 if scenario_id == 3 else 0.85),
        "oven_day": rng.rand() < (0.5 if scenario_id == 3 else 0.35),
        "dishwasher_start": int(rng.choice((13, 14)) if weekend else rng.randint(19, 21)),
        "wash_start": int(rng.randint(9, 12) if weekend else rng.randint(9, 15)),
        "lunch_hour": int(rng.randint(12, 14)),
        "dinner_hour": int(rng.randint(17, 19)),
    }
    if day.weekday() in (1, 5) and rng.rand() < 0.75:
        plan["wash"] = True
    elif rng.rand() < 0.15:
        plan["wash"] = True
    if plan["wash"]:
        plan["dryer"] = rng.rand() < (0.7 if scenario_id == 4 else 0.5)
    return plan


def _occupancy(plan: dict, hour: int, scenario_id: int) -> str:
    if plan["trip"]:
        return "nobody"
    if hour < 6 or hour >= 23:
        return "sleeping"
    if scenario_id == 1:
        if 9 <= hour < 17 and not plan["wfh"]:
            return "nobody"
        return "evening"
    if hour < 9:
        return "morning"
    if hour < 14:
        if plan["weekend"]:
            return "family_day"
        return "grandparents_out" if plan["grandparents_out"] else "grandparents"
    if hour < 17:
        return "family_day" if plan["weekend"] else "kids"
    if hour < 22:
        return "evening"
    return "winding_down"


def _heating_kw(
    rng: np.random.RandomState, plan: dict, hour: int, temperature: float, scenario_id: int
) -> float:
    setpoint = 17.0 if plan["trip"] else (19.5 if hour >= 22 or hour < 6 else 21.0)
    if scenario_id in (3, 5) and temperature > 22:
        if 12 <= hour <= 19:
            return rng.uniform(0.8, 2.0)
        return 0.2
    if temperature >= setpoint - 2:
        return 0.0
    thermal_kw = (setpoint - temperature) * (0.25 if scenario_id == 1 else 0.35)
    cop = min(3.5, max(2.2, 2.2 + 0.07 * temperature))
    electric_kw = min(4.5 if scenario_id == 3 else 4.0, thermal_kw / cop)
    return electric_kw * rng.uniform(0.85, 1.15)


def _simulate_hour(
    rng: np.random.RandomState,
    plan: dict,
    hour: int,
    month: int,
    temperature: float,
    cloud: float,
    scenario_id: int,
) -> tuple[dict, list[str]]:
    values = dict.fromkeys(CATEGORIES, 0.0)
    labels: list[str] = []
    occupancy = _occupancy(plan, hour, scenario_id)

    base_min, base_max = (
        (0.05, 0.09) if scenario_id == 1 else ((0.8, 1.4) if scenario_id == 3 else (0.11, 0.16))
    )
    values["Baza_kWh"] = rng.uniform(base_min, base_max)

    if scenario_id == 5 and occupancy == "nobody":
        values["Baza_kWh"] += rng.uniform(0.05, 0.10)
        labels.append("tryb opieki nad psem")

    if occupancy == "sleeping" and rng.rand() < 0.4:
        values["Baza_kWh"] += rng.uniform(0.01, 0.03)

    values["Ogrzewanie_kWh"] = _heating_kw(rng, plan, hour, temperature, scenario_id)

    dawn, dusk = _DAWN[month], _DUSK[month]
    if cloud > 70:
        dawn, dusk = dawn + 0.5, dusk - 0.5
    dark = hour < dawn or hour >= dusk
    if dark and occupancy not in ("nobody", "sleeping"):
        scale = {"morning": 0.7, "evening": 1.0, "winding_down": 0.5}.get(occupancy, 0.6)
        values["Oswietlenie_kWh"] = rng.uniform(0.10, 0.30) * scale

    if occupancy == "morning":
        values["Gotowanie_kWh"] = rng.uniform(0.10 if scenario_id == 1 else 0.15, 0.45)
        if rng.rand() < 0.8:
            values["Gotowanie_kWh"] += rng.uniform(0.10, 0.17)
    elif occupancy in ("grandparents", "family_day") and hour == plan["lunch_hour"]:
        values["Gotowanie_kWh"] = rng.uniform(0.3, 0.9 if occupancy == "grandparents" else 1.4)
    elif occupancy == "evening" and hour == plan["dinner_hour"]:
        mult = 1.8 if scenario_id == 3 else 1.0
        values["Gotowanie_kWh"] = rng.uniform(0.6, 2.0 if plan["oven_day"] else 1.1) * mult

    if plan["guests"] and occupancy == "evening":
        values["Gotowanie_kWh"] *= 1.5
        labels.append("goście")
    if plan["trip"]:
        labels.append("wyjazd rodziny" if scenario_id == 4 else "wyjazd / nieobecność")

    rtv_scale = 0.5 if scenario_id == 1 else (1.5 if scenario_id == 3 else 1.0)
    if occupancy == "grandparents":
        values["RTV_PC_kWh"] = rng.uniform(0.08, 0.15) * rtv_scale
    elif occupancy == "kids":
        values["RTV_PC_kWh"] = rng.uniform(0.08, 0.25) * rtv_scale
    elif occupancy == "family_day":
        values["RTV_PC_kWh"] = rng.uniform(0.05, 0.25) * rtv_scale
    elif occupancy in ("evening", "winding_down"):
        values["RTV_PC_kWh"] = rng.uniform(0.15, 0.35) * rtv_scale
    if plan["wfh"] and 9 <= hour < 17:
        values["RTV_PC_kWh"] += rng.uniform(0.08, 0.20)
        labels.append("praca zdalna")

    if scenario_id == 3:
        if 9 <= hour <= 16:
            values["Duze_AGD_kWh"] += rng.uniform(0.6, 1.2)
            labels.append("pompa basenu")
        if 19 <= hour <= 21 and plan["weekend"]:
            values["Duze_AGD_kWh"] += rng.uniform(6.0, 9.0)
            labels.append("sauna")
        if hour >= 22 or hour <= 5:
            values["Duze_AGD_kWh"] += rng.uniform(3.5, 7.4)
            labels.append("ładowanie EV")

    return values, labels


def _plan_flex_events(
    rng: np.random.RandomState, plan: dict, day: date, scenario_id: int
) -> list[FlexEvent]:
    events: list[FlexEvent] = []
    if plan["dishwasher"] and not plan["trip"]:
        profile = DEVICE_PROFILES["Zmywarka"]
        events.append(
            FlexEvent(
                "Zmywarka",
                day,
                plan["dishwasher_start"],
                int(rng.randint(profile["duration"][0], profile["duration"][1])),
                _q3(rng.uniform(*profile["energy"])),
            )
        )
    if plan["wash"] and not plan["trip"]:
        profile = DEVICE_PROFILES["Pralka"]
        duration = int(rng.randint(profile["duration"][0], profile["duration"][1]))
        events.append(
            FlexEvent(
                "Pralka", day, plan["wash_start"], duration, _q3(rng.uniform(*profile["energy"]))
            )
        )
        if plan["dryer"]:
            profile = DEVICE_PROFILES["Suszarka"]
            events.append(
                FlexEvent(
                    "Suszarka",
                    day,
                    min(plan["wash_start"] + duration, 21),
                    int(rng.randint(profile["duration"][0], profile["duration"][1])),
                    _q3(rng.uniform(*profile["energy"])),
                )
            )
    return events


def simulate_household(
    weather: list[WeatherHour], seed: int = SEED, scenario_id: int = 4
) -> tuple[list[ConsumptionHour], list[FlexEvent]]:
    rng = np.random.RandomState(seed + scenario_id - 4)
    by_day: dict[date, list[WeatherHour]] = {}
    for record in weather:
        by_day.setdefault(record.timestamp.date(), []).append(record)

    days = sorted(by_day)
    plans = {day: _draw_day_plan(rng, day, scenario_id) for day in days}
    if len(days) >= 30 and not any(plan["trip"] for plan in plans.values()):
        plans[days[int(rng.randint(0, len(days)))]]["trip"] = True

    consumption: list[ConsumptionHour] = []
    all_events: list[FlexEvent] = []
    for day in days:
        plan = plans[day]
        day_events = _plan_flex_events(rng, plan, day, scenario_id)
        all_events.extend(day_events)
        for record in sorted(by_day[day], key=lambda item: item.timestamp):
            hour = record.timestamp.hour
            values, labels = _simulate_hour(
                rng,
                plan,
                hour,
                record.timestamp.month,
                record.temperature,
                record.cloud_cover,
                scenario_id,
            )
            for event in day_events:
                if event.start_hour <= hour < event.start_hour + event.duration_h:
                    values["Duze_AGD_kWh"] += float(event.energy_kwh) / event.duration_h
                    labels.append(event.device.lower())
            categories = tuple(_q3(values[name]) for name in CATEGORIES)
            consumption.append(
                ConsumptionHour(record.timestamp, categories, "; ".join(dict.fromkeys(labels)))
            )
    return consumption, all_events


def write_consumption_csv(records: list[ConsumptionHour], path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(CONSUMPTION_COLUMNS)
        for record in records:
            writer.writerow(
                [
                    record.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    record.timestamp.strftime("%A"),
                    record.timestamp.hour,
                    *[f"{value:.3f}" for value in record.categories],
                    f"{record.total:.3f}",
                    record.events,
                ]
            )


def write_events_csv(events: list[FlexEvent], path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(EVENT_COLUMNS)
        for event in events:
            writer.writerow(
                [
                    event.day.isoformat(),
                    event.device,
                    event.start_hour,
                    event.duration_h,
                    f"{event.energy_kwh:.3f}",
                ]
            )


def read_events_csv(path: Path | str) -> list[FlexEvent]:
    events: list[FlexEvent] = []
    with Path(path).open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None or not set(EVENT_COLUMNS).issubset(reader.fieldnames):
            raise ValueError(f"File {Path(path).name} is missing required event columns.")
        for row in reader:
            events.append(
                FlexEvent(
                    row["Urzadzenie"],
                    date.fromisoformat(row["Data"]),
                    int(row["Start_Godzina"]),
                    int(row["Czas_h"]),
                    Decimal(row["Energia_kWh"]),
                )
            )
    return events
