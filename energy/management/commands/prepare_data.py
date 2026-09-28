"""Przygotowanie danych: pogoda Open-Meteo, symulacja wybranego scenariusza, prognoza."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from energy import forecasting, household, weather
from energy.scenarios import SCENARIOS
from decimal import Decimal

GENERATED_STAMP = "%Y-%m-%d %H:%M:%S"

SCENARIOS = {
    1: {
        "name": "Warszawa · Aleksandra",
        "city": "Warszawa, Polska",
        "lat": 52.2297,
        "lon": 21.0122,
        "folder": "scenario_1",
    },
    2: {
        "name": "Katowice · Marek i Ania",
        "city": "Katowice, Polska",
        "lat": 50.2649,
        "lon": 19.0238,
        "folder": "scenario_2",
    },
    3: {
        "name": "Barcelona · Anna i Robert",
        "city": "Barcelona, Hiszpania",
        "lat": 41.3879,
        "lon": 2.1699,
        "folder": "scenario_3",
    },
    4: {
        "name": "Kopenhaga · Dom Pokoleń",
        "city": "Kopenhaga, Dania",
        "lat": 55.6761,
        "lon": 12.5683,
        "folder": "scenario_4",
    },
    5: {
        "name": "Lizbona · Ola i Tomek",
        "city": "Lizbona, Portugalia",
        "lat": 38.7223,
        "lon": -9.1393,
        "folder": "scenario_5",
    },
}

class Command(BaseCommand):
    help = "Generuje 35 dni historii, prognozę 7 dni i roczny szacunek pod symulator PV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--scenario",
            type=int,
            default=4,
            choices=[1, 2, 3, 4, 5],
            help="Numer scenariusza (1-5). Domyślnie 4 (Kopenhaga).",
        )

    def _cached_weather(self, data_dir, fetch_error):
        self.stderr.write(self.style.WARNING(f"Brak pobierania ({fetch_error}); używam zapisanych CSV pogody."))
        try:
            return (
                weather.read_weather_csv(data_dir / weather.HISTORY_WEATHER_FILENAME),
                weather.read_weather_csv(data_dir / weather.FORECAST_WEATHER_FILENAME),
                weather.read_weather_csv(data_dir / weather.YEAR_WEATHER_FILENAME),
            )
        except (weather.WeatherFetchError, FileNotFoundError) as exc:
            raise CommandError("Nie udało się pobrać pogody, a brak plików w data/.") from exc

    def handle(self, *args, **options):
        base_data_dir = settings.BASE_DIR / "data"

        for scen_id, scen_info in SCENARIOS.items():
            self.stdout.write(self.style.SUCCESS(f"\n>>> Generuję dane dla: {scen_info['name']} ({scen_info['city']}) <<<"))
            
            # Tworzymy dedykowany folder np. data/scenario_1/, data/scenario_2/ itd.
            scen_dir = base_data_dir / scen_info["folder"]
            scen_dir.mkdir(parents=True, exist_ok=True)
            
            # Pobieramy POGODĘ DLA DANEGO MIASTA z Open-Meteo:
            now = weather.local_now()
            series = weather.fetch_weather_series()
            history_weather, forecast_weather = weather.split_history_forecast(series, now)
            year_weather = weather.fetch_year_weather(now)
            
            # Zapisujemy pliki pogody w folderze tego konkretnego scenariusza:
            weather.write_weather_csv(history_weather, scen_dir / weather.HISTORY_WEATHER_FILENAME)
            weather.write_weather_csv(forecast_weather, scen_dir / weather.FORECAST_WEATHER_FILENAME)
            weather.write_weather_csv(year_weather, scen_dir / weather.YEAR_WEATHER_FILENAME)
            
            # Generujemy zużycie i symulację dla tego scenariusza:
            consumption, events = household.simulate_household(history_weather, scenario_id=scen_id)
            annual, annual_events = household.simulate_household(year_weather, scenario_id=scen_id)

            # Mnożniki zużycia z regulaminu (1 os. Warszawa vs 4 os. Katowice vs Luksus Barcelona vs 6 os. Kopenhaga):
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
                    c.__class__(c.timestamp, tuple(round(v * mult, 3) for v in c.categories), c.events)
                    for c in consumption
                ]
                annual = [
                    c.__class__(c.timestamp, tuple(round(v * mult, 3) for v in c.categories), c.events)
                    for c in annual
                ]

            household.write_consumption_csv(consumption, scen_dir / household.HISTORY_FILENAME)
            household.write_events_csv(events, scen_dir / household.FLEX_EVENTS_FILENAME)
            household.write_consumption_csv(annual, scen_dir / household.ANNUAL_CONSUMPTION_FILENAME)
            household.write_events_csv(annual_events, scen_dir / household.ANNUAL_EVENTS_FILENAME)
            
            # Trenujemy XGBoost dla tego konkretnego miasta:
            backtest_rows, metrics = forecasting.backtest(consumption, history_weather)
            forecast_records = forecasting.forecast(consumption, history_weather, forecast_weather)
            
            forecasting.write_backtest_csv(backtest_rows, scen_dir / forecasting.BACKTEST_FILENAME)
            forecasting.write_metrics_json(metrics, scen_dir / forecasting.METRICS_FILENAME)
            household.write_consumption_csv(forecast_records, scen_dir / forecasting.FORECAST_FILENAME)

        self.stdout.write(self.style.SUCCESS("\nWSZYSTKIE 5 SCENARIUSZY WYGENEROWANE POMYŚLNIE!"))