"""Przygotowanie danych scenariusza 4: pogoda Open-Meteo, symulacja, prognoza."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from energy import forecasting, household, weather

GENERATED_STAMP = "%Y-%m-%d %H:%M:%S"


class Command(BaseCommand):
    help = (
        "Pobiera rzeczywistą pogodę z Open-Meteo (Kopenhaga), generuje 35 dni historii "
        "zużycia, ocenę błędu, prognozę 7 dni i roczny szacunek pod symulator PV."
    )

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
            raise CommandError(
                "Nie udało się pobrać pogody, a brak zapisanych plików pogody w data/."
            ) from exc

    def handle(self, *args, **options):
        data_dir = settings.DEMO_DATA_DIR
        data_dir.mkdir(parents=True, exist_ok=True)

        try:
            now = weather.local_now()
            series = weather.fetch_weather_series()
            history_weather, forecast_weather = weather.split_history_forecast(series, now)
            year_weather = weather.fetch_year_weather(now)
            weather.write_weather_csv(history_weather, data_dir / weather.HISTORY_WEATHER_FILENAME)
            weather.write_weather_csv(
                forecast_weather, data_dir / weather.FORECAST_WEATHER_FILENAME
            )
            weather.write_weather_csv(year_weather, data_dir / weather.YEAR_WEATHER_FILENAME)
            self.stdout.write(
                f"Pogoda: {len(history_weather)} h historii, {len(forecast_weather)} h prognozy, "
                f"{len(year_weather)} h roku z Open-Meteo ({weather.LOCATION_LABEL})."
            )
        except weather.WeatherFetchError as exc:
            history_weather, forecast_weather, year_weather = self._cached_weather(data_dir, exc)

        consumption, events = household.simulate_household(history_weather)
        household.write_consumption_csv(consumption, data_dir / household.HISTORY_FILENAME)
        household.write_events_csv(events, data_dir / household.FLEX_EVENTS_FILENAME)
        self.stdout.write(f"Historia: {len(consumption)} h, zdarzeń elastycznych: {len(events)}.")

        annual, annual_events = household.simulate_household(year_weather)
        household.write_consumption_csv(annual, data_dir / household.ANNUAL_CONSUMPTION_FILENAME)
        household.write_events_csv(annual_events, data_dir / household.ANNUAL_EVENTS_FILENAME)
        self.stdout.write(f"Szacunek roczny: {len(annual)} h.")

        backtest_rows, metrics = forecasting.backtest(consumption, history_weather)
        forecast_records = forecasting.forecast(consumption, history_weather, forecast_weather)
        metrics["wygenerowano"] = weather.local_now().strftime(GENERATED_STAMP)
        forecasting.write_backtest_csv(backtest_rows, data_dir / forecasting.BACKTEST_FILENAME)
        forecasting.write_metrics_json(metrics, data_dir / forecasting.METRICS_FILENAME)
        household.write_consumption_csv(forecast_records, data_dir / forecasting.FORECAST_FILENAME)
        self.stdout.write(
            f"Prognoza: {len(forecast_records)} h; MAE model {metrics['mae_model']:.4f} kWh "
            f"(MAPE {metrics['mape_model']:.2f}%), baseline {metrics['mae_baseline']:.4f} kWh "
            f"(MAPE {metrics['mape_baseline']:.2f}%)."
        )
        self.stdout.write(self.style.SUCCESS("Dane demonstracyjne są gotowe."))
