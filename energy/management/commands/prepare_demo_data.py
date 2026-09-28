"""Przygotowanie syntetycznej historii i prognozy przed uruchomieniem strony."""

from django.conf import settings
from django.core.management.base import BaseCommand

from chart_generator import FORECAST_FILENAME, generate_forecast
from generuj_zuzycie import HISTORY_FILENAME, generate_consumption


class Command(BaseCommand):
    help = "Generuje dane demo 2026 i 90-dniową prognozę XGBoost."

    def handle(self, *args, **options):
        data_dir = settings.DEMO_DATA_DIR
        data_dir.mkdir(parents=True, exist_ok=True)
        history_path = data_dir / HISTORY_FILENAME
        forecast_path = data_dir / FORECAST_FILENAME

        history = generate_consumption(history_path)
        self.stdout.write(f"Historia: {len(history)} godzin: {history_path}")
        forecast = generate_forecast(history_path, forecast_path)
        self.stdout.write(f"Prognoza: {len(forecast)} godzin: {forecast_path}")
        self.stdout.write(self.style.SUCCESS("Dane demonstracyjne są gotowe."))
