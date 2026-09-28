"""Symulator fotowoltaiki: roczny bilans, warianty zwrotu A/B i rekomendacje.

Produkcja PV pochodzi z rzeczywistego godzinowego promieniowania słonecznego
(Open-Meteo, Kopenhaga). Wariant A zachowuje obecne nawyki, wariant B przesuwa
elastyczne zdarzenia (zmywarka, pralka, suszarka) na godzinę maksymalnego
promieniowania w oknie 9–15 tego samego dnia.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from energy.household import ConsumptionHour, FlexEvent
from energy.tariffs import (
    EXPORT_PRICE,
    PV_COST_PER_KWP,
    PV_OPEX_RATE,
    PV_PERFORMANCE_RATIO,
    energy_cost,
)
from energy.weather import WeatherHour

COMPARE_VARIANTS_KWP = (2, 3, 4, 5, 6, 8, 10)
PV_WINDOW = range(9, 16)
RECOMMENDATION_DEVICES = ("Zmywarka", "Pralka", "Suszarka")
DUZE_AGD_INDEX = 5


@dataclass(frozen=True)
class VariantResult:
    self_kwh: Decimal
    exported_kwh: Decimal
    grid_kwh: Decimal
    savings: Decimal
    payback_years: Decimal | None


@dataclass(frozen=True)
class SimulationResult:
    kwp: Decimal
    production_kwh: Decimal
    consumption_kwh: Decimal
    variant_a: VariantResult
    variant_b: VariantResult

    @property
    def coverage_a(self) -> Decimal:
        return self.variant_a.self_kwh / self.consumption_kwh * 100

    @property
    def coverage_b(self) -> Decimal:
        return self.variant_b.self_kwh / self.consumption_kwh * 100


@dataclass(frozen=True)
class DeviceEffect:
    device: str
    moved_kwh: Decimal
    grid_saved_kwh: Decimal
    money_saved: Decimal


@dataclass(frozen=True)
class WeekProfile:
    timestamps: list[datetime]
    load: list[Decimal]
    pv: list[Decimal]
    grid_a: list[Decimal]
    grid_b: list[Decimal]


def pv_production(radiation: float, kwp: Decimal) -> Decimal:
    """kWh z godziny: irradiancja [W/m²] × 1 h = Wh/m² → kWh/kWp × sprawność."""
    return Decimal(str(radiation)) / 1000 * kwp * PV_PERFORMANCE_RATIO


def _radiation_by_hour(weather: list[WeatherHour]) -> dict[tuple, float]:
    return {(r.timestamp.date(), r.timestamp.hour): r.radiation for r in weather}


def _shift_records(
    records: list[ConsumptionHour],
    events: list[FlexEvent],
    radiation: dict[tuple, float],
    devices: tuple[str, ...] | None = None,
) -> list[ConsumptionHour]:
    index = {(r.timestamp.date(), r.timestamp.hour): i for i, r in enumerate(records)}
    values = [list(record.categories) for record in records]
    for event in events:
        if devices is not None and event.device not in devices:
            continue
        best_start = max(PV_WINDOW, key=lambda h: radiation.get((event.day, h), 0.0))
        if best_start == event.start_hour:
            continue
        per_hour = event.energy_kwh / event.duration_h
        for hour in range(event.start_hour, event.start_hour + event.duration_h):
            position = index.get((event.day, hour))
            if position is not None:
                values[position][DUZE_AGD_INDEX] -= per_hour
        for hour in range(best_start, best_start + event.duration_h):
            position = index.get((event.day, hour))
            if position is not None:
                values[position][DUZE_AGD_INDEX] += per_hour
    return [
        ConsumptionHour(
            record.timestamp,
            tuple(max(value, Decimal(0)) for value in categories),
            record.events,
        )
        for record, categories in zip(records, values, strict=True)
    ]


def _variant(
    records: list[ConsumptionHour], weather: list[WeatherHour], kwp: Decimal
) -> tuple[VariantResult, Decimal]:
    cost_without_pv = energy_cost([r.timestamp for r in records], [r.total for r in records])
    radiation = {r.timestamp: r.radiation for r in weather}
    self_kwh = exported = grid = Decimal(0)
    grid_timestamps: list[datetime] = []
    grid_amounts: list[Decimal] = []
    production = Decimal(0)
    for record in records:
        pv = pv_production(radiation.get(record.timestamp, 0.0), kwp)
        production += pv
        load = record.total
        self_kwh += min(load, pv)
        exported += max(pv - load, Decimal(0))
        grid_amount = max(load - pv, Decimal(0))
        grid += grid_amount
        grid_timestamps.append(record.timestamp)
        grid_amounts.append(grid_amount)
    grid_cost = energy_cost(grid_timestamps, grid_amounts)
    capex = PV_COST_PER_KWP * kwp
    savings = cost_without_pv - grid_cost + exported * EXPORT_PRICE - PV_OPEX_RATE * capex
    payback = (capex / savings) if savings > 0 else None
    return VariantResult(self_kwh, exported, grid, savings, payback), production


def simulate(
    records: list[ConsumptionHour],
    weather: list[WeatherHour],
    events: list[FlexEvent],
    kwp: Decimal,
) -> SimulationResult:
    variant_a, production = _variant(records, weather, kwp)
    shifted = _shift_records(records, events, _radiation_by_hour(weather))
    variant_b, _ = _variant(shifted, weather, kwp)
    consumption = sum((record.total for record in records), Decimal(0))
    return SimulationResult(kwp, production, consumption, variant_a, variant_b)


def compare_variants(
    records: list[ConsumptionHour],
    weather: list[WeatherHour],
    events: list[FlexEvent],
    variants_kwp: tuple[int, ...] = COMPARE_VARIANTS_KWP,
) -> list[SimulationResult]:
    return [simulate(records, weather, events, Decimal(kwp)) for kwp in variants_kwp]


def device_effects(
    records: list[ConsumptionHour],
    weather: list[WeatherHour],
    events: list[FlexEvent],
    kwp: Decimal,
) -> list[DeviceEffect]:
    """Efekt przesunięcia pojedynczego typu urządzenia względem wariantu A."""
    variant_a, _ = _variant(records, weather, kwp)
    radiation = _radiation_by_hour(weather)
    effects = []
    for device in RECOMMENDATION_DEVICES:
        device_events = [event for event in events if event.device == device]
        moved = [event for event in device_events if event.start_hour not in PV_WINDOW]
        shifted = _shift_records(records, device_events, radiation, devices=(device,))
        partial, _ = _variant(shifted, weather, kwp)
        effects.append(
            DeviceEffect(
                device,
                sum((event.energy_kwh for event in moved), Decimal(0)),
                variant_a.grid_kwh - partial.grid_kwh,
                partial.savings - variant_a.savings,
            )
        )
    return effects


def representative_week(
    records: list[ConsumptionHour],
    weather: list[WeatherHour],
    events: list[FlexEvent],
    kwp: Decimal,
    month: int,
) -> WeekProfile:
    """Pierwszy pełny tydzień (poniedziałek–niedziela) wybranego miesiąca."""
    first_monday = next(
        record.timestamp.date()
        for record in records
        if record.timestamp.month == month and record.timestamp.weekday() == 0
    )
    week_end = first_monday + timedelta(days=7)
    selected = [record for record in records if first_monday <= record.timestamp.date() < week_end]
    shifted = _shift_records(records, events, _radiation_by_hour(weather))
    shifted_by_ts = {record.timestamp: record for record in shifted}
    radiation = {record.timestamp: record.radiation for record in weather}

    timestamps: list[datetime] = []
    load: list[Decimal] = []
    pv: list[Decimal] = []
    grid_a: list[Decimal] = []
    grid_b: list[Decimal] = []
    for record in selected:
        production = pv_production(radiation.get(record.timestamp, 0.0), kwp)
        timestamps.append(record.timestamp)
        load.append(record.total)
        pv.append(production)
        grid_a.append(max(record.total - production, Decimal(0)))
        shifted_record = shifted_by_ts.get(record.timestamp, record)
        grid_b.append(max(shifted_record.total - production, Decimal(0)))
    return WeekProfile(timestamps, load, pv, grid_a, grid_b)
