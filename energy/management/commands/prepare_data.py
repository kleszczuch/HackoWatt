"""Przygotowanie danych: pogoda Open-Meteo, symulacja wybranego scenariusza, prognoza."""

from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from energy import forecasting, household, weather
from energy.scenarios import SCENARIOS


class Command(BaseCommand):
    help = "Generuje 35 dni historii, prognozę 7 dni i roczny szacunek pod symulator PV."

    def add_arguments(self, parser):
        parser.add_argument("--scenario", type=int, choices=SCENARIOS)

    def _cached_weather(self, data_dir, fetch_error):
        self.stderr.write(
            self.style.WARNING(f"Brak pobierania ({fetch_error}); używam zapisanych CSV pogody.")
        )
        try:
            return (
                weather.read_weather_csv(data_dir / weather.HISTORY_WEATHER_FILENAME),
                weather.read_weather_csv(data_dir / weather.FORECAST_WEATHER_FILENAME),
                weather.read_weather_csv(data_dir / weather.YEAR_WEATHER_FILENAME),
            )
        except (weather.WeatherFetchError, FileNotFoundError) as exc:
            raise CommandError("Nie udało się pobrać pogody, a brak plików w data/.") from exc

    def handle(self, *args, **options):
        base_data_dir = settings.DEMO_DATA_DIR
        scenario_ids = [options["scenario"]] if options["scenario"] else SCENARIOS
        for scen_id in scenario_ids:
            scen_info = SCENARIOS[scen_id]
            self.stdout.write(self.style.SUCCESS(f"Generuję dane dla: {scen_info['name']}"))
            scen_dir = base_data_dir / scen_info["folder"]
            scen_dir.mkdir(parents=True, exist_ok=True)
            try:
                now = weather.local_now(scen_info["timezone"])
                series = weather.fetch_weather_series(
                    latitude=scen_info["lat"],
                    longitude=scen_info["lon"],
                    timezone=scen_info["timezone"],
                )
                history_weather, forecast_weather = weather.split_history_forecast(series, now)
                year_weather = weather.fetch_year_weather(
                    now,
                    latitude=scen_info["lat"],
                    longitude=scen_info["lon"],
                    timezone=scen_info["timezone"],
                )
                weather.write_weather_csv(
                    history_weather, scen_dir / weather.HISTORY_WEATHER_FILENAME
                )
                weather.write_weather_csv(
                    forecast_weather, scen_dir / weather.FORECAST_WEATHER_FILENAME
                )
                weather.write_weather_csv(year_weather, scen_dir / weather.YEAR_WEATHER_FILENAME)
            except weather.WeatherFetchError as exc:
                history_weather, forecast_weather, year_weather = self._cached_weather(
                    scen_dir, exc
                )

            consumption, events = household.simulate_household(history_weather, scenario_id=scen_id)
            annual, annual_events = household.simulate_household(year_weather, scenario_id=scen_id)

            # Mnożniki zużycia dla profili gospodarstw domowych.
            mnozniki = {
                1: Decimal("0.40"),  # Warszawa: Aleksandra (singielka, małe zużycie)
                2: Decimal("0.80"),  # Katowice: Marek i Ania (4 osoby)
                3: Decimal("2.30"),  # Barcelona: Luxury (wielki dom, sauna, basen, EV)
                4: Decimal("1.00"),  # Kopenhaga: Dom Pokoleń (6 osób, oryginał)
                5: Decimal("0.60"),  # Lizbona: Ola i Tomek (2 osoby + pies)
            }
            mult = mnozniki.get(scen_id, Decimal("1.00"))

            if mult != Decimal("1.00"):
                consumption = [
                    c.__class__(
                        c.timestamp, tuple(round(v * mult, 3) for v in c.categories), c.events
                    )
                    for c in consumption
                ]
                annual = [
                    c.__class__(
                        c.timestamp, tuple(round(v * mult, 3) for v in c.categories), c.events
                    )
                    for c in annual
                ]

            household.write_consumption_csv(consumption, scen_dir / household.HISTORY_FILENAME)
            household.write_events_csv(events, scen_dir / household.FLEX_EVENTS_FILENAME)
            household.write_consumption_csv(
                annual, scen_dir / household.ANNUAL_CONSUMPTION_FILENAME
            )
            household.write_events_csv(annual_events, scen_dir / household.ANNUAL_EVENTS_FILENAME)

            backtest_rows, metrics = forecasting.backtest(consumption, history_weather)
            forecast_records = forecasting.forecast(consumption, history_weather, forecast_weather)
            metrics["wygenerowano"] = now.strftime("%Y-%m-%d %H:%M:%S")
            forecasting.write_backtest_csv(backtest_rows, scen_dir / forecasting.BACKTEST_FILENAME)
            forecasting.write_metrics_json(metrics, scen_dir / forecasting.METRICS_FILENAME)
            household.write_consumption_csv(
                forecast_records, scen_dir / forecasting.FORECAST_FILENAME
            )

        self.stdout.write(self.style.SUCCESS("Dane scenariuszy są gotowe."))
