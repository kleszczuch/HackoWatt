"""Taryfa godzinowa, stałe i konfiguracja taryfy użytkownika."""

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

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

# Kurs stały do przeliczenia cen PSE (PLN/MWh) na €/kWh — uproszczenie demo.
EURPLN_RATE = Decimal("4.30")

MODE_FIXED = "fixed"
MODE_DYNAMIC = "dynamic"
TARIFF_COOKIE = "tariff"
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
BLOCK_HOURS = 4


@dataclass(frozen=True)
class PriceBlock:
    """Ciągłe cztery godziny i ich średnia końcowa cena w EUR/kWh."""

    start_hour: int
    average: Decimal

    @property
    def end_hour(self) -> int:
        return self.start_hour + BLOCK_HOURS

    @property
    def interval_label(self) -> str:
        return f"{self.start_hour:02d}:00–{self.end_hour:02d}:00"


def four_hour_price_blocks(prices: list[Decimal]) -> tuple[PriceBlock, PriceBlock]:
    """Wybiera najtańsze i najdroższe okno 4 h; przy remisie pierwsze i ostatnie."""
    if len(prices) != 24:
        raise ValueError("Dobowy podgląd musi zawierać 24 stawki godzinowe.")
    totals = [
        sum(prices[start : start + BLOCK_HOURS], Decimal(0))
        for start in range(24 - BLOCK_HOURS + 1)
    ]
    cheapest_start = min(range(len(totals)), key=lambda start: (totals[start], start))
    highest_start = max(range(len(totals)), key=lambda start: (totals[start], start))
    return (
        PriceBlock(cheapest_start, totals[cheapest_start] / BLOCK_HOURS),
        PriceBlock(highest_start, totals[highest_start] / BLOCK_HOURS),
    )


@dataclass(frozen=True)
class Provider:
    """Dostawca energii z marżą brutto (zł/kWh) doliczaną do dynamicznej ceny RCE."""

    id: str
    name_pl: str
    name_en: str
    margin_pln: Decimal

    @property
    def margin(self) -> Decimal:
        """Marża w €/kWh po przeliczeniu stałym kursem EURPLN."""
        return (self.margin_pln / EURPLN_RATE).quantize(Decimal("0.00001"))


# Lista docelowych dostawców jest uzupełniana sukcesywnie.
PROVIDERS = (
    Provider(
        "standard",
        "Bez marży · same ceny giełdowe",
        "No margin · market prices only",
        Decimal("0.00"),
    ),
    Provider("tauron", "Tauron", "Tauron", Decimal("0.1097")),
)
DEFAULT_PROVIDER = PROVIDERS[0]


def price_for_hour(hour: int) -> Decimal:
    """Zwraca cenę energii dla konkretnej godziny w oparciu o taryfę godzinową."""
    if not 0 <= hour <= 23:
        raise ValueError(f"Godzina poza zakresu 0–23: {hour}")
    for start, end, price in TARIFF_PERIODS:
        if start <= hour < end:
            return price
    raise AssertionError("Taryfa nie pokrywa pełnej doby.")


def energy_cost(timestamps: list[datetime], amounts_kwh: list[Decimal]) -> Decimal:
    """Oblicza koszt energii na podstawie godzinowej taryfy i zużycia w kWh."""
    if len(timestamps) != len(amounts_kwh):
        raise ValueError("Liczba znaczników czasu i wartości kWh musi być równa.")
    pairs = zip(timestamps, amounts_kwh, strict=True)
    return sum((price_for_hour(ts.hour) * amount for ts, amount in pairs), Decimal(0))


@dataclass(frozen=True)
class TariffConfig:
    """Wybrana przez użytkownika taryfa: stała z edytowalnymi kwotami albo dynamiczna."""

    mode: str = MODE_FIXED
    fixed_prices: tuple[Decimal, ...] | None = None
    provider_id: str = DEFAULT_PROVIDER.id

    @property
    def provider(self) -> Provider:
        return next((p for p in PROVIDERS if p.id == self.provider_id), DEFAULT_PROVIDER)

    def price_for_hour(self, hour: int) -> Decimal:
        """Stawka stała dla godziny: kwota użytkownika albo domyślna."""
        if not 0 <= hour <= 23:
            raise ValueError(f"Godzina poza zakresu 0–23: {hour}")
        for index, (start, end, price) in enumerate(TARIFF_PERIODS):
            if start <= hour < end:
                if self.fixed_prices is not None and index < len(self.fixed_prices):
                    return self.fixed_prices[index]
                return price
        raise AssertionError("Taryfa nie pokrywa pełnej doby.")

    def price_at(self, moment: datetime, dynamic: dict[datetime, Decimal] | None) -> tuple:
        """Zwraca (cena €/kWh, fallback) dla chwili; dynamiczna obejmuje marżę dostawcy."""
        if self.mode == MODE_DYNAMIC and dynamic is not None:
            price = dynamic.get(moment)
            if price is not None:
                return price + self.provider.margin, False
        return self.price_for_hour(moment.hour), True


def load_dynamic_payload(path: Path | str) -> dict | None:
    """Wczytuje cały plik cen dynamicznych (metadane i ceny) albo zwraca None."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def load_dynamic_prices(path: Path | str) -> dict[datetime, Decimal] | None:
    """Wczytuje ceny dynamiczne z JSON zapisanego przez fetch_tariff_prices."""
    payload = load_dynamic_payload(path)
    if payload is None:
        return None
    try:
        prices = payload["prices"]
        return {
            datetime.strptime(label, TIMESTAMP_FORMAT): Decimal(str(value))
            for label, value in prices.items()
        }
    except KeyError, TypeError, ValueError, InvalidOperation:
        return None


def dynamic_coverage(timestamps: list[datetime], dynamic: dict[datetime, Decimal]) -> Decimal:
    """Zwraca ułamek godzin (0–1) mających cenę dynamiczną."""
    if not timestamps:
        return Decimal(0)
    covered = sum(1 for ts in timestamps if ts in dynamic)
    return Decimal(covered) / Decimal(len(timestamps))


def configured_energy_cost(
    config: TariffConfig,
    timestamps: list[datetime],
    amounts_kwh: list[Decimal],
    dynamic: dict[datetime, Decimal] | None = None,
) -> Decimal:
    """Koszt energii według wybranej taryfy; braki dynamiczne liczy po stawce stałej."""
    if len(timestamps) != len(amounts_kwh):
        raise ValueError("Liczba znaczników czasu i wartości kWh musi być równa.")
    pairs = zip(timestamps, amounts_kwh, strict=True)
    return sum((config.price_at(ts, dynamic)[0] * amount for ts, amount in pairs), Decimal(0))


def tariff_for_request(
    request, data_dir: Path | str
) -> tuple[TariffConfig, dict[datetime, Decimal] | None]:
    """Buduje konfigurację taryfy z sesji/ciastka i wczytuje ceny dynamiczne z dysku."""
    raw = request.session.get(TARIFF_COOKIE)
    if raw is None:
        cookie = request.COOKIES.get(TARIFF_COOKIE)
        if cookie:
            try:
                raw = json.loads(cookie)
            except json.JSONDecodeError:
                raw = None
    if not isinstance(raw, dict):
        raw = {}

    mode = raw.get("mode") if raw.get("mode") in (MODE_FIXED, MODE_DYNAMIC) else MODE_FIXED
    provider_id = raw.get("provider")
    if provider_id not in {p.id for p in PROVIDERS}:
        provider_id = DEFAULT_PROVIDER.id

    fixed_prices = None
    raw_prices = raw.get("fixed")
    if isinstance(raw_prices, list | tuple):
        try:
            parsed = tuple(Decimal(str(value)) for value in raw_prices)
        except InvalidOperation, ValueError:
            parsed = ()
        if len(parsed) == len(TARIFF_PERIODS) and all(Decimal(0) <= p <= 10 for p in parsed):
            fixed_prices = parsed

    config = TariffConfig(mode=mode, fixed_prices=fixed_prices, provider_id=provider_id)
    dynamic = load_dynamic_prices(Path(data_dir) / "tariff_prices.json")
    return config, dynamic


def serialize_tariff(config: TariffConfig) -> dict:
    """Zwraca słownik ustawień do zapisu w sesji/ciastku."""
    return {
        "mode": config.mode,
        "provider": config.provider_id,
        "fixed": [str(price) for price in config.fixed_prices]
        if config.fixed_prices is not None
        else None,
    }
