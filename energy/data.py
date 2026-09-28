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


def _data_dir() -> Path:
    """Zwraca katalog z danymi demo z ustawień projektu."""
    return settings.DEMO_DATA_DIR


def _missing() -> FileNotFoundError:
    """Tworzy wspólny błąd, gdy brak pliku z danymi demonstracyjnymi."""
    return FileNotFoundError("Demo data is temporarily unavailable.")


def _read_consumption(path: Path) -> list[ConsumptionHour]:
    """Czyta historię lub prognozę zużycia z CSV i waliduje dane godzinowe."""
    if not path.is_file():
        raise _missing()
    required = {"Data_Czas", *CATEGORIES, TOTAL_COLUMN}
    records: list[ConsumptionHour] = []
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise DemoDataError(f"File {path.name} is missing required columns.")
        for line_number, row in enumerate(reader, start=2):
            try:
                timestamp = datetime.strptime(row["Data_Czas"], "%Y-%m-%d %H:%M:%S")
                categories = tuple(Decimal(row[name]) for name in CATEGORIES)
                total = Decimal(row[TOTAL_COLUMN])
                values = (*categories, total)
                if any(not value.is_finite() or value < 0 for value in values):
                    raise ValueError("negative or infinite value")
                if sum(categories, Decimal(0)) != total:
                    raise ValueError("category sum differs from the total")
            except (TypeError, ValueError, InvalidOperation) as exc:
                raise DemoDataError(f"Error in {path.name}, row {line_number}: {exc}") from exc
            records.append(ConsumptionHour(timestamp, categories, row.get(EVENTS_COLUMN, "")))
    if not records:
        raise DemoDataError(f"File {path.name} contains no hourly records.")
    return records


def _read_weather(path: Path) -> list[WeatherHour]:
    """Wczytuje dane pogodowe z pliku CSV i sprawdza ich poprawność."""
    if not path.is_file():
        raise _missing()
    try:
        return read_weather_csv(path)
    except (WeatherFetchError, ValueError) as exc:
        raise DemoDataError(str(exc)) from exc


def _read_events(path: Path) -> list[FlexEvent]:
    """Czyta zdarzenia elastyczne z CSV i zwraca listę obiektów wydarzeń."""
    if not path.is_file():
        raise _missing()
    try:
        return read_events_csv(path)
    except ValueError as exc:
        raise DemoDataError(str(exc)) from exc


def load_history() -> list[ConsumptionHour]:
    """Ładuje historię zużycia energii z przygotowanego pliku demo."""
    return _read_consumption(_data_dir() / HISTORY_FILENAME)


def load_forecast() -> list[ConsumptionHour]:
    """Ładuje dane prognozy zużycia do symulacji lub widoku forecast."""
    return _read_consumption(_data_dir() / FORECAST_FILENAME)


def load_weather_history() -> list[WeatherHour]:
    """Pobiera historyczne dane pogodowe dla analizy zużycia i temperatury."""
    return _read_weather(_data_dir() / HISTORY_WEATHER_FILENAME)


def load_weather_forecast() -> list[WeatherHour]:
    """Pobiera prognozę pogody dla wyświetlania temperatury w przyszłości."""
    return _read_weather(_data_dir() / FORECAST_WEATHER_FILENAME)


def load_history_events() -> list[FlexEvent]:
    """Ładuje historię zdarzeń elastycznych, np. przesunięć obciążenia."""
    return _read_events(_data_dir() / FLEX_EVENTS_FILENAME)


def load_annual() -> tuple[list[ConsumptionHour], list[WeatherHour], list[FlexEvent]]:
    """Wczytuje roczne dane zużycia, pogody i zdarzeń w jednym pakiecie."""
    return (
        _read_consumption(_data_dir() / ANNUAL_CONSUMPTION_FILENAME),
        _read_weather(_data_dir() / YEAR_WEATHER_FILENAME),
        _read_events(_data_dir() / ANNUAL_EVENTS_FILENAME),
    )


def load_backtest() -> list[BacktestRow]:
    """Wczytuje wyniki backtestu z CSV i zwraca rekordy do porównania modeli."""
    path = _data_dir() / "backtest.csv"
    if not path.is_file():
        raise _missing()
    rows: list[BacktestRow] = []
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None or not set(BACKTEST_COLUMNS).issubset(reader.fieldnames):
            raise DemoDataError(f"File {path.name} is missing required columns.")
        for row in reader:
            try:
                rows.append(
                    BacktestRow(
                        datetime.strptime(row["Data_Czas"], "%Y-%m-%d %H:%M:%S"),
                        Decimal(row["Rzeczywiste_kWh"]),
                        Decimal(row["Model_kWh"]),
                        Decimal(row["Baseline_kWh"]),
                    )
                )
            except (TypeError, ValueError, InvalidOperation) as exc:
                raise DemoDataError(f"Error in {path.name}: {exc}") from exc
    if not rows:
        raise DemoDataError(f"File {path.name} contains no backtest data.")
    return rows


def load_metrics() -> dict:
    """Czyta plik JSON z metrykami systemu i zwraca słownik wyników."""
    path = _data_dir() / METRICS_FILENAME
    if not path.is_file():
        raise _missing()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DemoDataError(f"File {path.name} is not valid JSON: {exc}") from exc


def default_dates(history: list[ConsumptionHour]) -> tuple[date, date]:
    """Oblicza domyślny zakres dat na 7 ostatnich dni na podstawie historii."""
    end = history[-1].timestamp.date()
    return end - timedelta(days=6), end


def filter_records(records: list, start: date, end: date) -> list:
    """Filtruje rekordy do wybranego przedziału dat włącznie z początkiem i końcem."""
    return [record for record in records if start <= record.timestamp.date() <= end]
