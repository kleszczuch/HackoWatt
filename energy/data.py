"""Odczyt przygotowanych plików CSV/JSON; bez pobierania i treningu w HTTP."""

import csv
import json
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings

from energy.forecasting import BACKTEST_COLUMNS, FORECAST_FILENAME, METRICS_FILENAME, BacktestRow
from energy.household import (
    ANNUAL_CONSUMPTION_FILENAME,
    ANNUAL_EVENTS_FILENAME,
    CATEGORIES,
    EVENTS_COLUMN,
    FLEX_EVENTS_FILENAME,
    HISTORY_FILENAME,
    TOTAL_COLUMN,
    ConsumptionHour,
    FlexEvent,
    read_events_csv,
)
from energy.weather import (
    FORECAST_WEATHER_FILENAME,
    HISTORY_WEATHER_FILENAME,
    YEAR_WEATHER_FILENAME,
    WeatherFetchError,
    WeatherHour,
    read_weather_csv,
)


class DemoDataError(ValueError):
    """Plik demonstracyjny ma nieoczekiwany lub niepoprawny format."""


def _data_dir(request=None) -> Path:
    base = settings.DEMO_DATA_DIR
    if (base / HISTORY_FILENAME).is_file():
        return base

    try:
        from energy.scenarios import capture_scenario_data_dir, get_current_request

        req = request if request is not None else get_current_request()
        candidate = capture_scenario_data_dir(req)
        if (candidate / HISTORY_FILENAME).is_file():
            return candidate
    except Exception:
        pass

    default_scenario = base / "scenario_4"
    if (default_scenario / HISTORY_FILENAME).is_file():
        return default_scenario
    for sc in ("scenario_1", "scenario_2", "scenario_3", "scenario_5"):
        candidate = base / sc
        if (candidate / HISTORY_FILENAME).is_file():
            return candidate
    return base


def _missing() -> FileNotFoundError:
    return FileNotFoundError("Demo data is temporarily unavailable.")


_CONSUMPTION_CACHE: dict[tuple[str, int], list[ConsumptionHour]] = {}
_WEATHER_CACHE: dict[tuple[str, int], list[WeatherHour]] = {}
_EVENTS_CACHE: dict[tuple[str, int], list[FlexEvent]] = {}
_BACKTEST_CACHE: dict[tuple[str, int], list[BacktestRow]] = {}
_METRICS_CACHE: dict[tuple[str, int], dict] = {}


def _read_consumption(path: Path) -> list[ConsumptionHour]:
    if not path.is_file():
        raise _missing()
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        mtime = 0
    cache_key = (str(path.resolve()), mtime)
    if cache_key in _CONSUMPTION_CACHE:
        return list(_CONSUMPTION_CACHE[cache_key])

    required = {"Data_Czas", *CATEGORIES, TOTAL_COLUMN}
    records: list[ConsumptionHour] = []
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source)
        try:
            headers = next(reader)
        except StopIteration as exc:
            raise DemoDataError(f"File {path.name} contains no hourly records.") from exc
        h_map = {name: i for i, name in enumerate(headers)}
        if not required.issubset(h_map):
            raise DemoDataError(f"File {path.name} is missing required columns.")

        ts_idx = h_map["Data_Czas"]
        cat_idxs = tuple(h_map[c] for c in CATEGORIES)
        tot_idx = h_map[TOTAL_COLUMN]
        ev_idx = h_map.get(EVENTS_COLUMN)

        for line_number, row in enumerate(reader, start=2):
            if not row:
                continue
            try:
                timestamp = datetime.fromisoformat(row[ts_idx])
                categories = tuple(Decimal(row[i]) for i in cat_idxs)
                total = Decimal(row[tot_idx])
                values = (*categories, total)
                if any(not value.is_finite() or value < 0 for value in values):
                    raise ValueError("negative or infinite value")
                if sum(categories, Decimal(0)) != total:
                    raise ValueError("category sum differs from the total")
            except (TypeError, ValueError, InvalidOperation, IndexError) as exc:
                raise DemoDataError(f"Error in {path.name}, row {line_number}: {exc}") from exc
            ev = row[ev_idx] if ev_idx is not None and ev_idx < len(row) else ""
            records.append(ConsumptionHour(timestamp, categories, ev, total=total))

    if not records:
        raise DemoDataError(f"File {path.name} contains no hourly records.")
    _CONSUMPTION_CACHE[cache_key] = records
    return list(records)


def _read_weather(path: Path) -> list[WeatherHour]:
    if not path.is_file():
        raise _missing()
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        mtime = 0
    cache_key = (str(path.resolve()), mtime)
    if cache_key in _WEATHER_CACHE:
        return list(_WEATHER_CACHE[cache_key])
    try:
        records = read_weather_csv(path)
        _WEATHER_CACHE[cache_key] = records
        return list(records)
    except (WeatherFetchError, ValueError) as exc:
        raise DemoDataError(str(exc)) from exc


def _read_events(path: Path) -> list[FlexEvent]:
    if not path.is_file():
        raise _missing()
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        mtime = 0
    cache_key = (str(path.resolve()), mtime)
    if cache_key in _EVENTS_CACHE:
        return list(_EVENTS_CACHE[cache_key])
    try:
        events = read_events_csv(path)
        _EVENTS_CACHE[cache_key] = events
        return list(events)
    except ValueError as exc:
        raise DemoDataError(str(exc)) from exc


def load_history(data_dir: Path | None = None) -> list[ConsumptionHour]:
    target = data_dir if data_dir is not None else _data_dir()
    return _read_consumption(target / HISTORY_FILENAME)


def load_forecast(data_dir: Path | None = None) -> list[ConsumptionHour]:
    target = data_dir or _data_dir()
    return _read_consumption(target / FORECAST_FILENAME)


def load_weather_history(data_dir: Path | None = None) -> list[WeatherHour]:
    target = data_dir or _data_dir()
    return _read_weather(target / HISTORY_WEATHER_FILENAME)


def load_weather_forecast(data_dir: Path | None = None) -> list[WeatherHour]:
    target = data_dir or _data_dir()
    return _read_weather(target / FORECAST_WEATHER_FILENAME)


def load_history_events(data_dir: Path | None = None) -> list[FlexEvent]:
    target = data_dir or _data_dir()
    return _read_events(target / FLEX_EVENTS_FILENAME)


def load_annual(
    data_dir: Path | None = None,
) -> tuple[list[ConsumptionHour], list[WeatherHour], list[FlexEvent]]:
    target = data_dir or _data_dir()
    return (
        _read_consumption(target / ANNUAL_CONSUMPTION_FILENAME),
        _read_weather(target / YEAR_WEATHER_FILENAME),
        _read_events(target / ANNUAL_EVENTS_FILENAME),
    )


def load_backtest(data_dir: Path | None = None) -> list[BacktestRow]:
    target = data_dir or _data_dir()
    path = target / "backtest.csv"
    if not path.is_file():
        raise _missing()
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        mtime = 0
    cache_key = (str(path.resolve()), mtime)
    if cache_key in _BACKTEST_CACHE:
        return list(_BACKTEST_CACHE[cache_key])

    rows: list[BacktestRow] = []
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source)
        try:
            headers = next(reader)
        except StopIteration as exc:
            raise DemoDataError(f"File {path.name} contains no backtest data.") from exc
        h_map = {name: i for i, name in enumerate(headers)}
        if not set(BACKTEST_COLUMNS).issubset(h_map):
            raise DemoDataError(f"File {path.name} is missing required columns.")
        ts_idx = h_map["Data_Czas"]
        act_idx = h_map["Rzeczywiste_kWh"]
        mod_idx = h_map["Model_kWh"]
        base_idx = h_map["Baseline_kWh"]
        for row in reader:
            if not row:
                continue
            try:
                rows.append(
                    BacktestRow(
                        datetime.fromisoformat(row[ts_idx]),
                        Decimal(row[act_idx]),
                        Decimal(row[mod_idx]),
                        Decimal(row[base_idx]),
                    )
                )
            except (TypeError, ValueError, InvalidOperation, IndexError) as exc:
                raise DemoDataError(f"Error in {path.name}: {exc}") from exc
    if not rows:
        raise DemoDataError(f"File {path.name} contains no backtest data.")
    _BACKTEST_CACHE[cache_key] = rows
    return list(rows)


def load_metrics(data_dir: Path | None = None) -> dict:
    target = data_dir or _data_dir()
    path = target / METRICS_FILENAME
    if not path.is_file():
        raise _missing()
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        mtime = 0
    cache_key = (str(path.resolve()), mtime)
    if cache_key in _METRICS_CACHE:
        return dict(_METRICS_CACHE[cache_key])
    try:
        data_json = json.loads(path.read_text(encoding="utf-8"))
        _METRICS_CACHE[cache_key] = data_json
        return dict(data_json)
    except json.JSONDecodeError as exc:
        raise DemoDataError(f"File {path.name} is not valid JSON: {exc}") from exc


TARIFF_PRICES_FILENAME = "tariff_prices.json"


def load_tariff_prices(data_dir: Path | None = None) -> dict[datetime, Decimal]:
    """Wczytuje godzinowe ceny RCE; brak lub błąd pliku daje pusty słownik."""
    target = Path(data_dir) if data_dir else settings.DEMO_DATA_DIR
    path = target / TARIFF_PRICES_FILENAME
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {
            datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S"): Decimal(str(price))
            for stamp, price in payload["prices"].items()
        }
    except KeyError, TypeError, ValueError, InvalidOperation, json.JSONDecodeError:
        return {}


def default_dates(history: list[ConsumptionHour]) -> tuple[date, date]:
    end = history[-1].timestamp.date()
    return end - timedelta(days=6), end


def filter_records(records: list, start: date, end: date) -> list:
    return [record for record in records if start <= record.timestamp.date() <= end]
