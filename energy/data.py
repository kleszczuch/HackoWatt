"""Odczyt gotowych CSV bez trenowania modeli podczas żądania HTTP."""

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings

from chart_generator import FORECAST_FILENAME
from generuj_zuzycie import CATEGORIES, HISTORY_FILENAME

TOTAL_COLUMN = "Calkowite_Zuzycie_kWh"
REQUIRED_COLUMNS = {"Data_Czas", *CATEGORIES, TOTAL_COLUMN}


class DemoDataError(ValueError):
    """Plik demonstracyjny ma nieoczekiwany lub niepoprawny format."""


@dataclass(frozen=True)
class EnergyRecord:
    timestamp: datetime
    kind: str
    categories: tuple[str, ...]
    total: str

    @property
    def date(self) -> date:
        return self.timestamp.date()

    @property
    def category_cells(self) -> tuple[str, ...]:
        return self.categories

    @property
    def total_decimal(self) -> Decimal:
        return Decimal(self.total)


def _read_file(path: Path, kind: str) -> list[EnergyRecord]:
    records = []
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None or not REQUIRED_COLUMNS.issubset(reader.fieldnames):
            raise DemoDataError(f"Plik {path.name} nie ma wymaganych kolumn.")

        for line_number, row in enumerate(reader, start=2):
            try:
                timestamp = datetime.strptime(row["Data_Czas"], "%Y-%m-%d %H:%M:%S")
                categories = tuple(row[name] for name in CATEGORIES)
                total = row[TOTAL_COLUMN]
                values = [Decimal(value) for value in (*categories, total)]
                if any(not value.is_finite() or value < 0 for value in values):
                    raise ValueError("wartość ujemna lub nieskończona")
                if sum(values[:-1]) != values[-1]:
                    raise ValueError("suma kategorii różni się od sumy całkowitej")
            except (TypeError, ValueError, InvalidOperation) as exc:
                raise DemoDataError(f"Błąd w {path.name}, wiersz {line_number}: {exc}") from exc
            records.append(EnergyRecord(timestamp, kind, categories, total))
    return records


def load_demo_data() -> tuple[list[EnergyRecord], list[EnergyRecord]]:
    folder = settings.DEMO_DATA_DIR
    history_path = folder / HISTORY_FILENAME
    forecast_path = folder / FORECAST_FILENAME
    if not history_path.is_file() or not forecast_path.is_file():
        raise FileNotFoundError("Uruchom: uv run python manage.py prepare_demo_data")

    history = _read_file(history_path, "Symulacja")
    forecast = _read_file(forecast_path, "Prognoza")
    if not history or not forecast:
        raise DemoDataError("Pliki danych nie mogą być puste.")
    if history[-1].timestamp >= forecast[0].timestamp:
        raise DemoDataError("Historia i prognoza nachodzą na siebie.")
    return history, forecast


def default_dates(history: list[EnergyRecord], forecast: list[EnergyRecord]) -> tuple[date, date]:
    return history[-1].date - timedelta(days=6), min(
        forecast[-1].date, forecast[0].date + timedelta(days=6)
    )


def filter_records(records: list[EnergyRecord], start: date, end: date) -> list[EnergyRecord]:
    return [record for record in records if start <= record.date <= end]
