"""Pobiera ceny RCE z PSE dla roku modelowego i najbliższych dni."""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from energy import pse, tariffs, weather


class Command(BaseCommand):
    help = (
        "Pobiera godzinowe ceny RCE z API PSE (rok modelowy i nadchodzące dni) "
        "i zapisuje je w data/tariff_prices.json."
    )

    def handle(self, *args, **options):
        data_dir = settings.DEMO_DATA_DIR
        now = weather.local_now("Europe/Warsaw")
        end = now.date() + timedelta(days=2)
        start = end - timedelta(days=weather.YEAR_DAYS + weather.ARCHIVE_DELAY_DAYS + 2)
        try:
            rows = pse.fetch_rce(start, end)
        except pse.PseFetchError as exc:
            if (data_dir / pse.PRICES_FILENAME).exists():
                self.stderr.write(
                    self.style.WARNING(f"Brak pobierania ({exc}); zostawiam zapisane ceny.")
                )
                return
            raise CommandError(
                f"Nie udało się pobrać cen RCE i brak zapisanego pliku: {exc}"
            ) from exc
        prices = pse.hourly_prices_eur(rows, tariffs.EURPLN_RATE)
        pse.write_prices_json(prices, data_dir / pse.PRICES_FILENAME)
        first, last = min(prices), max(prices)
        self.stdout.write(
            self.style.SUCCESS(
                f"Ceny RCE: {len(prices)} h ({first:%Y-%m-%d %H:%M} – {last:%Y-%m-%d %H:%M})."
            )
        )
