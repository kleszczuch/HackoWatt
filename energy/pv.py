"""Symulator fotowoltaiki: roczny bilans, warianty zwrotu A/B i rekomendacje.

Produkcja PV pochodzi z rzeczywistego godzinowego promieniowania słonecznego
(Open-Meteo, Kopenhaga). Wariant A zachowuje obecne nawyki, wariant B przesuwa
elastyczne zdarzenia (zmywarka, pralka, suszarka) na godzinę maksymalnego
promieniowania w oknie 9–15 tego samego dnia.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from energy.household import ConsumptionHour, FlexEvent
from energy.tariffs import (
    EXPORT_PRICE,
    PV_COST_PER_KWP,
    PV_OPEX_RATE,
    PV_PERFORMANCE_RATIO,
    TariffConfig,
    configured_energy_cost,
    energy_cost,
    price_for_hour,
)
from energy.weather import WeatherHour


def _energy_cost(
    tariff: TariffConfig | None,
    timestamps: list[datetime],
    amounts: list[Decimal],
    dynamic: dict[datetime, Decimal] | None,
) -> Decimal:
    """Koszt energii według wybranej taryfy albo domyślnej stawki stałej."""
    if tariff is None:
        return energy_cost(timestamps, amounts)
    return configured_energy_cost(tariff, timestamps, amounts, dynamic)


COMPARE_VARIANTS_KWP = (2, 3, 4, 5, 6, 8, 10)
PV_WINDOW = range(9, 16)
RECOMMENDATION_DEVICES = ("Zmywarka", "Pralka", "Suszarka")
DUZE_AGD_INDEX = 5
MIN_KWP = Decimal("1.0")
MAX_KWP = Decimal("150.0")
PAYBACK_MAX_KWP = Decimal("15.0")
KWP_STEP = Decimal("0.1")
BATTERY_ROUND_TRIP_EFFICIENCY = Decimal("0.90")


@dataclass(frozen=True)
class StorageConfig:
    """Parametry magazynu energii: pojemność, moc i koszt zakupu."""

    capacity_kwh: Decimal = Decimal(0)
    power_kw: Decimal = Decimal(0)
    cost_eur: Decimal = Decimal(0)


@dataclass(frozen=True)
class VariantResult:
    """Wynik jednego wariantu PV: pokrycie, eksport, import i oszczędności."""

    self_kwh: Decimal
    exported_kwh: Decimal
    grid_kwh: Decimal
    savings: Decimal
    payback_years: Decimal | None
    battery_charged_kwh: Decimal = Decimal(0)
    battery_delivered_kwh: Decimal = Decimal(0)


@dataclass(frozen=True)
class SimulationResult:
    """Kompletne podsumowanie symulacji dla konkretnej mocy instalacji PV."""

    kwp: Decimal
    production_kwh: Decimal
    consumption_kwh: Decimal
    variant_a: VariantResult
    variant_b: VariantResult
    storage: StorageConfig = StorageConfig()

    @property
    def coverage_a(self) -> Decimal:
        return self.variant_a.self_kwh / self.consumption_kwh * 100

    @property
    def coverage_b(self) -> Decimal:
        return self.variant_b.self_kwh / self.consumption_kwh * 100

    @property
    def investment_eur(self) -> Decimal:
        return PV_COST_PER_KWP * self.kwp + self.storage.cost_eur


@dataclass(frozen=True)
class DeviceEffect:
    """Efekt przesunięcia jednego urządzenia w wariancie B względem wariantu A."""

    device: str
    moved_kwh: Decimal
    grid_saved_kwh: Decimal
    money_saved: Decimal


@dataclass(frozen=True)
class WeekProfile:
    """Profil tygodniowy z obciążeniem, produkcją PV i kupnem z sieci."""

    timestamps: list[datetime]
    load: list[Decimal]
    pv: list[Decimal]
    grid_a: list[Decimal]
    grid_b: list[Decimal]
    battery_b: list[Decimal]


@dataclass(frozen=True)
class DayProfile:
    """Dzienny podział zużycia, produkcji i importu z sieci."""

    day: date
    consumption_kwh: Decimal
    production_kwh: Decimal
    grid_a_kwh: Decimal
    grid_b_kwh: Decimal


@dataclass(frozen=True)
class CapacityChoice:
    """Wybrana moc PV wraz z odczytem pokrycia i zwrotu inwestycji."""

    kwp: Decimal | None
    coverage: Decimal | None
    payback_years: Decimal | None
    target_met: bool


def pv_production(radiation: float, kwp: Decimal) -> Decimal:
    """kWh z godziny: irradiancja [W/m²] × 1 h = Wh/m² → kWh/kWp × sprawność.
    Oblicza produkcję PV w danej godzinie na podstawie promieniowania i mocy instalacji."""
    return Decimal(str(radiation)) / 1000 * kwp * PV_PERFORMANCE_RATIO


def _radiation_by_hour(weather: list[WeatherHour]) -> dict[tuple, float]:
    """Buduje mapę promieniowania w godzinach i dniach do przesunięć elastycznych."""
    return {(r.timestamp.date(), r.timestamp.hour): r.radiation for r in weather}


def _shift_records(
    records: list[ConsumptionHour],
    events: list[FlexEvent],
    radiation: dict[tuple, float],
    devices: tuple[str, ...] | None = None,
) -> list[ConsumptionHour]:
    """Przesuwa elastyczne urządzenia do godzin z największym promieniowaniem słonecznym."""
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


def _hour_balance(
    load: Decimal, production: Decimal, charge: Decimal, storage: StorageConfig
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]:
    """Rozwiązuje bilans godzinowy PV, zużycia, eksportu, importu i magazynowania."""
    direct = min(load, production)
    surplus = production - direct
    deficit = load - direct
    charged = delivered = Decimal(0)
    if storage.capacity_kwh > 0:
        charged = min(surplus, storage.power_kw, storage.capacity_kwh - charge)
        charge += charged
        surplus -= charged
        delivered = min(deficit, storage.power_kw, charge * BATTERY_ROUND_TRIP_EFFICIENCY)
        charge = max(charge - delivered / BATTERY_ROUND_TRIP_EFFICIENCY, Decimal(0))
        deficit -= delivered
    return direct + delivered, surplus, deficit, charged, delivered, charge


def _settled_charge(
    hours: list[tuple[Decimal, Decimal]], storage: StorageConfig, full_year: bool
) -> Decimal:
    """Ustala stan początkowy baterii na podstawie nadwyżek z poprzednich godzin."""
    if not full_year or storage.capacity_kwh <= 0:
        return Decimal(0)
    initial = Decimal(0)
    for _ in range(24):
        charge = initial
        for load, production in hours:
            _, _, _, _, _, charge = _hour_balance(load, production, charge, storage)
        if charge == initial:
            break
        initial = charge
    return initial


def _variant(
    records: list[ConsumptionHour],
    weather: list[WeatherHour],
    kwp: Decimal,
    storage: StorageConfig = StorageConfig(),
    tariff: TariffConfig | None = None,
    dynamic: dict[datetime, Decimal] | None = None,
) -> tuple[VariantResult, Decimal]:
    """Oblicza wynik jednego wariantu PV: pokrycie, oszczędności i zwrot inwestycji."""
    cost_without_pv = _energy_cost(
        tariff, [r.timestamp for r in records], [r.total for r in records], dynamic
    )
    radiation = {r.timestamp: r.radiation for r in weather}
    self_kwh = exported = grid = Decimal(0)
    grid_timestamps: list[datetime] = []
    grid_amounts: list[Decimal] = []
    production = Decimal(0)
    hours = [
        (record.total, pv_production(radiation.get(record.timestamp, 0.0), kwp))
        for record in records
    ]
    charge = _settled_charge(hours, storage, len(records) >= 8760)
    charged_total = delivered_total = Decimal(0)
    for record, (load, pv_kwh) in zip(records, hours, strict=True):
        production += pv_kwh
        used, exported_hour, grid_amount, charged, delivered, charge = _hour_balance(
            load, pv_kwh, charge, storage
        )
        self_kwh += used
        exported += exported_hour
        charged_total += charged
        delivered_total += delivered
        grid += grid_amount
        grid_timestamps.append(record.timestamp)
        grid_amounts.append(grid_amount)
    grid_cost = _energy_cost(tariff, grid_timestamps, grid_amounts, dynamic)
    pv_capex = PV_COST_PER_KWP * kwp
    capex = pv_capex + storage.cost_eur
    savings = cost_without_pv - grid_cost + exported * EXPORT_PRICE - PV_OPEX_RATE * pv_capex
    payback = (capex / savings) if savings > 0 else None
    return VariantResult(
        self_kwh, exported, grid, savings, payback, charged_total, delivered_total
    ), production


def simulate(
    records: list[ConsumptionHour],
    weather: list[WeatherHour],
    events: list[FlexEvent],
    kwp: Decimal,
    storage: StorageConfig = StorageConfig(),
    tariff: TariffConfig | None = None,
    dynamic: dict[datetime, Decimal] | None = None,
) -> SimulationResult:
    """Porównuje wariant A i B dla jednej mocy PV i zwraca kompletne podsumowanie."""
    variant_a, production = _variant(records, weather, kwp, storage, tariff, dynamic)
    shifted = _shift_records(records, events, _radiation_by_hour(weather))
    variant_b, _ = _variant(shifted, weather, kwp, storage, tariff, dynamic)
    consumption = sum((record.total for record in records), Decimal(0))
    return SimulationResult(kwp, production, consumption, variant_a, variant_b, storage)


def compare_variants(
    records: list[ConsumptionHour],
    weather: list[WeatherHour],
    events: list[FlexEvent],
    variants_kwp: tuple[int, ...] = COMPARE_VARIANTS_KWP,
    storage: StorageConfig = StorageConfig(),
    tariff: TariffConfig | None = None,
    dynamic: dict[datetime, Decimal] | None = None,
) -> list[SimulationResult]:
    """Uruchamia symulację dla wielu mocy instalacji i zwraca listę wyników."""
    return [
        simulate(records, weather, events, Decimal(kwp), storage, tariff, dynamic)
        for kwp in variants_kwp
    ]


def choose_capacity(
    records: list[ConsumptionHour],
    weather: list[WeatherHour],
    events: list[FlexEvent],
    goal: str,
    storage: StorageConfig = StorageConfig(),
    tariff: TariffConfig | None = None,
    dynamic: dict[datetime, Decimal] | None = None,
) -> CapacityChoice:
    """Dobierz moc dla 100% pokrycia lub zwrotu wariantu B."""
    if goal not in {"coverage", "payback"}:
        raise ValueError(f"Nieznany cel doboru PV: {goal}")

    consumption = sum((record.total for record in records), Decimal(0))
    if consumption <= 0:
        raise ValueError("Roczne zużycie musi być dodatnie.")
    shifted = _shift_records(records, events, _radiation_by_hour(weather))
    radiation = {record.timestamp: record.radiation for record in weather}
    hours = [
        (
            record.total,
            pv_production(radiation.get(record.timestamp, 0.0), Decimal(1)),
            tariff.price_at(record.timestamp, dynamic)[0]
            if tariff is not None
            else price_for_hour(record.timestamp.hour),
        )
        for record in shifted
    ]

    def evaluate(step: int) -> tuple[CapacityChoice, Decimal]:
        kwp = MIN_KWP + KWP_STEP * step
        self_kwh = exported = gross_savings = Decimal(0)
        energy_hours = [(load, production_per_kwp * kwp) for load, production_per_kwp, _ in hours]
        charge = _settled_charge(energy_hours, storage, len(records) >= 8760)
        grid = Decimal(0)
        for load, production_per_kwp, price in hours:
            production = production_per_kwp * kwp
            used, exported_hour, grid_hour, _, _, charge = _hour_balance(
                load, production, charge, storage
            )
            self_kwh += used
            exported += exported_hour
            grid += grid_hour
            gross_savings += used * price
        coverage = self_kwh / consumption * 100
        pv_capex = PV_COST_PER_KWP * kwp
        capex = pv_capex + storage.cost_eur
        savings = gross_savings + exported * EXPORT_PRICE - PV_OPEX_RATE * pv_capex
        payback = capex / savings if savings > 0 else None

        return CapacityChoice(kwp, coverage, payback, grid == 0), grid

    if goal == "coverage":
        last = int((MAX_KWP - MIN_KWP) / KWP_STEP)
        last_choice, lowest_grid = evaluate(last)
        low, high = 0, last
        while low < high:
            middle = (low + high) // 2
            _, grid = evaluate(middle)
            if grid <= lowest_grid:
                high = middle
            else:
                low = middle + 1
        return evaluate(low)[0] if low != last else last_choice

    best = CapacityChoice(None, None, None, False)
    for step in range(int((PAYBACK_MAX_KWP - MIN_KWP) / KWP_STEP) + 1):
        choice, _ = evaluate(step)
        if choice.payback_years is not None and (
            best.payback_years is None or choice.payback_years < best.payback_years
        ):
            best = choice
    return best


def device_effects(
    records: list[ConsumptionHour],
    weather: list[WeatherHour],
    events: list[FlexEvent],
    kwp: Decimal,
    storage: StorageConfig = StorageConfig(),
    tariff: TariffConfig | None = None,
    dynamic: dict[datetime, Decimal] | None = None,
) -> list[DeviceEffect]:
    """Efekt przesunięcia pojedynczego typu urządzenia względem wariantu A.
    Mierzy, jak bardzo przesunięcie jednego typu urządzenia poprawia bilans PV."""
    variant_a, _ = _variant(records, weather, kwp, storage, tariff, dynamic)
    radiation = _radiation_by_hour(weather)
    effects = []
    for device in RECOMMENDATION_DEVICES:
        device_events = [event for event in events if event.device == device]
        moved = [event for event in device_events if event.start_hour not in PV_WINDOW]
        shifted = _shift_records(records, device_events, radiation, devices=(device,))
        partial, _ = _variant(shifted, weather, kwp, storage, tariff, dynamic)
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
    storage: StorageConfig = StorageConfig(),
) -> WeekProfile:
    """Zwraca reprezentatywny tydzień danego miesiąca do wizualizacji profilu ładowania."""
    first_monday = next(
        record.timestamp.date()
        for record in records
        if record.timestamp.month == month and record.timestamp.weekday() == 0
    )
    week_end = first_monday + timedelta(days=7)
    selected = [record for record in records if first_monday <= record.timestamp.date() < week_end]
    shifted = _shift_records(records, events, _radiation_by_hour(weather))
    radiation = {record.timestamp: record.radiation for record in weather}

    def grid_and_battery(series: list[ConsumptionHour]) -> dict[datetime, tuple[Decimal, Decimal]]:
        hours = [
            (record.total, pv_production(radiation.get(record.timestamp, 0.0), kwp))
            for record in series
        ]
        charge = _settled_charge(hours, storage, len(series) >= 8760)
        profile = {}
        for record, (load, production) in zip(series, hours, strict=True):
            _, _, grid, _, delivered, charge = _hour_balance(load, production, charge, storage)
            profile[record.timestamp] = (grid, delivered)
        return profile

    profile_a = grid_and_battery(records)
    profile_b = grid_and_battery(shifted)

    timestamps: list[datetime] = []
    load: list[Decimal] = []
    pv: list[Decimal] = []
    grid_a: list[Decimal] = []
    grid_b: list[Decimal] = []
    battery_b: list[Decimal] = []
    for record in selected:
        production = pv_production(radiation.get(record.timestamp, 0.0), kwp)
        timestamps.append(record.timestamp)
        load.append(record.total)
        pv.append(production)
        grid_a.append(profile_a[record.timestamp][0])
        grid_b.append(profile_b[record.timestamp][0])
        battery_b.append(profile_b[record.timestamp][1])
    return WeekProfile(timestamps, load, pv, grid_a, grid_b, battery_b)


def daily_week_summary(week: WeekProfile) -> list[DayProfile]:
    """Sumy dobowe z tych samych godzin, które tworzą wykres tygodnia."""
    totals: dict[date, list[Decimal]] = {}
    for stamp, load, production, grid_a, grid_b in zip(
        week.timestamps, week.load, week.pv, week.grid_a, week.grid_b, strict=True
    ):
        day_totals = totals.setdefault(stamp.date(), [Decimal(0) for _ in range(4)])
        for index, value in enumerate((load, production, grid_a, grid_b)):
            day_totals[index] += value
    return [DayProfile(day, *values) for day, values in totals.items()]
