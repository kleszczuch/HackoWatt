"""Testy scenariusza 4: pogoda, generator, taryfa, prognoza, PV i widoki."""

import csv
import io
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from energy import forecasting, household, pv, tariffs, weather
from energy.data import load_annual, load_history

HISTORY_START = datetime(2026, 9, 15, 0)
FORECAST_START = datetime(2026, 10, 20, 11)
ANNUAL_START = datetime(2027, 6, 7, 0)  # poniedziałek


def make_test_dir() -> Path:
    path = settings.BASE_DIR / "data" / f"test-{uuid4().hex}"
    path.mkdir(parents=True)
    return path


def clean_test_dir(path: Path) -> None:
    for child in path.iterdir():
        child.unlink()
    path.rmdir()


def write_weather(path: Path, start: datetime, hours: int, temp: float = 5.0) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(weather.WEATHER_COLUMNS)
        for offset in range(hours):
            stamp = start + timedelta(hours=offset)
            writer.writerow([stamp.strftime("%Y-%m-%d %H:%M:%S"), f"{temp:.1f}", "50", "0.0"])


def write_consumption(path: Path, start: datetime, hours: int, base: str = "1.000") -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(household.CONSUMPTION_COLUMNS)
        for offset in range(hours):
            stamp = start + timedelta(hours=offset)
            row = [stamp.strftime("%Y-%m-%d %H:%M:%S"), "Monday", stamp.hour]
            writer.writerow([*row, base, 0, 0, 0, 0, 0, base, ""])


def write_events(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(household.EVENT_COLUMNS)
        writer.writerow(["2027-06-07", "Zmywarka", 19, 2, "1.000"])
        writer.writerow(["2027-06-08", "Pralka", 10, 1, "0.800"])


def write_backtest(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(forecasting.BACKTEST_COLUMNS)
        for offset in range(24):
            stamp = HISTORY_START + timedelta(hours=offset)
            writer.writerow([stamp.strftime("%Y-%m-%d %H:%M:%S"), "1.000", "1.100", "0.900"])


def write_metrics(path: Path) -> None:
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


class ViewTests(SimpleTestCase):
    def setUp(self):
        self.data_dir = make_test_dir()
        self.addCleanup(clean_test_dir, self.data_dir)
        settings_context = override_settings(DEMO_DATA_DIR=self.data_dir)
        settings_context.enable()
        self.addCleanup(settings_context.disable)
        prepare_fixture_dir(self.data_dir)

    def test_dashboard_shows_charts_peaks_and_error_panel(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Zużycie i temperatura")
        self.assertContains(response, "Model kontra baseline")
        self.assertContains(response, "Szczyt:")
        self.assertContains(response, "0,123")  # MAE modelu z metryki (lokalizacja PL)

    def test_dashboard_filters_range_and_exports_csv(self):
        response = self.client.get(
            reverse("dashboard"), {"start": "2026-09-20", "end": "2026-09-21"}
        )
        self.assertEqual(response.context["selected_count"], 48)
        export = self.client.get(
            reverse("export_csv"), {"start": "2026-09-20", "end": "2026-09-21"}
        )
        self.assertEqual(export.status_code, 200)
        rows = list(csv.reader(io.StringIO(export.content.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 49)

    def test_pv_simulator_shows_variants_and_recommendations(self):
        response = self.client.get(reverse("pv_simulator"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Warianty instalacji")
        self.assertContains(response, "Zakup z sieci")
        self.assertContains(response, "Zmywarka")

    def test_assumptions_page_documents_everything(self):
        response = self.client.get(reverse("assumptions"))
        self.assertEqual(response.status_code, 200)
        for phrase in ("Kopenhaga", "1300", "35 dni", "szacunkiem"):
            self.assertContains(response, phrase)

    def test_missing_data_shows_preparation_command(self):
        (self.data_dir / household.HISTORY_FILENAME).unlink()
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "prepare_demo_data", status_code=200)

    def test_loaders_parse_fixture_files(self):
        history = load_history()
        records, series, events = load_annual()
        self.assertEqual(len(history), 10 * 24)
        self.assertEqual(len(records), 14 * 24)
        self.assertEqual(len(series), 14 * 24)
        self.assertEqual(events[0].device, "Zmywarka")


class ApiTests(TestCase):
    def setUp(self):
        self.data_dir = make_test_dir()
        self.addCleanup(clean_test_dir, self.data_dir)
        settings_context = override_settings(
            DEMO_DATA_DIR=self.data_dir,
        )
        settings_context.enable()
        self.addCleanup(settings_context.disable)
        prepare_fixture_dir(self.data_dir)

    def test_smart_schedule_today_endpoint(self):
        res = self.client.get(reverse("api_smart_schedule_today"))
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertIn("current_hour", data)
        self.assertIn("best_windows", data)
        self.assertIn("tips_by_generation", data)
        self.assertIn("dla_dziadkow", data["tips_by_generation"])
        self.assertIn("dla_mlodziezy", data["tips_by_generation"])
        self.assertEqual(len(data["timeline"]), 24)

    def test_devices_guidance_endpoint(self):
        res = self.client.get(reverse("api_devices_guidance"))
        self.assertEqual(res.status_code, 200)
        devices = res.json()["data"]["devices"]
        self.assertTrue(len(devices) >= 4)
        names = [d["device"] for d in devices]
        self.assertIn("Zmywarka", names)
        self.assertIn("Pralka", names)
        self.assertIn("Suszarka bębnowa", names)

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
