"""Testy scenariusza 4: pogoda, generator, taryfa, prognoza, PV i widoki."""

import csv
import io
import json
import shutil
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from energy import forecasting, household, pv, tariffs, weather
from energy.charts import build_history_chart, build_overview_chart
from energy.data import (
    load_annual,
    load_forecast,
    load_history,
    load_tariff_prices,
    load_weather_forecast,
    load_weather_history,
)
from energy.presentation import device_name, event_names
from energy.views import PLOTLY_CONFIG, _chart_html

HISTORY_START = datetime(2026, 9, 15, 0)
FORECAST_START = datetime(2026, 10, 20, 11)
ANNUAL_START = datetime(2027, 6, 7, 0)  # poniedziałek


def make_test_dir() -> Path:
    """Tworzy osobny katalog testowy w katalogu danych demo."""
    path = settings.BASE_DIR / "data" / f"test-{uuid4().hex}"
    path.mkdir(parents=True)
    return path


def clean_test_dir(path: Path) -> None:
    """Usuwa katalog testowy po zakończeniu testu."""
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def write_weather(path: Path, start: datetime, hours: int, temp: float = 5.0) -> None:
    """Zapisuje prosty plik z danymi pogodowymi dla testu."""
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(weather.WEATHER_COLUMNS)
        for offset in range(hours):
            stamp = start + timedelta(hours=offset)
            writer.writerow([stamp.strftime("%Y-%m-%d %H:%M:%S"), f"{temp:.1f}", "50", "0.0"])


def write_consumption(path: Path, start: datetime, hours: int, base: str = "1.000") -> None:
    """Zapisuje uproszczony plik zużycia energii dla scenariusza testowego."""
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(household.CONSUMPTION_COLUMNS)
        for offset in range(hours):
            stamp = start + timedelta(hours=offset)
            row = [stamp.strftime("%Y-%m-%d %H:%M:%S"), "Monday", stamp.hour]
            writer.writerow([*row, base, 0, 0, 0, 0, 0, base, ""])


def write_events(path: Path) -> None:
    """Zapisuje prosty zestaw zdarzeń elastycznych do testowego CSV."""
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(household.EVENT_COLUMNS)
        writer.writerow(["2027-06-07", "Zmywarka", 19, 2, "1.000"])
        writer.writerow(["2027-06-08", "Pralka", 10, 1, "0.800"])


def write_backtest(path: Path) -> None:
    """Tworzy minimalny plik backtestu do sprawdzenia obliczeń modeli."""
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(forecasting.BACKTEST_COLUMNS)
        for offset in range(24):
            stamp = HISTORY_START + timedelta(hours=offset)
            writer.writerow([stamp.strftime("%Y-%m-%d %H:%M:%S"), "1.000", "1.100", "0.900"])


def write_metrics(path: Path) -> None:
    """Zapisuje metryki modelu do prostego pliku JSON testowego."""
    path.write_text(
        json.dumps(
            {
                "okres_od": "2026-09-15 00:00:00",
                "okres_do": "2026-09-15 23:00:00",
                "godzin": 24,
                "mae_model": 0.1234,
                "mape_model": 5.67,
                "mae_baseline": 0.2345,
                "mape_baseline": 8.9,
                "wygenerowano": "2026-09-28 11:00:00",
            }
        ),
        encoding="utf-8",
    )


def prepare_fixture_dir(data_dir: Path) -> None:
    """Przygotowuje komplet plików demo potrzebnych do testów widoków i API."""
    write_weather(data_dir / weather.HISTORY_WEATHER_FILENAME, HISTORY_START, 10 * 24)
    write_weather(data_dir / weather.FORECAST_WEATHER_FILENAME, FORECAST_START, 7 * 24)
    write_weather(data_dir / weather.YEAR_WEATHER_FILENAME, ANNUAL_START, 14 * 24)
    write_consumption(data_dir / household.HISTORY_FILENAME, HISTORY_START, 10 * 24)
    write_consumption(data_dir / forecasting.FORECAST_FILENAME, FORECAST_START, 7 * 24)
    write_consumption(data_dir / household.ANNUAL_CONSUMPTION_FILENAME, ANNUAL_START, 14 * 24)
    write_events(data_dir / household.FLEX_EVENTS_FILENAME)
    write_events(data_dir / household.ANNUAL_EVENTS_FILENAME)
    write_backtest(data_dir / forecasting.BACKTEST_FILENAME)
    write_metrics(data_dir / forecasting.METRICS_FILENAME)


class WeatherTests(SimpleTestCase):
    """Testy parsera danych pogodowych i podziału historii na fragmenty."""

    def test_parse_hourly_reads_open_meteo_payload(self):
        payload = {
            "hourly": {
                "time": ["2026-09-28T00:00", "2026-09-28T01:00"],
                "temperature_2m": [5.5, 5.1],
                "cloud_cover": [80, 75],
                "shortwave_radiation": [0.0, 0.0],
            }
        }
        records = weather.parse_hourly(payload)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].timestamp, datetime(2026, 9, 28, 0))
        self.assertEqual(records[0].temperature, 5.5)

    def test_fetch_weather_uses_selected_location(self):
        payload = {
            "hourly": {
                "time": ["2026-09-28T00:00"],
                "temperature_2m": [20.0],
                "cloud_cover": [10],
                "shortwave_radiation": [0.0],
            }
        }
        with patch("energy.weather._get_json", return_value=payload) as get_json:
            weather.fetch_weather_series(
                latitude=38.7223, longitude=-9.1393, timezone="Europe/Lisbon"
            )
        params = get_json.call_args.args[1]
        self.assertEqual(params["latitude"], 38.7223)
        self.assertEqual(params["longitude"], -9.1393)
        self.assertEqual(params["timezone"], "Europe/Lisbon")

    def test_parse_hourly_rejects_missing_fields(self):
        with self.assertRaises(weather.WeatherFetchError):
            weather.parse_hourly({"hourly": {"time": []}})

    def test_split_history_forecast_around_now(self):
        start = datetime(2026, 9, 1, 0)
        series = [
            weather.WeatherHour(start + timedelta(hours=offset), 10.0, 50.0, 0.0)
            for offset in range(40 * 24)
        ]
        now = start + timedelta(days=36)
        history, forecast = weather.split_history_forecast(
            series, now, history_days=35, forecast_days=4
        )
        self.assertEqual(len(history), 35 * 24)
        self.assertEqual(len(forecast), 4 * 24)
        self.assertEqual(history[-1].timestamp, now - timedelta(hours=1))
        self.assertEqual(forecast[0].timestamp, now)

    def test_weather_csv_round_trip(self):
        directory = make_test_dir()
        try:
            path = directory / "pogoda.csv"
            write_weather(path, HISTORY_START, 24, temp=7.5)
            records = weather.read_weather_csv(path)
            self.assertEqual(len(records), 24)
            self.assertEqual(records[0].temperature, 7.5)
        finally:
            clean_test_dir(directory)


class HouseholdTests(SimpleTestCase):
    """Testy generatora zużycia energii i zachowania scenariusza domowego."""

    def _weather(self, days: int, temp: float) -> list[weather.WeatherHour]:
        return [
            weather.WeatherHour(HISTORY_START + timedelta(hours=offset), temp, 50.0, 0.0)
            for offset in range(days * 24)
        ]

    def test_simulation_is_deterministic(self):
        first, first_events = household.simulate_household(self._weather(14, 5.0))
        second, second_events = household.simulate_household(self._weather(14, 5.0))
        self.assertEqual([r.total for r in first], [r.total for r in second])
        self.assertEqual(first_events, second_events)

    def test_cold_days_raise_heating(self):
        cold, _ = household.simulate_household(self._weather(7, -5.0))
        warm, _ = household.simulate_household(self._weather(7, 22.0))
        heating_index = household.CATEGORIES.index("Ogrzewanie_kWh")
        cold_heating = sum(r.categories[heating_index] for r in cold)
        warm_heating = sum(r.categories[heating_index] for r in warm)
        self.assertGreater(cold_heating, warm_heating * 10)

    def test_events_are_labeled_and_flex_events_exported(self):
        records, events = household.simulate_household(self._weather(35, 8.0))
        self.assertTrue(any(record.events for record in records))
        self.assertTrue(any("wyjazd rodziny" in record.events for record in records))
        self.assertTrue(any(event.device == "Zmywarka" for event in events))
        for record in records:
            self.assertEqual(record.total, sum(record.categories, Decimal(0)))

    def test_weekend_differs_from_weekday(self):
        records, _ = household.simulate_household(self._weather(35, 8.0))
        daily = {}
        for record in records:
            daily.setdefault(record.timestamp.date(), Decimal(0))
            daily[record.timestamp.date()] += record.total
        weekday_avg = sum(v for d, v in daily.items() if d.weekday() < 5) / max(
            1, sum(1 for d in daily if d.weekday() < 5)
        )
        weekend_avg = sum(v for d, v in daily.items() if d.weekday() >= 5) / max(
            1, sum(1 for d in daily if d.weekday() >= 5)
        )
        self.assertNotEqual(weekday_avg, weekend_avg)


class TariffTests(SimpleTestCase):
    """Testy taryfy godzinowej i obliczeń kosztów energii."""

    def test_period_boundaries(self):
        expected = {
            0: "0.18",
            5: "0.18",
            6: "0.28",
            16: "0.28",
            17: "0.40",
            21: "0.40",
            22: "0.28",
            23: "0.28",
        }
        for hour, price in expected.items():
            self.assertEqual(tariffs.price_for_hour(hour), Decimal(price))

    def test_energy_cost_uses_decimal(self):
        stamps = [datetime(2026, 9, 28, hour) for hour in (2, 12, 19)]
        cost = tariffs.energy_cost(stamps, [Decimal("2"), Decimal("2"), Decimal("2")])
        self.assertEqual(cost, Decimal("0.18") * 2 + Decimal("0.28") * 2 + Decimal("0.40") * 2)


class ForecastingTests(SimpleTestCase):
    """Testy pracy modeli prognostycznych i backtestu."""

    def test_backtest_and_forecast_outputs(self):
        series = [
            weather.WeatherHour(
                HISTORY_START + timedelta(hours=offset), 6.0 + (offset % 24), 50.0, 0.0
            )
            for offset in range(21 * 24)
        ]
        consumption, _ = household.simulate_household(series)
        rows, metrics = forecasting.backtest(consumption, series)
        self.assertEqual(len(rows), forecasting.BACKTEST_HOURS)
        for key in ("mae_model", "mape_model", "mae_baseline", "mape_baseline"):
            self.assertIn(key, metrics)
        future = [
            weather.WeatherHour(FORECAST_START + timedelta(hours=offset), 5.0, 50.0, 0.0)
            for offset in range(48)
        ]
        forecast_records = forecasting.forecast(consumption, series, future)
        self.assertEqual(len(forecast_records), 48)
        self.assertTrue(all(record.total >= 0 for record in forecast_records))


class PvTests(SimpleTestCase):
    """Testy symulacji fotowoltaiki, magazynu i doboru mocy PV."""

    def _toy_data(self):
        start = datetime(2027, 6, 7, 0)
        records = [
            household.ConsumptionHour(start + timedelta(hours=offset), (Decimal("1"),) * 6, "")
            for offset in range(7 * 24)
        ]
        radiation = [0.0] * 9 + [100.0, 400.0, 800.0, 800.0, 400.0, 100.0, 0.0] + [0.0] * 9
        series = [
            weather.WeatherHour(
                start + timedelta(hours=offset), 18.0, 20.0, float(radiation[offset % 24])
            )
            for offset in range(7 * 24)
        ]
        events = [household.FlexEvent("Zmywarka", start.date(), 19, 2, Decimal("1.000"))]
        return records, series, events

    def test_pv_production_from_radiation(self):
        self.assertEqual(pv.pv_production(800.0, Decimal("5")), Decimal("3.200"))

    def test_hourly_balance_self_export_grid(self):
        records, series, events = self._toy_data()
        result = pv.simulate(records, series, events, Decimal("5"))
        self.assertGreater(result.production_kwh, 0)
        self.assertEqual(result.variant_a.exported_kwh, 0)
        self.assertLessEqual(result.variant_b.grid_kwh, result.variant_a.grid_kwh)
        self.assertEqual(result.consumption_kwh, Decimal("6") * 24 * 7)
        # Tydzień danych kontra roczny OPEX: zwrot słusznie nie wychodzi.
        self.assertIsNone(result.variant_a.payback_years)

    def test_storage_moves_day_surplus_to_evening_with_losses(self):
        noon = datetime(2027, 6, 7, 12)
        evening = datetime(2027, 6, 7, 20)
        records = [
            household.ConsumptionHour(noon, (Decimal("1"), *(Decimal(0) for _ in range(5))), ""),
            household.ConsumptionHour(evening, (Decimal("3"), *(Decimal(0) for _ in range(5))), ""),
        ]
        weather_rows = [weather.WeatherHour(noon, 20.0, 0.0, 1000.0)]
        without = pv.simulate(records, weather_rows, [], Decimal("5"))
        storage = pv.StorageConfig(Decimal("3"), Decimal("3"), Decimal("2000"))
        with_storage = pv.simulate(records, weather_rows, [], Decimal("5"), storage)
        self.assertEqual(without.variant_b.grid_kwh, Decimal("3"))
        self.assertEqual(with_storage.variant_b.battery_charged_kwh, Decimal("3"))
        self.assertEqual(with_storage.variant_b.battery_delivered_kwh, Decimal("2.70"))
        self.assertEqual(with_storage.variant_b.grid_kwh, Decimal("0.30"))
        self.assertEqual(with_storage.variant_b.self_kwh, Decimal("3.70"))
        self.assertEqual(with_storage.investment_eur, Decimal("8500"))
        limited_power = pv.simulate(
            records,
            weather_rows,
            [],
            Decimal("5"),
            pv.StorageConfig(Decimal("3"), Decimal("1"), Decimal("2000")),
        )
        self.assertEqual(limited_power.variant_b.battery_delivered_kwh, Decimal("0.90"))
        self.assertEqual(limited_power.variant_b.grid_kwh, Decimal("2.10"))

        enough_sun = [
            records[0],
            household.ConsumptionHour(evening, (Decimal("2"), *(Decimal(0) for _ in range(5))), ""),
        ]
        choice = pv.choose_capacity(enough_sun, weather_rows, [], "coverage", storage)
        self.assertTrue(choice.target_met)
        self.assertEqual(
            pv.simulate(enough_sun, weather_rows, [], choice.kwp, storage).variant_b.grid_kwh,
            Decimal(0),
        )

    def test_full_year_uses_only_pv_energy_carried_across_year_boundary(self):
        start = datetime(2027, 1, 1)
        records = [
            household.ConsumptionHour(
                start + timedelta(hours=offset),
                (Decimal(1) if offset % 24 == 0 else Decimal(0), *(Decimal(0) for _ in range(5))),
                "",
            )
            for offset in range(8760)
        ]
        series = [
            weather.WeatherHour(
                row.timestamp, 18.0, 0.0, 1000.0 if row.timestamp.hour == 12 else 0.0
            )
            for row in records
        ]
        storage = pv.StorageConfig(Decimal(2), Decimal(2), Decimal(1000))
        result = pv.simulate(records, series, [], Decimal("1.4"), storage)
        self.assertEqual(result.variant_b.grid_kwh, Decimal(0))
        self.assertEqual(result.variant_b.battery_delivered_kwh, Decimal(365))
        self.assertEqual(result.variant_b.self_kwh, result.consumption_kwh)
        choice = pv.choose_capacity(records, series, [], "coverage", storage)
        self.assertEqual(choice.kwp, Decimal("1.4"))
        self.assertTrue(choice.target_met)

    def test_storage_purchase_price_changes_payback_but_not_coverage(self):
        start = datetime(2027, 1, 1)
        records = [
            household.ConsumptionHour(
                start + timedelta(days=day, hours=hour),
                (Decimal("2"), *(Decimal(0) for _ in range(5))),
                "",
            )
            for day in range(365)
            for hour in (12, 20)
        ]
        weather_rows = [
            weather.WeatherHour(
                row.timestamp, 18.0, 0.0, 1000.0 if row.timestamp.hour == 12 else 0.0
            )
            for row in records
        ]
        inexpensive = pv.StorageConfig(Decimal("2"), Decimal("2"), Decimal("1000"))
        expensive = pv.StorageConfig(Decimal("2"), Decimal("2"), Decimal("3000"))
        a = pv.simulate(records, weather_rows, [], Decimal("5"), inexpensive)
        b = pv.simulate(records, weather_rows, [], Decimal("5"), expensive)
        self.assertEqual(a.coverage_b, b.coverage_b)
        self.assertEqual(a.variant_b.savings, b.variant_b.savings)
        self.assertLess(a.variant_b.payback_years, b.variant_b.payback_years)
        choice = pv.choose_capacity(records, weather_rows, [], "payback", inexpensive)
        chosen = pv.simulate(records, weather_rows, [], choice.kwp, inexpensive)
        self.assertEqual(choice.coverage, chosen.coverage_b)
        self.assertEqual(choice.payback_years, chosen.variant_b.payback_years)

    def test_zero_capacity_keeps_previous_pv_balance(self):
        records, series, events = self._toy_data()
        original = pv.simulate(records, series, events, Decimal("5"))
        zero = pv.simulate(
            records,
            series,
            events,
            Decimal("5"),
            pv.StorageConfig(Decimal(0), Decimal(5), Decimal(0)),
        )
        self.assertEqual(original.variant_a, zero.variant_a)
        self.assertEqual(original.variant_b, zero.variant_b)

    def test_payback_with_year_of_sunny_data(self):
        start = datetime(2027, 1, 1, 0)
        records = [
            household.ConsumptionHour(start + timedelta(hours=offset), (Decimal("1"),) * 6, "")
            for offset in range(8760)
        ]
        pattern = [0.0] * 9 + [100.0, 400.0, 800.0, 800.0, 400.0, 100.0, 0.0] + [0.0] * 9
        series = [
            weather.WeatherHour(
                start + timedelta(hours=offset), 18.0, 20.0, float(pattern[offset % 24])
            )
            for offset in range(8760)
        ]
        result = pv.simulate(records, series, [], Decimal("5"))
        self.assertIsNotNone(result.variant_a.payback_years)
        self.assertAlmostEqual(float(result.variant_a.payback_years), 6.5, delta=0.5)

    def test_device_effects_cover_three_devices(self):
        records, series, events = self._toy_data()
        effects = pv.device_effects(records, series, events, Decimal("5"))
        self.assertEqual([effect.device for effect in effects], ["Zmywarka", "Pralka", "Suszarka"])
        dishwasher = effects[0]
        self.assertEqual(dishwasher.moved_kwh, Decimal("1.000"))
        self.assertGreaterEqual(dishwasher.grid_saved_kwh, 0)

    def test_representative_week_has_seven_days(self):
        records, series, events = self._toy_data()
        week = pv.representative_week(records, series, events, Decimal("5"), month=6)
        self.assertEqual(len(week.timestamps), 7 * 24)
        self.assertEqual(week.timestamps[0].weekday(), 0)
        daily = pv.daily_week_summary(week)
        self.assertEqual(len(daily), 7)
        self.assertEqual(
            sum((row.consumption_kwh for row in daily), Decimal(0)), sum(week.load, Decimal(0))
        )

    def test_capacity_choice_handles_reachable_and_unreachable_coverage(self):
        start = datetime(2027, 1, 1)
        sunny = [
            household.ConsumptionHour(
                start + timedelta(days=day, hours=12),
                (Decimal("2"), *(Decimal(0) for _ in range(5))),
                "",
            )
            for day in range(365)
        ]
        weather_sunny = [weather.WeatherHour(row.timestamp, 18.0, 0.0, 1000.0) for row in sunny]
        reached = pv.choose_capacity(sunny, weather_sunny, [], "coverage")
        self.assertEqual(reached.kwp, Decimal("2.5"))
        self.assertTrue(reached.target_met)
        self.assertEqual(reached.coverage, Decimal(100))

        night = [
            household.ConsumptionHour(
                start + timedelta(days=day),
                (Decimal("2"), *(Decimal(0) for _ in range(5))),
                "",
            )
            for day in range(365)
        ]
        limited = pv.choose_capacity(sunny + night, weather_sunny, [], "coverage")
        self.assertEqual(limited.kwp, Decimal("2.5"))
        self.assertFalse(limited.target_met)
        self.assertEqual(limited.coverage, Decimal(50))

        quickest = pv.choose_capacity(sunny + night, weather_sunny, [], "payback")
        self.assertEqual(quickest.kwp, Decimal("1.0"))
        self.assertIsNotNone(quickest.payback_years)
        selected = pv.simulate(sunny + night, weather_sunny, [], quickest.kwp)
        self.assertEqual(quickest.coverage, selected.coverage_b)
        self.assertEqual(quickest.payback_years, selected.variant_b.payback_years)

    def test_capacity_choice_reports_no_positive_payback(self):
        records, series, events = self._toy_data()
        result = pv.choose_capacity(records, series, events, "payback")
        self.assertIsNone(result.kwp)
        self.assertIsNone(result.payback_years)


class ViewTests(SimpleTestCase):
    """Testy widoków i renderowania dashboardu, historii i symulatora PV."""

    databases = {"default"}

    def setUp(self):
        self.data_dir = make_test_dir()
        self.addCleanup(clean_test_dir, self.data_dir)
        settings_context = override_settings(DEMO_DATA_DIR=self.data_dir)
        settings_context.enable()
        self.addCleanup(settings_context.disable)
        prepare_fixture_dir(self.data_dir)

    def test_scenario_switch_does_not_fall_back_to_other_scenario_data(self):
        self.assertEqual(self.client.get(reverse("switch_scenario", args=[1])).status_code, 302)
        self.assertEqual(self.client.session["active_scenario"], 1)
        self.assertContains(self.client.get(reverse("dashboard")), "Dane są chwilowo niedostępne")
        self.client.get(reverse("switch_scenario", args=[4]))
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "KOPENHAGA")
        for flag in ("🇵🇱", "🇪🇸", "🇩🇰", "🇵🇹"):
            self.assertContains(response, flag)

    def test_dashboard_shows_charts_peaks_and_error_panel(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Zużycie i temperatura")
        self.assertContains(response, "Model i prognoza odniesienia")
        self.assertContains(response, "Szczyt:")
        self.assertContains(response, "0,123")
        self.assertNotContains(response, "Przegląd godzinowy")
        self.assertNotContains(response, "Ile da dach z panelami?")
        self.assertNotContains(response, "Historia godzinowa")
        self.assertEqual(response.context["selected_count"], 7 * 24)
        self.assertEqual(response.context["selected_total"], Decimal(7 * 24))

        response_en = self.client.get(reverse("dashboard"), HTTP_COOKIE="django_language=en")
        self.assertEqual(response_en.status_code, 200)
        self.assertContains(response_en, "Energy use and temperature")
        self.assertContains(response_en, "Model versus reference forecast")
        self.assertContains(response_en, "COPENHAGEN, DENMARK")
        self.assertContains(response_en, "A House Full of Generations (Three Generations)")
        self.assertNotContains(response_en, "3 pokolenia")
        self.assertContains(response_en, "0.123")
        self.assertContains(response_en, "Peak:")
        self.assertNotContains(response_en, "Explore hourly data")
        self.assertNotContains(response_en, "What could rooftop solar deliver?")

    def test_charts_keep_hover_and_allow_horizontal_pan_without_wheel_zoom(self):
        records = load_history()[-24:]
        chart = build_overview_chart(records, load_weather_history()[-24:])
        self.assertEqual(chart.layout.hovermode, "x unified")
        self.assertIs(chart.layout.showlegend, False)
        self.assertTrue(all("%{x" not in trace.hovertemplate for trace in chart.data))
        self.assertTrue(all("<extra>" in trace.hovertemplate for trace in chart.data))
        self.assertIs(chart.layout.dragmode, False)
        self.assertIs(chart.layout.xaxis.fixedrange, False)
        self.assertIsNotNone(chart.layout.xaxis.minallowed)
        self.assertIsNotNone(chart.layout.xaxis.maxallowed)
        self.assertEqual(chart.layout.xaxis.range, (records[0].timestamp, records[-1].timestamp))
        self.assertEqual(chart.layout.xaxis.minallowed, records[0].timestamp)
        self.assertEqual(chart.layout.xaxis.maxallowed, records[-1].timestamp)
        self.assertIs(chart.layout.yaxis.fixedrange, True)
        self.assertIs(chart.layout.yaxis2.fixedrange, True)
        self.assertIs(PLOTLY_CONFIG["scrollZoom"], False)
        self.assertIs(PLOTLY_CONFIG["doubleClick"], False)
        self.assertIs(PLOTLY_CONFIG["displayModeBar"], False)

    def test_chart_time_bounds_for_empty_and_single_hour(self):
        empty = build_history_chart([], [])
        self.assertIsNone(empty.layout.xaxis.range)
        self.assertIsNone(empty.layout.xaxis.minallowed)
        self.assertIsNone(empty.layout.xaxis.maxallowed)

        record = load_history()[0]
        one_hour = build_history_chart([record], [])
        self.assertEqual(
            one_hour.layout.xaxis.range,
            (record.timestamp - timedelta(minutes=30), record.timestamp + timedelta(minutes=30)),
        )
        self.assertEqual(one_hour.layout.xaxis.minallowed, one_hour.layout.xaxis.range[0])
        self.assertEqual(one_hour.layout.xaxis.maxallowed, one_hour.layout.xaxis.range[1])

    def test_chart_controls_have_one_checkbox_per_trace_and_are_isolated(self):
        chart = build_overview_chart(load_history()[-24:], load_weather_history()[-24:])
        first = _chart_html(chart)
        second = _chart_html(chart)
        self.assertEqual(first.count('type="checkbox"'), len(chart.data))
        self.assertIn('data-chart-action="select-all"', first)
        self.assertIn('data-chart-action="deselect-all"', first)
        self.assertIn('data-chart-zoom="in"', first)
        self.assertIn('data-chart-zoom="out"', first)
        self.assertIn('aria-label="Zoom in"', first)
        self.assertIn("Energy use · simulation", first)
        self.assertNotEqual(
            first.split('data-chart-id="')[1].split('"')[0],
            second.split('data-chart-id="')[1].split('"')[0],
        )

    def test_hover_keeps_series_names_and_tiny_nonzero_energy(self):
        record = household.ConsumptionHour(
            HISTORY_START,
            (Decimal("0"), Decimal("0.00001"), *(Decimal("0") for _ in range(4))),
            "goście",
        )
        chart = build_history_chart([record], [weather.WeatherHour(HISTORY_START, 15.6, 50, 0)])
        self.assertEqual(chart.data[0].y[0], 0)
        self.assertEqual(chart.data[1].y[0], 0.00001)
        self.assertTrue(
            all(
                "%{fullData.name}: %{y:.5~r} kWh" in trace.hovertemplate for trace in chart.data[:6]
            )
        )
        self.assertEqual(chart.data[6].hovertemplate, "Events: %{text}<extra></extra>")
        self.assertEqual(chart.data[6].text[0], "guests")
        self.assertIn("Temperature:", chart.data[7].hovertemplate)

    def test_charts_show_rce_and_tariff_price_series(self):
        records = load_history()[-48:]
        rce_prices = {
            record.timestamp: Decimal("0.12") + Decimal(index) / Decimal(1000)
            for index, record in enumerate(records[:24])
        }
        history_chart = build_history_chart(
            records, load_weather_history()[-48:], prices=rce_prices, lang="pl"
        )
        price_traces = {trace.name: trace for trace in history_chart.data if trace.yaxis == "y3"}
        self.assertEqual(set(price_traces), {"Cena · RCE", "Cena · taryfa"})
        rce_trace = price_traces["Cena · RCE"]
        self.assertEqual(rce_trace.y[0], 0.12)
        self.assertIsNone(rce_trace.y[24])
        tariff_trace = price_traces["Cena · taryfa"]
        self.assertIsNone(tariff_trace.y[0])
        self.assertEqual(
            tariff_trace.y[24], float(tariffs.price_for_hour(records[24].timestamp.hour))
        )
        self.assertEqual(history_chart.layout.yaxis3.title.text, "€/kWh")
        self.assertIn("€/kWh", rce_trace.hovertemplate)

        forecast_records = load_forecast()[:24]
        forecast_chart = build_overview_chart(
            forecast_records, load_weather_forecast()[:24], prices={}, forecast=True
        )
        forecast_traces = {trace.name: trace for trace in forecast_chart.data}
        self.assertNotIn("Price · RCE", forecast_traces)
        self.assertEqual(
            forecast_traces["Price · tariff"].y[0],
            float(tariffs.price_for_hour(forecast_records[0].timestamp.hour)),
        )

    def test_load_tariff_prices_reads_hourly_prices(self):
        test_dir = make_test_dir()
        try:
            (test_dir / "tariff_prices.json").write_text(
                json.dumps(
                    {
                        "source": "test",
                        "unit": "EUR/kWh",
                        "prices": {"2026-09-28 17:00:00": "0.20916"},
                    }
                ),
                encoding="utf-8",
            )
            prices = load_tariff_prices(test_dir)
            self.assertEqual(prices, {datetime(2026, 9, 28, 17): Decimal("0.20916")})
        finally:
            clean_test_dir(test_dir)

    def test_charts_fall_back_to_tariff_without_rce_file(self):
        missing_dir = make_test_dir()
        try:
            self.assertEqual(load_tariff_prices(missing_dir), {})
        finally:
            clean_test_dir(missing_dir)

        records = load_history()[-24:]
        chart = build_history_chart(records, load_weather_history()[-24:], prices={}, lang="en")
        price_traces = [trace for trace in chart.data if trace.yaxis == "y3"]
        self.assertEqual([trace.name for trace in price_traces], ["Price · tariff"])
        self.assertEqual(
            price_traces[0].y[0], float(tariffs.price_for_hour(records[0].timestamp.hour))
        )

    def test_dashboard_simulation_periods_and_short_snapshot(self):
        for days in (1, 3, 5, 7, 14, 31):
            response = self.client.get(reverse("dashboard"), {"dni": days, "horyzont": "72"})
            self.assertEqual(response.context["selected_count"], min(days * 24, 10 * 24))
            self.assertEqual(response.context["selected_total"], Decimal(min(days * 24, 240)))
            self.assertEqual(response.context["horizon_hours"], 72)
            self.assertContains(response, f"?dni={days}&amp;horyzont=72")

        response = self.client.get(reverse("dashboard"), {"dni": "invalid"})
        self.assertEqual(response.context["simulation_days"], 7)

    def test_dashboard_31_days_with_full_history(self):
        write_weather(self.data_dir / weather.HISTORY_WEATHER_FILENAME, HISTORY_START, 35 * 24)
        write_consumption(self.data_dir / household.HISTORY_FILENAME, HISTORY_START, 35 * 24)
        response = self.client.get(reverse("dashboard"), {"dni": "31"})
        self.assertEqual(response.context["selected_count"], 31 * 24)
        self.assertEqual(response.context["selected_total"], Decimal(31 * 24))

    def test_hourly_history_filters_range_paginates_and_exports_csv(self):
        response = self.client.get(
            reverse("hourly_history"), {"start": "2026-09-20", "end": "2026-09-21"}
        )
        self.assertEqual(response.context["selected_count"], 48)
        self.assertContains(response, "1.000")
        self.assertContains(response, "Pobierz CSV")
        page_two = self.client.get(
            reverse("hourly_history"),
            {"start": "2026-09-20", "end": "2026-09-22", "page": 2},
        )
        self.assertEqual(page_two.context["page"].number, 2)
        self.assertContains(page_two, "start=2026-09-20&amp;end=2026-09-22")
        export = self.client.get(
            reverse("export_csv"), {"start": "2026-09-20", "end": "2026-09-21"}
        )
        self.assertEqual(export.status_code, 200)
        rows = list(csv.reader(io.StringIO(export.content.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 49)
        self.assertEqual(rows[0][0:2], ["Data_Czas", "Typ_danych"])
        self.assertEqual(rows[0][-1], "Zdarzenia")
        self.assertEqual(rows[1][1], "Symulacja")
        self.assertEqual(rows[1][2], "1.000")
        self.assertEqual(rows[1][-2], "1.000")

        # English language test
        response_en = self.client.get(
            reverse("hourly_history"),
            {"start": "2026-09-20", "end": "2026-09-21"},
            HTTP_COOKIE="django_language=en",
        )
        self.assertContains(response_en, "Download CSV")
        export_en = self.client.get(
            reverse("export_csv"),
            {"start": "2026-09-20", "end": "2026-09-21"},
            HTTP_COOKIE="django_language=en",
        )
        rows_en = list(csv.reader(io.StringIO(export_en.content.decode("utf-8-sig"))))
        self.assertEqual(rows_en[0][0:2], ["Date_Time", "Data_Type"])
        self.assertEqual(rows_en[0][-1], "Events")
        self.assertEqual(rows_en[1][1], "Simulation")

    def test_hourly_history_has_collapsible_filters_and_table(self):
        response = self.client.get(
            reverse("hourly_history"), {"start": "2026-09-20", "end": "2026-09-21"}
        )
        self.assertContains(response, '<details class="group mb-5 ')
        self.assertContains(response, 'aria-labelledby="filter-heading" >')
        self.assertContains(response, 'aria-labelledby="table-heading">')

        invalid = self.client.get(
            reverse("hourly_history"), {"start": "2026-09-21", "end": "2026-09-20"}
        )
        self.assertContains(invalid, 'aria-labelledby="filter-heading" open>')

    def test_polish_demo_labels_are_translated_for_presentation(self):
        self.assertEqual(device_name("Zmywarka", lang="en"), "Dishwasher")
        self.assertEqual(device_name("Zmywarka", lang="pl"), "Zmywarka")
        self.assertEqual(
            event_names("goście; pralka; praca zdalna", lang="en"),
            "guests; washing machine; working from home",
        )
        self.assertEqual(
            event_names("goście; pralka; praca zdalna", lang="pl"),
            "goście; pralka; praca zdalna",
        )
        self.assertEqual(
            event_names(
                "tryb opieki nad psem; wyjazd / nieobecność; pompa basenu; sauna; ładowanie EV",
                lang="en",
            ),
            "dog care routine; trip / absence; pool pump; sauna; EV charging",
        )

    def test_chart_dates_and_decimals_follow_language(self):
        records = load_history()[-24:]
        weather_rows = load_weather_history()[-24:]
        chart_pl = build_overview_chart(records, weather_rows, lang="pl")
        chart_en = build_overview_chart(records, weather_rows, lang="en")
        self.assertEqual(chart_pl.layout.separators, ", ")
        self.assertEqual(chart_pl.layout.xaxis.hoverformat, "%d.%m.%Y %H:%M")
        self.assertEqual(chart_en.layout.separators, ".,")
        self.assertIsNone(chart_en.layout.xaxis.tickformat)

    def test_new_events_are_english_in_table_chart_and_csv(self):
        history_path = self.data_dir / household.HISTORY_FILENAME
        with history_path.open(encoding="utf-8", newline="") as source:
            rows = list(csv.reader(source))
        rows[1][-1] = "pompa basenu; ładowanie EV"
        with history_path.open("w", encoding="utf-8", newline="") as output:
            csv.writer(output).writerows(rows)

        response = self.client.get(
            reverse("hourly_history"),
            {"start": "2026-09-15", "end": "2026-09-15"},
            HTTP_COOKIE="django_language=en",
        )
        self.assertContains(response, "pool pump; EV charging")
        chart = build_history_chart(load_history()[:24], load_weather_history()[:24], lang="en")
        event_trace = next(trace for trace in chart.data if trace.name == "Events")
        self.assertIn("pool pump; EV charging", event_trace.text)

        export = self.client.get(
            reverse("export_csv"),
            {"start": "2026-09-15", "end": "2026-09-15"},
            HTTP_COOKIE="django_language=en",
        )
        csv_rows = list(csv.reader(io.StringIO(export.content.decode("utf-8-sig"))))
        self.assertEqual(csv_rows[1][-1], "pool pump; EV charging")

    def test_builtin_form_errors_follow_selected_language(self):
        params = {"kwp": "bad"}
        response_en = self.client.get(
            reverse("pv_simulator"), params, HTTP_COOKIE="django_language=en"
        )
        self.assertContains(response_en, "Enter a number.")
        self.assertNotContains(response_en, "Wpisz liczbę.")
        response_pl = self.client.get(reverse("pv_simulator"), params)
        self.assertContains(response_pl, "Wpisz liczbę.")

    def test_hourly_history_uses_exact_rolling_period_from_dashboard(self):
        response = self.client.get(reverse("hourly_history"), {"dni": "3", "page": 2})
        self.assertEqual(response.context["selected_count"], 72)
        self.assertEqual(response.context["page"].number, 2)
        self.assertContains(response, "?dni=3&amp;page=1")
        export = self.client.get(reverse("export_csv"), {"dni": "3"})
        rows = list(csv.reader(io.StringIO(export.content.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 73)
        self.assertEqual(
            rows[1][0], (HISTORY_START + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        )

    def test_pv_simulator_shows_variants_and_recommendations(self):
        response = self.client.get(reverse("pv_simulator"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Warianty instalacji")
        self.assertContains(response, "Zakup z sieci")
        self.assertContains(response, "Zmywarka")
        self.assertContains(response, "Efekt zmiany godziny pracy")
        self.assertNotContains(response, "Wskazówka:")
        self.assertNotContains(response, "nie ma czego przesuwać")
        self.assertContains(response, "Dobierz do 100% pokrycia")
        self.assertContains(response, "Najkrótszy zwrot (B)")

        response_en = self.client.get(reverse("pv_simulator"), HTTP_COOKIE="django_language=en")
        self.assertEqual(response_en.status_code, 200)
        self.assertContains(response_en, "PV system options")
        self.assertContains(response_en, "Grid purchases")
        self.assertContains(response_en, "Dishwasher")
        self.assertContains(response_en, "Effect of shifting appliance use")
        self.assertContains(response_en, "Find 100% coverage")
        self.assertContains(response_en, "Shortest payback (B)")

    def test_pv_form_has_suggestion_chips_and_collapsible_sections(self):
        response = self.client.get(reverse("pv_simulator"))
        self.assertContains(response, 'data-target="id_kwp"')
        self.assertContains(response, "suggestion-chip")
        self.assertContains(response, 'data-value="25"')
        self.assertContains(response, 'data-value="150"')
        self.assertContains(response, 'data-target="id_magazyn_kwh"')
        self.assertContains(response, 'data-value="500"')
        self.assertContains(response, 'data-target="id_magazyn_moc_kw"')
        self.assertNotContains(response, 'data-target="id_magazyn_koszt_eur"')

        self.assertContains(response, 'aria-labelledby="pv-form-heading" >')
        self.assertContains(response, 'aria-labelledby="variants-heading">')
        self.assertContains(response, 'aria-labelledby="daily-heading">')
        self.assertContains(response, 'aria-labelledby="reco-heading">')

        invalid = self.client.get(reverse("pv_simulator"), {"kwp": "bad"})
        self.assertContains(invalid, 'aria-labelledby="pv-form-heading" open>')

    def test_pv_auto_choices_show_result_and_preserve_manual_mode(self):
        coverage = self.client.get(reverse("pv_simulator"), {"cel": "coverage", "miesiac": "6"})
        self.assertEqual(coverage.status_code, 200)
        self.assertContains(coverage, "100% pokrycia nie jest osiągalne")
        self.assertEqual(coverage.context["kwp"], Decimal("1.0"))
        self.assertEqual(coverage.context["form"]["miesiac"].value(), "6")

        payback = self.client.get(reverse("pv_simulator"), {"cel": "payback", "miesiac": "6"})
        self.assertEqual(payback.status_code, 200)
        self.assertContains(payback, "Brak dodatniego zwrotu")
        self.assertEqual(payback.context["kwp"], Decimal("5"))

        manual = self.client.get(reverse("pv_simulator"), {"kwp": "4", "miesiac": "6"})
        self.assertEqual(manual.context["kwp"], Decimal("4"))
        self.assertNotContains(manual, "Wynik automatycznego doboru")

        coverage_en = self.client.get(
            reverse("pv_simulator"),
            {"cel": "coverage", "miesiac": "6"},
            HTTP_COOKIE="django_language=en",
        )
        self.assertContains(coverage_en, "100% coverage is not achievable")

    def test_pv_storage_form_and_daily_results(self):
        params = {
            "kwp": "5",
            "miesiac": "6",
            "magazyn_kwh": "10",
            "magazyn_moc_kw": "5",
            "magazyn_koszt_eur": "7000",
        }
        response = self.client.get(reverse("pv_simulator"), params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected"].investment_eur, Decimal("13500"))
        self.assertEqual(len(response.context["week_days"]), 7)
        self.assertContains(response, "Średnie dzienne zużycie budynku")
        self.assertContains(response, "Zużycie budynku w wybranym tygodniu")
        self.assertContains(response, "Cena zakupu")

        no_price = self.client.get(reverse("pv_simulator"), {**params, "magazyn_koszt_eur": "0"})
        self.assertContains(no_price, "Podaj dodatnią cenę zakupu magazynu")
        self.assertNotIn("selected", no_price.context)

        no_battery = self.client.get(reverse("pv_simulator"), {**params, "magazyn_kwh": "0"})
        self.assertContains(no_battery, "Przy pojemności 0 kWh cena musi wynosić 0")

        automatic = self.client.get(reverse("pv_simulator"), {**params, "cel": "coverage"})
        self.assertEqual(automatic.status_code, 200)
        self.assertEqual(automatic.context["storage"].capacity_kwh, Decimal("10"))
        self.assertContains(automatic, "Nawet przy 150")

        large = self.client.get(
            reverse("pv_simulator"),
            {
                **params,
                "kwp": "100",
                "magazyn_kwh": "3000",
                "magazyn_moc_kw": "100",
                "magazyn_koszt_eur": "1000000",
            },
        )
        self.assertEqual(large.status_code, 200)
        self.assertEqual(large.context["kwp"], Decimal("100"))
        self.assertContains(large, "scenariuszem teoretycznym")

        # English check
        response_en = self.client.get(
            reverse("pv_simulator"), params, HTTP_COOKIE="django_language=en"
        )
        self.assertContains(response_en, "Average daily household use")
        self.assertContains(response_en, "Purchase price")

    def test_missing_data_shows_neutral_status(self):
        (self.data_dir / household.HISTORY_FILENAME).unlink()
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Dane są chwilowo niedostępne.", status_code=200)
        self.assertNotContains(response, "prepare_demo_data")

        response_en = self.client.get(reverse("dashboard"), HTTP_COOKIE="django_language=en")
        self.assertContains(response_en, "Demo data is temporarily unavailable.", status_code=200)

    def test_language_switcher_and_toggle(self):
        res_default = self.client.get(reverse("dashboard"))
        self.assertContains(res_default, '<html lang="pl">')
        self.assertContains(res_default, "Pulpit")

        # Switch to English
        res_switch = self.client.get(
            reverse("change_language", args=["en"]) + "?next=" + reverse("dashboard")
        )
        self.assertEqual(res_switch.status_code, 302)
        self.assertEqual(res_switch.cookies["django_language"].value, "en")

        res_en = self.client.get(reverse("dashboard"), HTTP_COOKIE="django_language=en")
        self.assertContains(res_en, '<html lang="en">')
        self.assertContains(res_en, "Dashboard")
        self.assertContains(res_en, "Hourly data →")

        # Switch back to Polish
        res_switch_pl = self.client.get(
            reverse("change_language", args=["pl"]) + "?next=" + reverse("dashboard")
        )
        self.assertEqual(res_switch_pl.status_code, 302)
        self.assertEqual(res_switch_pl.cookies["django_language"].value, "pl")

        res_pl = self.client.get(reverse("dashboard"), HTTP_COOKIE="django_language=pl")
        self.assertContains(res_pl, '<html lang="pl">')
        self.assertContains(res_pl, "Pulpit")

    def test_loaders_parse_fixture_files(self):
        history = load_history()
        records, series, events = load_annual()
        self.assertEqual(len(history), 10 * 24)
        self.assertEqual(len(records), 14 * 24)
        self.assertEqual(len(series), 14 * 24)
        self.assertEqual(events[0].device, "Zmywarka")


class ApiTests(TestCase):
    """Testy endpointów REST API dla smart schedule, prognoz i PV."""

    def setUp(self):
        self.data_dir = make_test_dir()
        self.addCleanup(clean_test_dir, self.data_dir)
        settings_context = override_settings(
            DEMO_DATA_DIR=self.data_dir,
            API_KEY="test-api-key",
        )
        settings_context.enable()
        self.addCleanup(settings_context.disable)
        prepare_fixture_dir(self.data_dir)

        from energy.api import get_expected_api_key

        api_key = get_expected_api_key()
        if api_key:
            self.client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {api_key}"

    def test_smart_schedule_today_endpoint(self):
        res = self.client.get(reverse("api_smart_schedule_today"))
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertIn("current_hour", data)
        self.assertEqual(data["lowest_tariff_hours"], list(range(6)))
        self.assertEqual(data["highest_tariff_hours"], list(range(17, 22)))
        self.assertEqual(len(data["timeline"]), 24)
        self.assertNotIn("recommended_action", data["timeline"][0])

    def test_api_descriptions_follow_explicit_language(self):
        summary = self.client.get(reverse("api_dashboard_summary"), {"lang": "en"})
        self.assertEqual(summary.status_code, 200)
        payload = summary.json()["data"]
        self.assertIn(
            payload["tariff"]["period_label"],
            {
                "Afternoon peak (expensive)",
                "Night valley (very cheap)",
                "Day rate (PV window)",
                "Standard day rate",
            },
        )
        self.assertEqual(payload["last_reading"]["dominant_category"]["label"], "Base load")

        via_header = self.client.get(
            reverse("api_tariffs_info"), HTTP_ACCEPT_LANGUAGE="en-US,en;q=0.9"
        )
        self.assertEqual(via_header.status_code, 200)
        self.assertEqual(
            via_header.json()["data"]["periods"][0]["label"], "Night valley (lowest rate)"
        )

        invalid = self.client.get(
            reverse("api_consumption_forecast"), {"horizon": "50", "lang": "en"}
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("Invalid forecast horizon", invalid.json()["error"]["message"])

        devices = self.client.get(reverse("api_devices_guidance"), {"lang": "en"})
        self.assertEqual(devices.json()["data"]["devices"][0]["device"], "Dishwasher")

        pv_result = self.client.get(reverse("api_pv_simulate"), {"lang": "en"})
        self.assertEqual(pv_result.json()["data"]["variant_a"]["name"], "Current routine")

        assumptions = self.client.get(reverse("api_system_assumptions"), {"lang": "en"})
        self.assertEqual(assumptions.json()["data"]["location"], "Copenhagen, Denmark")

        shifted = self.client.get(
            reverse("api_shift_simulation"), {"device": "Pralka", "lang": "en"}
        )
        self.assertIn("Tariff cost per cycle", shifted.json()["data"]["recommendation"])

    def test_devices_guidance_endpoint(self):
        res = self.client.get(reverse("api_devices_guidance"))
        self.assertEqual(res.status_code, 200)
        devices = res.json()["data"]["devices"]
        self.assertTrue(len(devices) >= 4)
        names = [d["device"] for d in devices]
        self.assertIn("Zmywarka", names)
        self.assertIn("Pralka", names)
        self.assertIn("Suszarka bębnowa", names)
        self.assertNotIn("tip_pl", devices[0])
        self.assertIn("annual_energy_kwh", devices[0])

    def test_devices_shift_simulation_get_and_post(self):
        # Odczyt przez GET z parametrami URL
        res_get = self.client.get(
            reverse("api_shift_simulation"),
            {"device": "Pralka", "original_hour": "19", "target_hour": "12", "energy_kwh": "0.8"},
        )
        self.assertEqual(res_get.status_code, 200)
        payload_get = res_get.json()["data"]
        self.assertEqual(payload_get["device"], "Pralka")
        self.assertEqual(payload_get["original_price_eur"], 0.40)
        self.assertEqual(payload_get["target_price_eur"], 0.28)
        self.assertGreater(payload_get["savings_per_cycle_eur"], 0)
        self.assertTrue(payload_get["in_pv_window"])
        self.assertIn("recommendation", payload_get)

        # Odczyt przez POST z ciałem JSON
        res_post = self.client.post(
            reverse("api_shift_simulation"),
            data=json.dumps({"device": "Zmywarka", "original_hour": 19, "target_hour": 1}),
            content_type="application/json",
        )
        self.assertEqual(res_post.status_code, 200)
        payload_post = res_post.json()["data"]
        self.assertTrue(payload_post["in_night_valley"])
        self.assertGreater(payload_post["savings_per_cycle_eur"], 0)

    def test_dashboard_summary_endpoint(self):
        res = self.client.get(reverse("api_dashboard_summary"))
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertIn("last_reading", data)
        self.assertIn("tariff", data)
        self.assertIn("history_last_24h_kwh", data)
        self.assertIn("forecast_next_24h_kwh", data)
        self.assertIn("pv_preview", data)
        self.assertEqual(data["tariff"]["currency"], "EUR")

    def test_consumption_history_endpoint_and_pagination(self):
        res = self.client.get(
            reverse("api_consumption_history"),
            {"start": "2026-09-15", "end": "2026-09-16", "page": "1", "page_size": "10"},
        )
        self.assertEqual(res.status_code, 200)
        payload = res.json()["data"]
        self.assertEqual(len(payload["items"]), 10)
        self.assertEqual(payload["pagination"]["page"], 1)
        self.assertEqual(payload["pagination"]["page_size"], 10)
        self.assertEqual(payload["pagination"]["total_items"], 48)
        self.assertEqual(payload["pagination"]["total_pages"], 5)
        self.assertTrue(payload["pagination"]["has_next"])
        self.assertFalse(payload["pagination"]["has_previous"])
        self.assertIn("categories_totals", payload["summary"])

    def test_consumption_history_validation_errors(self):
        # Błędny zakres dat (end < start) -> 400
        res_date = self.client.get(
            reverse("api_consumption_history"),
            {"start": "2026-09-20", "end": "2026-09-10"},
        )
        self.assertEqual(res_date.status_code, 400)
        self.assertEqual(res_date.json()["error"]["code"], "INVALID_DATE_RANGE")

        # Błędny page -> 400
        res_page = self.client.get(reverse("api_consumption_history"), {"page": "0"})
        self.assertEqual(res_page.status_code, 400)
        self.assertEqual(res_page.json()["error"]["code"], "INVALID_PAGINATION")

    def test_consumption_forecast_endpoint(self):
        for horizon in (24, 72, 168):
            res = self.client.get(reverse("api_consumption_forecast"), {"horizon": str(horizon)})
            self.assertEqual(res.status_code, 200)
            payload = res.json()["data"]
            self.assertEqual(payload["horizon_hours"], horizon)
            self.assertEqual(len(payload["items"]), horizon)
            self.assertTrue(len(payload["peaks"]) > 0)
            self.assertIn("tariff_price_eur", payload["items"][0])

    def test_consumption_forecast_invalid_horizon(self):
        res = self.client.get(reverse("api_consumption_forecast"), {"horizon": "50"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"]["code"], "INVALID_HORIZON")

    def test_tariffs_endpoint(self):
        res = self.client.get(reverse("api_tariffs_info"))
        self.assertEqual(res.status_code, 200)
        payload = res.json()["data"]
        self.assertEqual(payload["currency"], "EUR")
        self.assertEqual(len(payload["periods"]), 4)
        self.assertIn("recommendations", payload)
        self.assertEqual(payload["recommendations"]["cheapest_window"]["price_per_kwh"], 0.18)

    def test_pv_simulate_get_and_post(self):
        # GET
        res_get = self.client.get(reverse("api_pv_simulate"), {"kwp": "5", "month": "6"})
        self.assertEqual(res_get.status_code, 200)
        data_get = res_get.json()["data"]
        self.assertEqual(data_get["kwp"], 5.0)
        self.assertIn("variant_a", data_get)
        self.assertIn("variant_b", data_get)
        self.assertIn("optimization_gain", data_get)
        self.assertEqual(len(data_get["device_recommendations"]), 3)

        # POST z profilem tygodnia dla dostępnego miesiąca (czerwiec)
        res_post = self.client.post(
            reverse("api_pv_simulate"),
            data=json.dumps({"kwp": "6", "month": 6, "include_week_profile": True}),
            content_type="application/json",
        )
        self.assertEqual(res_post.status_code, 200)
        data_post = res_post.json()["data"]
        self.assertEqual(data_post["kwp"], 6.0)
        self.assertIn("week_profile", data_post)
        self.assertEqual(len(data_post["week_profile"]["timestamps"]), 7 * 24)

        # POST z profilem tygodnia dla miesiąca bez pełnego tygodnia w teście
        res_no_week = self.client.post(
            reverse("api_pv_simulate"),
            data=json.dumps({"kwp": "6", "month": 1, "include_week_profile": True}),
            content_type="application/json",
        )
        self.assertEqual(res_no_week.status_code, 200)
        self.assertIsNone(res_no_week.json()["data"]["week_profile"])
        self.assertIn("week_profile_warning", res_no_week.json()["data"])

    def test_pv_simulate_validation_errors(self):
        res_neg = self.client.get(reverse("api_pv_simulate"), {"kwp": "-5"})
        self.assertEqual(res_neg.status_code, 400)
        self.assertEqual(res_neg.json()["error"]["code"], "INVALID_PV_PARAMS")

    def test_pv_variants_endpoint(self):
        res = self.client.get(reverse("api_pv_variants"))
        self.assertEqual(res.status_code, 200)
        variants = res.json()["data"]["variants"]
        self.assertEqual(len(variants), len(pv.COMPARE_VARIANTS_KWP))

    def test_devices_flexible_events_endpoint(self):
        res = self.client.get(reverse("api_flexible_events"), {"device": "Zmywarka"})
        self.assertEqual(res.status_code, 200)
        payload = res.json()["data"]
        self.assertTrue(all(item["device"] == "Zmywarka" for item in payload["items"]))

    def test_devices_shift_simulation_endpoint(self):
        # Przesunięcie ze szczytu 19:00 na 12:00 (okno PV)
        res = self.client.post(
            reverse("api_shift_simulation"),
            data=json.dumps(
                {
                    "device": "Pralka",
                    "original_hour": 19,
                    "target_hour": 12,
                    "energy_kwh": 0.8,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        payload = res.json()["data"]
        self.assertEqual(payload["device"], "Pralka")
        self.assertEqual(payload["original_price_eur"], 0.40)
        self.assertEqual(payload["target_price_eur"], 0.28)
        self.assertGreater(payload["savings_per_cycle_eur"], 0)
        self.assertTrue(payload["in_pv_window"])
        self.assertIn("recommendation", payload)

    def test_devices_shift_simulation_validation_errors(self):
        # Nieobsługiwane urządzenie
        res_dev = self.client.post(
            reverse("api_shift_simulation"),
            data=json.dumps({"device": "Klimatyzator", "original_hour": 19, "target_hour": 12}),
            content_type="application/json",
        )
        self.assertEqual(res_dev.status_code, 400)
        self.assertEqual(res_dev.json()["error"]["code"], "INVALID_DEVICE")

        # Błędna godzina
        res_hour = self.client.post(
            reverse("api_shift_simulation"),
            data=json.dumps({"device": "Pralka", "original_hour": 25, "target_hour": 12}),
            content_type="application/json",
        )
        self.assertEqual(res_hour.status_code, 400)
        self.assertEqual(res_hour.json()["error"]["code"], "INVALID_HOURS")

    def test_system_assumptions_and_metrics_endpoints(self):
        res_assumptions = self.client.get(reverse("api_system_assumptions"))
        self.assertEqual(res_assumptions.status_code, 200)
        self.assertIn("household", res_assumptions.json()["data"])
        self.assertIn("device_profiles", res_assumptions.json()["data"])

        res_metrics = self.client.get(reverse("api_system_metrics"))
        self.assertEqual(res_metrics.status_code, 200)
        self.assertIn("mae_model", res_metrics.json()["data"])

    def test_api_503_when_data_missing(self):
        (self.data_dir / household.HISTORY_FILENAME).unlink()
        res = self.client.get(reverse("api_dashboard_summary"))
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()["error"]["code"], "DATA_NOT_FOUND")

    def test_unsupported_methods_return_405(self):
        res = self.client.delete(reverse("api_consumption_history"))
        self.assertEqual(res.status_code, 405)

    def test_scenarios_list_and_active_endpoint(self):
        # 1. Lista scenariuszy
        res = self.client.get(reverse("api_scenarios_list"))
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertEqual(len(data["scenarios"]), 5)
        self.assertEqual(data["active_scenario_id"], 4)
        active_entry = next(s for s in data["scenarios"] if s["id"] == 4)
        self.assertTrue(active_entry["is_active"])
        self.assertIn("🇩🇰", active_entry["flag"])
        self.assertEqual(active_entry["city"], "Kopenhaga, Dania")

        # 2. Aktywny scenariusz - domyślnie 4
        res_act = self.client.get(reverse("api_active_scenario"))
        self.assertEqual(res_act.status_code, 200)
        act_data = res_act.json()["data"]
        self.assertEqual(act_data["id"], 4)
        self.assertEqual(act_data["city"], "Kopenhaga, Dania")

        # 3. Zmiana aktywnego scenariusza przez parametr ?scenario=1
        res_s1 = self.client.get(reverse("api_active_scenario"), {"scenario": "1"})
        self.assertEqual(res_s1.status_code, 200)
        s1_data = res_s1.json()["data"]
        self.assertEqual(s1_data["id"], 1)
        self.assertEqual(s1_data["city"], "Warszawa, Polska")

        # 4. Zmiana aktywnego scenariusza przez nagłówek HTTP X-Scenario-ID: 2
        res_s2 = self.client.get(reverse("api_active_scenario"), headers={"X-Scenario-ID": "2"})
        self.assertEqual(res_s2.status_code, 200)
        s2_data = res_s2.json()["data"]
        self.assertEqual(s2_data["id"], 2)
        self.assertEqual(s2_data["city"], "Katowice, Polska")

    def test_scenario_data_dir_loading_in_api(self):
        # Tworzymy dane dla scenariusza 1 w katalogu testowym
        scen1_dir = self.data_dir / "scenario_1"
        scen1_dir.mkdir(parents=True, exist_ok=True)
        prepare_fixture_dir(scen1_dir)

        # Wywołujemy dashboard/summary dla scenariusza 1
        res = self.client.get(reverse("api_dashboard_summary"), {"scenario": "1"})
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertEqual(data["scenario"]["id"], 1)
        self.assertEqual(data["scenario"]["city"], "Warszawa, Polska")
        self.assertIn("last_reading", data)

        # Wywołujemy devices/guidance z nagłówkiem X-Scenario-ID: 1
        res_dev = self.client.get(reverse("api_devices_guidance"), headers={"X-Scenario-ID": "1"})
        self.assertEqual(res_dev.status_code, 200)
        self.assertEqual(res_dev.json()["data"]["scenario"]["id"], 1)

        # Wywołujemy system/assumptions z ?scenario=1
        res_assump = self.client.get(reverse("api_system_assumptions"), {"scenario": "1"})
        self.assertEqual(res_assump.status_code, 200)
        assump_data = res_assump.json()["data"]
        self.assertEqual(assump_data["scenario"]["id"], 1)
        self.assertEqual(assump_data["household"]["residents_count"], 1)

    def test_scenarios_require_bearer_token(self):
        client = self.client_class()
        res_list = client.get(reverse("api_scenarios_list"))
        self.assertEqual(res_list.status_code, 401)

        res_active = client.get(reverse("api_active_scenario"))
        self.assertEqual(res_active.status_code, 401)
