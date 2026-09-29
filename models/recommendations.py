"""Rekomendacje godzin pracy urządzeń na jutro z lokalnym modelem AI.

Python liczy wszystkie godziny i kwoty (prognoza + PV + magazyn + taryfa);
model Ollamy jedynie wybiera wariant z zamkniętej listy kandydatów i pisze
uzasadnienie. Walidacja odrzuca każdą odpowiedź spoza kandydatów. Moduł nie
korzysta z widoków ani modeli Django — tylko z czystych funkcji pakietu energy.

Publiczny, stabilny interfejs dla warstwy Django:

    build_plan(
        *,
        scenario_id,          # identyfikator scenariusza (do klucza bufora)
        data_dir,             # katalog danych scenariusza (Path lub str)
        tariff,               # energy.tariffs.TariffConfig
        dynamic,              # dict[datetime, Decimal] | None — ceny RCE
        kwp,                  # Decimal — moc instalacji PV
        storage,              # energy.pv.StorageConfig
        lang="pl",            # język szablonowych uzasadnień fallbacku
        use_cache=True,       # False wymusza przeliczenie pomimo bufora
        cache_dir=None,       # domyślnie data/recommendations (rodzic data_dir)
    ) -> dict

Zwraca słownik: date, scenario_id, status ("ready" | "no_data"), source
("local_ai" | "calculated_fallback" | None), currency ("EUR"), recommendations,
total_daily_saving (pomijane przy no_data) oraz metadane generated_at i inputs.
Przy source == "calculated_fallback" dodaje fallback_cause
("ollama_unavailable" | "invalid_response").
"""

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median

from energy import data as energy_data
from energy.forecasting import FORECAST_FILENAME
from energy.household import FLEX_EVENTS_FILENAME, HISTORY_FILENAME, ConsumptionHour, FlexEvent
from energy.pv import DEFAULT_STORAGE, StorageConfig, hour_balance, pv_production
from energy.tariffs import CURRENCY, EXPORT_PRICE, MODE_DYNAMIC, TariffConfig, serialize_tariff
from energy.weather import FORECAST_WEATHER_FILENAME
from models import ollama_client

MIN_OCCURRENCES = 2
HISTORY_DAYS = 35
CACHE_DIRNAME = "recommendations"
CACHE_VERSION = 10

# Okna pracy (godzina_od, godzina_do); cykl musi zmieścić się w całości.
DEVICE_WINDOWS = {
    "Zmywarka": (7, 22),
    "Pralka": (8, 20),
    "Suszarka": (0, 21),  # start nie wcześniej niż koniec cyklu pralki
}
DEVICE_SLUGS = {"Zmywarka": "dishwasher", "Pralka": "washer", "Suszarka": "dryer"}
DEVICE_ORDER = ("Zmywarka", "Pralka", "Suszarka")
POOL_PUMP = "pompa basenu"
POOL_WINDOW = (7, 22)
_DEVICE_EVENT_LABELS = {name.lower() for name in DEVICE_ORDER}

_FALLBACK_REASONS = {
    "pl": "Najniższy koszt domu: spośród dozwolonych godzin ta daje największą oszczędność.",
    "en": "Lowest household cost: this allowed hour gives the biggest saving.",
}
_KEEP_REASONS = {
    "pl": "W dopuszczalnych godzinach nie znaleziono tańszego startu dla całego domu.",
    "en": "No allowed start hour lowers the total household cost.",
}


@dataclass(frozen=True)
class CycleForecast:
    """Przewidywany jutrzejszy cykl urządzenia: mediany z historii dnia tygodnia."""

    device: str
    start_hour: int
    duration_h: int
    energy_kwh: Decimal
    occurrences: int


@dataclass(frozen=True)
class Candidate:
    """Godzina startu z oszczędnością pełnego kosztu domu względem układu bazowego."""

    hour: int
    saving: Decimal


@dataclass(frozen=True)
class DevicePlan:
    """Cykl urządzenia wraz z listą dopuszczalnych kandydatów na godzinę startu."""

    device: str
    slug: str
    cycle: CycleForecast
    candidates: list[Candidate]


def infer_cycle(events: list[FlexEvent], device: str, weekday: int) -> CycleForecast | None:
    """Wnioskuje jutrzejszy cykl z wystąpień urządzenia w ten sam dzień tygodnia."""
    matching = [e for e in events if e.device == device and e.day.weekday() == weekday]
    if len(matching) < MIN_OCCURRENCES:
        return None
    return CycleForecast(
        device=device,
        start_hour=int(round(median(e.start_hour for e in matching))),
        duration_h=max(1, int(round(median(e.duration_h for e in matching)))),
        energy_kwh=median(e.energy_kwh for e in matching),
        occurrences=len(matching),
    )


def infer_pool_cycle(
    records: list[ConsumptionHour], events: list[FlexEvent], weekday: int
) -> CycleForecast | None:
    """Pełne dzienne bloki pompy z energią wydzieloną z kategorii dużego AGD."""
    by_day: dict[date, list[ConsumptionHour]] = defaultdict(list)
    for record in records:
        if record.timestamp.weekday() == weekday and POOL_PUMP in record.events.split("; "):
            by_day[record.timestamp.date()].append(record)
    cycles = []
    for day, rows in by_day.items():
        hours = sorted(row.timestamp.hour for row in rows)
        if not hours or hours != list(range(hours[0], hours[0] + len(hours))):
            continue
        energy = Decimal(0)
        for row in rows:
            other_devices = sum(
                (
                    event.energy_kwh / event.duration_h
                    for event in events
                    if event.day == day
                    and event.start_hour <= row.timestamp.hour < event.start_hour + event.duration_h
                ),
                Decimal(0),
            )
            energy += max(row.categories[5] - other_devices, Decimal(0))
        if energy > 0:
            cycles.append((hours[0], len(hours), energy))
    if len(cycles) < MIN_OCCURRENCES:
        return None
    return CycleForecast(
        device=POOL_PUMP,
        start_hour=int(round(median(start for start, _, _ in cycles))),
        duration_h=int(round(median(duration for _, duration, _ in cycles))),
        energy_kwh=median(energy for _, _, energy in cycles),
        occurrences=len(cycles),
    )


def observed_events(records: list[ConsumptionHour], weekday: int) -> list[dict]:
    """Zdarzenia godzinowe jako liczba dni wystąpienia, bez prognozy i kwot."""
    if not records:
        return []
    end_day = max(record.timestamp.date() for record in records)
    first_day = end_day - timedelta(days=HISTORY_DAYS - 1)
    recent = [record for record in records if record.timestamp.date() >= first_day]
    matching_days = {
        record.timestamp.date() for record in recent if record.timestamp.weekday() == weekday
    }
    days_by_event: dict[str, set[date]] = defaultdict(set)
    for record in recent:
        for label in record.events.split(";"):
            event = label.strip()
            if event and event.lower() not in _DEVICE_EVENT_LABELS:
                days_by_event[event].add(record.timestamp.date())
    result = []
    for event, days in days_by_event.items():
        matching = len(days & matching_days)
        result.append(
            {
                "event": event,
                "days_in_history": len(days),
                "days_on_matching_weekday": matching,
                "matching_weekdays": len(matching_days),
                "status": "repeated" if matching >= MIN_OCCURRENCES else "observed_only",
            }
        )
    return sorted(
        result,
        key=lambda item: (
            -item["days_on_matching_weekday"],
            -item["days_in_history"],
            item["event"],
        ),
    )


def _device_history(events: list[FlexEvent], device: str, weekday: int) -> dict:
    days = {event.day for event in events if event.device == device}
    return {
        "history_days": len(days),
        "matching_weekday_days": sum(day.weekday() == weekday for day in days),
    }


def candidate_hours(
    window_start: int, window_end: int, duration_h: int, earliest: int = 0
) -> list[int]:
    """Pełne godziny startu, dla których cykl mieści się w całości w oknie."""
    start = max(window_start, earliest)
    return list(range(start, window_end - duration_h + 1))


def _day_cost(
    timestamps: list[datetime],
    loads: list[Decimal],
    radiation: dict[datetime, float],
    kwp: Decimal,
    storage: StorageConfig,
    tariff: TariffConfig,
    dynamic: dict[datetime, Decimal] | None,
) -> Decimal:
    """Pełny koszt domu na jutro: zakup z sieci po taryfie minus eksport."""
    grid_cost = Decimal(0)
    export_credit = Decimal(0)
    charge = Decimal(0)
    for moment, load in zip(timestamps, loads, strict=True):
        production = pv_production(radiation[moment], kwp)
        _, surplus, deficit, _, _, charge = hour_balance(load, production, charge, storage)
        grid_cost += tariff.price_at(moment, dynamic)[0] * deficit
        export_credit += surplus * EXPORT_PRICE
    return grid_cost - export_credit


def _shifted_loads(
    loads: list[Decimal],
    timestamps: list[datetime],
    from_hour: int,
    to_hour: int,
    duration_h: int,
    energy_kwh: Decimal,
) -> list[Decimal]:
    """Przenosi energię cyklu (równomiernie na godziny) między godzinami doby.

    Godziny cyklu wypadające poza dobę (np. start 23:00 przy długości 2 h) są
    pomijane po obu stronach: odejmowana i dodawana jest ta sama liczba godzin.
    """
    per_hour = energy_kwh / duration_h
    index = {moment.hour: position for position, moment in enumerate(timestamps)}
    from_hours = [hour for hour in range(from_hour, from_hour + duration_h) if hour in index]
    shifted = list(loads)
    for hour in from_hours:
        shifted[index[hour]] = max(shifted[index[hour]] - per_hour, Decimal(0))
    for hour in range(to_hour, to_hour + len(from_hours)):
        if hour in index:
            shifted[index[hour]] += per_hour
    return shifted


def _best(candidates: list[Candidate]) -> Candidate:
    """Maksymalna oszczędność; przy remisie wcześniejsza godzina."""
    return max(candidates, key=lambda candidate: (candidate.saving, -candidate.hour))


def _money(value: Decimal) -> str:
    """Zaokrąglenie prezentacyjne: 2 miejsca po przecinku jako string."""
    return str(value.quantize(Decimal("0.01")))


def _visible_saving(value: Decimal) -> bool:
    """Nie proponuj zmiany godziny, gdy na karcie widać 0,00 oszczędności."""
    return value > 0 and Decimal(_money(value)) > 0


def _fallback_reason(lang: str) -> str:
    return _FALLBACK_REASONS.get(lang, _FALLBACK_REASONS["pl"])


def _keep_reason(lang: str) -> str:
    return _KEEP_REASONS.get(lang, _KEEP_REASONS["pl"])


def _build_prompt(plans: list[DevicePlan], lang: str = "pl") -> str:
    """Prompt z zamkniętą listą wariantów per urządzenie; model tylko wybiera."""
    example = json.dumps(
        {
            "choices": [
                {
                    "device": plan.slug,
                    "to": f"{_best(plan.candidates).hour:02d}:00",
                    "reason": (
                        "This start lowers tomorrow's household cost."
                        if lang == "en"
                        else "Ta godzina obniża jutrzejszy koszt domu."
                    ),
                }
                for plan in plans
            ]
        },
        ensure_ascii=False,
    )
    lines = []
    for plan in plans:
        options = ", ".join(
            f'{{"to": "{candidate.hour:02d}:00", "saving": "{_money(candidate.saving)}"}}'
            for candidate in plan.candidates
        )
        if lang == "en":
            lines.append(
                f'- "{plan.slug}" (current start {plan.cycle.start_hour:02d}:00, '
                f"cycle {plan.cycle.duration_h} h): [{options}]"
            )
        else:
            lines.append(
                f'- "{plan.slug}" (obecny start {plan.cycle.start_hour:02d}:00, '
                f"cykl {plan.cycle.duration_h} h): [{options}]"
            )
    if lang == "en":
        introduction = (
            "You are a home assistant planning appliance use for tomorrow. "
            f"Return exactly {len(plans)} choice(s): one for each device listed below, "
            "and no other devices. Choose a listed start hour and explain your choice "
            "in one short English sentence. Return JSON only.\n"
            "Base the reason on the listed household saving; do not claim a lowest "
            "electricity rate or highest PV output without evidence.\n"
            f"Valid response using the best listed hours (you may choose other listed hours): "
            f"{example}\n"
        )
    else:
        introduction = (
            "Jesteś asystentem domowym planującym pracę urządzeń na jutro. "
            f"Zwróć dokładnie {len(plans)} odpowiedzi: po jednej dla każdego urządzenia "
            "z listy poniżej i żadnych innych. Wybierz podaną godzinę startu i uzasadnij "
            "wybór jednym krótkim zdaniem po polsku. Odpowiedz wyłącznie JSON-em.\n"
            "Uzasadniaj podaną oszczędnością całego domu; nie twierdź, że cena "
            "energii jest najniższa albo produkcja PV największa bez takich danych.\n"
            "Poprawna odpowiedź z najlepszymi godzinami (możesz wybrać inne podane "
            f"godziny): {example}\n"
        )
    return introduction + "\n".join(lines)


def _parse_hour(value: object) -> int | None:
    """Parsuje godzinę „HH:MM" od modelu; akceptuje wyłącznie pełne godziny."""
    if not isinstance(value, str):
        return None
    try:
        hour, minute = (int(part) for part in value.split(":"))
    except ValueError:
        return None
    if minute != 0 or not 0 <= hour <= 23:
        return None
    return hour


def _validate_choices(payload: dict | None, plans: list[DevicePlan]) -> dict | None:
    """Zwraca {slug: (godzina, reason)} albo None przy każdej niezgodności.

    Godzina „to" musi być wśród kandydatów danego urządzenia (dla suszarki
    dodatkowo nie wcześniej niż koniec cyklu pralki wybrany przez model),
    a uzasadnienie nie może być puste. Kwoty i godzina „from" nigdy nie
    pochodzą z modelu.
    """
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return None
    by_device: dict[str, tuple[object, object]] = {}
    for choice in choices:
        if not isinstance(choice, dict):
            return None
        device = choice.get("device")
        if not isinstance(device, str) or device in by_device:
            return None
        by_device[device] = (choice.get("to"), choice.get("reason"))
    if set(by_device) != {plan.slug for plan in plans}:
        return None

    selected: dict[str, tuple[int, str]] = {}
    washer_end: int | None = None
    for plan in plans:
        if plan.slug not in by_device:
            return None
        raw_to, raw_reason = by_device[plan.slug]
        hour = _parse_hour(raw_to)
        if hour is None or not isinstance(raw_reason, str) or not raw_reason.strip():
            return None
        valid = [
            candidate.hour for candidate in plan.candidates if _visible_saving(candidate.saving)
        ]
        if plan.device == "Suszarka" and washer_end is not None:
            window = DEVICE_WINDOWS["Suszarka"]
            allowed = candidate_hours(window[0], window[1], plan.cycle.duration_h, washer_end)
            valid = [candidate for candidate in valid if candidate in allowed]
        if hour not in valid:
            return None
        selected[plan.slug] = (hour, raw_reason.strip())
        if plan.device == "Pralka":
            washer_end = hour + plan.cycle.duration_h
    return selected


def _param_hash(
    tariff: TariffConfig,
    kwp: Decimal,
    storage: StorageConfig,
    lang: str,
    dynamic_prices: list[str | None] | None,
    data_fingerprint: str,
) -> str:
    """Krótki skrót parametrów wpływających na plan (bez ceny zakupu magazynu)."""
    payload = json.dumps(
        {
            "tariff": serialize_tariff(tariff),
            "kwp": str(kwp),
            "storage": [str(storage.capacity_kwh), str(storage.power_kw)],
            "lang": lang,
            "cache_version": CACHE_VERSION,
            "dynamic_prices": dynamic_prices,
            "data_fingerprint": data_fingerprint,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _data_fingerprint(data_dir: Path) -> str:
    digest = hashlib.sha256()
    for name in (
        HISTORY_FILENAME,
        FLEX_EVENTS_FILENAME,
        FORECAST_FILENAME,
        FORECAST_WEATHER_FILENAME,
    ):
        path = data_dir / name
        digest.update(name.encode("utf-8"))
        try:
            digest.update(path.read_bytes())
        except FileNotFoundError:
            digest.update(b"missing")
    return digest.hexdigest()[:12]


def _read_cache(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _no_data(scenario_id, day, missing_data: str, history_events: list[dict]) -> dict:
    return {
        "date": day.isoformat() if day is not None else None,
        "scenario_id": scenario_id,
        "status": "no_data",
        "source": None,
        "currency": CURRENCY,
        "recommendations": [],
        "observed_events": history_events,
        "missing_data": missing_data,
    }


def _target_date() -> date:
    """Dzień planu według lokalnego zegara serwera."""
    return date.today() + timedelta(days=1)


def _compute_plans(
    events: list[FlexEvent],
    weekday: int,
    timestamps: list[datetime],
    loads: list[Decimal],
    radiation: dict[datetime, float],
    kwp: Decimal,
    storage: StorageConfig,
    tariff: TariffConfig,
    dynamic: dict[datetime, Decimal] | None,
    washer_hour: int | None = None,
) -> list[DevicePlan]:
    """Cykle i kandydaci; pralka dobierana przed suszarką (jej okno od pralki).

    `washer_hour` wymusza godzinę pralki (wybór modelu), dzięki czemu kandydaci
    i oszczędności suszarki odpowiadają faktycznie wybranej parze godzin.
    """
    plans: list[DevicePlan] = []
    washer_end: int | None = None
    current_loads = loads
    current_cost = _day_cost(timestamps, loads, radiation, kwp, storage, tariff, dynamic)
    for device in DEVICE_ORDER:
        cycle = infer_cycle(events, device, weekday)
        if cycle is None:
            continue
        window = DEVICE_WINDOWS[device]
        earliest = washer_end if device == "Suszarka" and washer_end is not None else window[0]
        candidates = []
        for hour in candidate_hours(window[0], window[1], cycle.duration_h, earliest):
            shifted = _shifted_loads(
                current_loads,
                timestamps,
                cycle.start_hour,
                hour,
                cycle.duration_h,
                cycle.energy_kwh,
            )
            cost_after = _day_cost(timestamps, shifted, radiation, kwp, storage, tariff, dynamic)
            candidates.append(Candidate(hour, current_cost - cost_after))
        plans.append(DevicePlan(device, DEVICE_SLUGS[device], cycle, candidates))
        if device == "Pralka":
            profitable = [
                candidate for candidate in candidates if _visible_saving(candidate.saving)
            ]
            chosen_hour = (
                washer_hour
                if washer_hour is not None
                else _best(profitable).hour
                if profitable
                else cycle.start_hour
            )
            washer_end = chosen_hour + cycle.duration_h
            if chosen_hour != cycle.start_hour:
                current_loads = _shifted_loads(
                    current_loads,
                    timestamps,
                    cycle.start_hour,
                    chosen_hour,
                    cycle.duration_h,
                    cycle.energy_kwh,
                )
                current_cost = _day_cost(
                    timestamps, current_loads, radiation, kwp, storage, tariff, dynamic
                )
    return plans


def _pool_plan(
    cycle: CycleForecast | None,
    timestamps: list[datetime],
    loads: list[Decimal],
    radiation: dict[datetime, float],
    kwp: Decimal,
    storage: StorageConfig,
    tariff: TariffConfig,
    dynamic: dict[datetime, Decimal] | None,
) -> DevicePlan | None:
    if cycle is None:
        return None
    baseline = _day_cost(timestamps, loads, radiation, kwp, storage, tariff, dynamic)
    candidates = []
    for hour in candidate_hours(*POOL_WINDOW, cycle.duration_h):
        shifted = _shifted_loads(
            loads, timestamps, cycle.start_hour, hour, cycle.duration_h, cycle.energy_kwh
        )
        saving = baseline - _day_cost(timestamps, shifted, radiation, kwp, storage, tariff, dynamic)
        if _visible_saving(saving):
            candidates.append(Candidate(hour, saving))
    return DevicePlan(POOL_PUMP, "pool_pump", cycle, candidates) if candidates else None


def build_plan(
    *,
    scenario_id,
    data_dir: Path | str,
    tariff: TariffConfig,
    dynamic: dict[datetime, Decimal] | None,
    kwp: Decimal,
    storage: StorageConfig = DEFAULT_STORAGE,
    lang: str = "pl",
    use_cache: bool = True,
    cache_dir: Path | str | None = None,
) -> dict:
    """Buduje plan pracy urządzeń na jutro; kształt wyniku w docstringu modułu."""
    data_dir = Path(data_dir)
    tomorrow = _target_date()
    try:
        history_records = energy_data.load_history(data_dir)
        history_events = observed_events(history_records, tomorrow.weekday())
    except FileNotFoundError, energy_data.DemoDataError:
        history_records = []
        history_events = []
    try:
        forecast = energy_data.load_forecast(data_dir)
    except FileNotFoundError, energy_data.DemoDataError:
        return _no_data(scenario_id, tomorrow, "forecast", history_events)
    try:
        weather = energy_data.load_weather_forecast(data_dir)
    except FileNotFoundError, energy_data.DemoDataError:
        return _no_data(scenario_id, tomorrow, "weather", history_events)
    try:
        events = energy_data.load_history_events(data_dir)
    except FileNotFoundError, energy_data.DemoDataError:
        return _no_data(scenario_id, tomorrow, "history", history_events)

    # Prognoza może zaczynać się w środku dnia; wymagamy wszystkich 24 godzin
    # dokładnie jutra. Nie pokazujemy starej prognozy jako nowego planu.
    day_records = [record for record in forecast if record.timestamp.date() == tomorrow]
    if len(day_records) != 24 or {row.timestamp.hour for row in day_records} != set(range(24)):
        return _no_data(scenario_id, tomorrow, "forecast", history_events)
    day_records.sort(key=lambda record: record.timestamp)
    timestamps = [record.timestamp for record in day_records]
    radiation = {row.timestamp: row.radiation for row in weather}
    if any(moment not in radiation for moment in timestamps):
        return _no_data(scenario_id, tomorrow, "weather", history_events)
    dynamic_prices = (
        [str(dynamic[moment]) if dynamic and moment in dynamic else None for moment in timestamps]
        if tariff.mode == MODE_DYNAMIC
        else None
    )
    tariff_fallback_hours = (
        sum(price is None for price in dynamic_prices) if dynamic_prices is not None else 0
    )

    cache_dir = Path(cache_dir) if cache_dir is not None else data_dir.parent / CACHE_DIRNAME
    data_fingerprint = _data_fingerprint(data_dir)
    params_hash = _param_hash(tariff, kwp, storage, lang, dynamic_prices, data_fingerprint)
    cache_path = cache_dir / f"{scenario_id}_{tomorrow.isoformat()}_{params_hash}.json"
    if use_cache:
        cached = _read_cache(cache_path)
        if cached is not None:
            return cached

    loads = [record.total for record in day_records]
    plans = _compute_plans(
        events, tomorrow.weekday(), timestamps, loads, radiation, kwp, storage, tariff, dynamic
    )
    pool_cycle = infer_pool_cycle(history_records, events, tomorrow.weekday())
    pool_plan = _pool_plan(pool_cycle, timestamps, loads, radiation, kwp, storage, tariff, dynamic)
    if pool_plan is not None:
        plans.append(pool_plan)

    choice_plans = [
        DevicePlan(
            plan.device,
            plan.slug,
            plan.cycle,
            [candidate for candidate in plan.candidates if _visible_saving(candidate.saving)],
        )
        for plan in plans
        if any(_visible_saving(candidate.saving) for candidate in plan.candidates)
    ]
    selected = None
    source = "calculated_fallback"
    fallback_cause = None
    if choice_plans:
        response = ollama_client.generate(_build_prompt(choice_plans, lang))
        selected = _validate_choices(response, choice_plans)
        if selected is not None:
            source = "local_ai"
        else:
            fallback_cause = "ollama_unavailable" if response is None else "invalid_response"

    plans_by_device = {plan.device: plan for plan in plans}
    recommendations: list[dict] = []
    current_loads = list(loads)
    current_cost = _day_cost(timestamps, loads, radiation, kwp, storage, tariff, dynamic)
    washer_end: int | None = None
    for device in DEVICE_ORDER:
        slug = DEVICE_SLUGS[device]
        plan = plans_by_device.get(device)
        history = _device_history(events, device, tomorrow.weekday())
        if plan is None:
            recommendations.append({"device": slug, "status": "no_cycle", **history})
            continue
        window = DEVICE_WINDOWS[device]
        earliest = washer_end if device == "Suszarka" and washer_end is not None else window[0]
        candidates = []
        for candidate_hour in candidate_hours(*window, plan.cycle.duration_h, earliest):
            shifted = _shifted_loads(
                current_loads,
                timestamps,
                plan.cycle.start_hour,
                candidate_hour,
                plan.cycle.duration_h,
                plan.cycle.energy_kwh,
            )
            saving = current_cost - _day_cost(
                timestamps, shifted, radiation, kwp, storage, tariff, dynamic
            )
            if _visible_saving(saving):
                candidates.append(Candidate(candidate_hour, saving))
        choice = selected.get(plan.slug) if selected is not None else None
        selected_candidate = (
            next((item for item in candidates if item.hour == choice[0]), None)
            if choice is not None
            else None
        )
        if selected_candidate is not None:
            chosen = selected_candidate
            reason = choice[1]
        elif candidates:
            chosen = _best(candidates)
            reason = _fallback_reason(lang)
        else:
            recommendations.append(
                {
                    "device": slug,
                    "status": "keep",
                    "from": f"{plan.cycle.start_hour:02d}:00",
                    "to": f"{plan.cycle.start_hour:02d}:00",
                    "duration_h": plan.cycle.duration_h,
                    "reason": _keep_reason(lang),
                    **history,
                }
            )
            if device == "Pralka":
                washer_end = plan.cycle.start_hour + plan.cycle.duration_h
            continue
        hour, saving = chosen.hour, chosen.saving
        annual = saving * plan.cycle.occurrences * Decimal(365) / Decimal(HISTORY_DAYS)
        recommendations.append(
            {
                "device": slug,
                "from": f"{plan.cycle.start_hour:02d}:00",
                "to": f"{hour:02d}:00",
                "duration_h": plan.cycle.duration_h,
                "saving_per_cycle": _money(saving),
                "estimated_annual_saving": _money(annual),
                "reason": reason,
                **history,
            }
        )
        current_loads = _shifted_loads(
            current_loads,
            timestamps,
            plan.cycle.start_hour,
            hour,
            plan.cycle.duration_h,
            plan.cycle.energy_kwh,
        )
        current_cost = _day_cost(
            timestamps, current_loads, radiation, kwp, storage, tariff, dynamic
        )
        if device == "Pralka":
            washer_end = hour + plan.cycle.duration_h

    pool_advice_added = False

    if pool_plan is not None:
        choice = selected.get("pool_pump") if selected is not None else None
        hour, reason = (
            choice
            if choice is not None
            else (_best(pool_plan.candidates).hour, _fallback_reason(lang))
        )
        pool_loads = _shifted_loads(
            current_loads,
            timestamps,
            pool_plan.cycle.start_hour,
            hour,
            pool_plan.cycle.duration_h,
            pool_plan.cycle.energy_kwh,
        )
        saving = _day_cost(
            timestamps, current_loads, radiation, kwp, storage, tariff, dynamic
        ) - _day_cost(timestamps, pool_loads, radiation, kwp, storage, tariff, dynamic)
        if _visible_saving(saving):
            annual = saving * pool_plan.cycle.occurrences * Decimal(365) / Decimal(HISTORY_DAYS)
            for event in history_events:
                if event["event"] == POOL_PUMP:
                    event["advice"] = {
                        "from": f"{pool_plan.cycle.start_hour:02d}:00",
                        "to": f"{hour:02d}:00",
                        "duration_h": pool_plan.cycle.duration_h,
                        "saving_per_cycle": _money(saving),
                        "estimated_annual_saving": _money(annual),
                        "reason": reason,
                    }
                    break
            current_loads = pool_loads
            pool_advice_added = True
    if pool_cycle is not None and not pool_advice_added:
        for event in history_events:
            if event["event"] == POOL_PUMP:
                event["advice"] = {
                    "status": "keep",
                    "from": f"{pool_cycle.start_hour:02d}:00",
                    "to": f"{pool_cycle.start_hour:02d}:00",
                    "duration_h": pool_cycle.duration_h,
                    "reason": _keep_reason(lang),
                }
                break

    total = _day_cost(timestamps, loads, radiation, kwp, storage, tariff, dynamic) - _day_cost(
        timestamps, current_loads, radiation, kwp, storage, tariff, dynamic
    )

    payload = {
        "date": tomorrow.isoformat(),
        "scenario_id": scenario_id,
        "status": "ready",
        "source": source,
        "currency": CURRENCY,
        "recommendations": recommendations,
        "observed_events": history_events,
        "tariff_fallback_hours": tariff_fallback_hours,
        "total_daily_saving": _money(total),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "inputs": {
            "forecast_file": FORECAST_FILENAME,
            "weather_file": FORECAST_WEATHER_FILENAME,
            "events_file": FLEX_EVENTS_FILENAME,
            "forecast_hours": len(day_records),
            "history_events": len(events),
            "data_fingerprint": data_fingerprint,
            "tariff_mode": tariff.mode,
            "tariff_fallback_hours": tariff_fallback_hours,
            "kwp": str(kwp),
            "storage_capacity_kwh": str(storage.capacity_kwh),
            "storage_power_kw": str(storage.power_kw),
        },
    }
    if fallback_cause is not None:
        payload["fallback_cause"] = fallback_cause
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
