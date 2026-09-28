"""Testy przepływu od generatorów do tabeli i pobrania CSV."""

import csv
import io
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from chart_generator import FORECAST_FILENAME, generate_forecast
from energy.data import load_demo_data
from generuj_zuzycie import CATEGORIES, HISTORY_FILENAME, generate_consumption


def write_data(path: Path, start: datetime, hours: int, base: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(["Data_Czas", *CATEGORIES, "Calkowite_Zuzycie_kWh"])
        for offset in range(hours):
            timestamp = start + timedelta(hours=offset)
            writer.writerow([timestamp.strftime("%Y-%m-%d %H:%M:%S"), base, 0, 0, 0, 0, 0, base])


def make_test_dir() -> Path:
    path = settings.BASE_DIR / "data" / f"test-{uuid4().hex}"
    path.mkdir(parents=True)
    return path


def clean_test_dir(path: Path) -> None:
    for child in path.iterdir():
        child.unlink()
    path.rmdir()


class DashboardTests(SimpleTestCase):
    def setUp(self):
        self.data_dir = make_test_dir()
        self.addCleanup(clean_test_dir, self.data_dir)
        settings_context = override_settings(DEMO_DATA_DIR=self.data_dir)
        settings_context.enable()
        self.addCleanup(settings_context.disable)
        write_data(
            self.data_dir / HISTORY_FILENAME,
            datetime(2026, 12, 29, 12),
            60,
            "1.000",
        )
        write_data(self.data_dir / FORECAST_FILENAME, datetime(2027, 1, 1), 24, "2.000000")

    def test_dashboard_has_both_charts_and_exact_paginated_rows(self):
        response = self.client.get(
            reverse("dashboard"), {"start": "2026-12-29", "end": "2027-01-01"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_count"], 84)
        self.assertEqual(len(response.context["page"].object_list), 48)
        self.assertEqual(response.context["selected_total"], Decimal("108.000000"))
        self.assertContains(response, "Szczegółowe wykresy")
        self.assertContains(response, "Zużycie dzień po dniu")
        self.assertContains(response, "29.12.2026 12:00")

        next_page = self.client.get(
            reverse("dashboard"), {"start": "2026-12-29", "end": "2027-01-01", "page": 2}
        )
        self.assertEqual(len(next_page.context["page"].object_list), 36)
        self.assertContains(next_page, "01.01.2027 00:00")
        self.assertContains(next_page, "2.000000")

    def test_export_has_every_filtered_hour_with_original_precision(self):
        response = self.client.get(
            reverse("export_csv"), {"start": "2026-12-31", "end": "2027-01-01"}
        )
        self.assertEqual(response.status_code, 200)
        reader = csv.DictReader(io.StringIO(response.content.decode("utf-8-sig")))
        rows = list(reader)
        self.assertEqual(len(rows), 48)
        self.assertEqual(rows[0]["Data_Czas"], "2026-12-31 00:00:00")
        self.assertEqual(rows[0]["Calkowite_Zuzycie_kWh"], "1.000")
        self.assertEqual(rows[-1]["Typ_danych"], "Prognoza")
        self.assertEqual(rows[-1]["Calkowite_Zuzycie_kWh"], "2.000000")

    def test_invalid_range_is_explained_and_export_rejected(self):
        query = {"start": "2027-01-02", "end": "2026-12-31"}
        response = self.client.get(reverse("dashboard"), query)
        self.assertContains(response, "Data końcowa nie może być wcześniejsza")
        self.assertEqual(self.client.get(reverse("export_csv"), query).status_code, 400)

    def test_valid_range_without_data_is_not_reported_as_zero_usage(self):
        response = self.client.get(
            reverse("dashboard"), {"start": "2028-01-01", "end": "2028-01-02"}
        )
        self.assertEqual(response.context["selected_count"], 0)
        self.assertContains(response, "Brak danych w wybranym okresie")

    def test_missing_data_shows_preparation_command(self):
        (self.data_dir / HISTORY_FILENAME).unlink()
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "prepare_demo_data")


class GeneratorTests(SimpleTestCase):
    def test_consumption_generator_has_full_year_and_reproducible_values(self):
        directory = make_test_dir()
        try:
            first = generate_consumption(directory / "first.csv")
            second = generate_consumption(directory / "second.csv")
            self.assertEqual(len(first), 8760)
            self.assertEqual(first["Data_Czas"].iloc[0], "2026-01-01 00:00:00")
            self.assertEqual(first["Data_Czas"].iloc[-1], "2026-12-31 23:00:00")
            self.assertTrue(first.equals(second))
        finally:
            clean_test_dir(directory)

    def test_forecast_has_all_hours_and_nonnegative_categories(self):
        directory = make_test_dir()
        try:
            history_path = directory / HISTORY_FILENAME
            forecast_path = directory / FORECAST_FILENAME
            write_data(history_path, datetime(2026, 12, 25), 168, "1.000")
            result = generate_forecast(history_path, forecast_path, days=1)
            self.assertEqual(len(result), 24)
            self.assertEqual(result["Data_Czas"].iloc[0], "2027-01-01 00:00:00")
            self.assertTrue((result[list(CATEGORIES)] >= 0).all().all())
            with override_settings(DEMO_DATA_DIR=directory):
                history, forecast = load_demo_data()
            self.assertEqual(len(history), 168)
            self.assertEqual(len(forecast), 24)
        finally:
            clean_test_dir(directory)
