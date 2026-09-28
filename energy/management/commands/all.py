"""Polecenie Django uruchamiające cały cykl: uv sync, fetch_tariff_prices, prepare_data oraz runserver 0.0.0.0:8000."""

import shutil
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Wykonuje pełny rozruch systemu HackoWatt / EkoDzik: "
        "synchronizuje zależności (uv sync), pobiera ceny RCE (fetch_tariff_prices), "
        "generuje dane i symulacje scenariuszy (prepare_data) "
        "oraz uruchamia serwer deweloperski na 0.0.0.0:8000."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--addrport",
            default="0.0.0.0:8000",
            help="Adres i port dla serwera deweloperskiego (domyślnie: 0.0.0.0:8000).",
        )
        parser.add_argument(
            "--no-sync",
            action="store_true",
            help="Pomiń synchronizację zależności (uv sync).",
        )
        parser.add_argument(
            "--no-tariffs",
            action="store_true",
            help="Pomiń pobieranie cen RCE z PSE (fetch_tariff_prices).",
        )
        parser.add_argument(
            "--no-data",
            action="store_true",
            help="Pomiń generowanie danych scenariuszy (prepare_data).",
        )
        parser.add_argument(
            "--no-server",
            action="store_true",
            help="Wykonaj tylko kroki przygotowawcze i zakończ bez uruchamiania serwera.",
        )
        parser.add_argument(
            "--noreload",
            action="store_true",
            help="Uruchom serwer bez automatycznego przeładowywania kodu (--noreload).",
        )

    def handle(self, *args, **options):
        base_dir: Path = settings.BASE_DIR
        manage_py = base_dir / "manage.py"
        addrport = options["addrport"]

        self.stdout.write(
            self.style.SUCCESS(
                "\n"
                + "=" * 62
                + "\n  EkoDzik / HackoWatt: Kompleksowy rozruch (all)\n"
                + "=" * 62
            )
        )

        # Krok 1: uv sync
        if not options["no_sync"]:
            self.stdout.write(self.style.NOTICE("\n[1/4] Synchronizacja bibliotek (uv sync)..."))
            uv_path = shutil.which("uv") or "uv"
            try:
                subprocess.run([uv_path, "sync"], cwd=base_dir, check=True)
                self.stdout.write(self.style.SUCCESS("[OK] Zależności uv zsynchronizowane."))
            except FileNotFoundError:
                self.stderr.write(
                    self.style.WARNING("! Nie znaleziono 'uv' w PATH, pomijam synchronizację.")
                )
            except subprocess.CalledProcessError as exc:
                self.stderr.write(
                    self.style.WARNING(f"! Błąd podczas uv sync: {exc}. Kontynuuję...")
                )
        else:
            self.stdout.write("\n[1/4] Pomijam synchronizację uv (--no-sync).")

        # Krok 2: fetch_tariff_prices
        if not options["no_tariffs"]:
            self.stdout.write(
                self.style.NOTICE("\n[2/4] Pobieranie cen taryfowych RCE (fetch_tariff_prices)...")
            )
            try:
                call_command("fetch_tariff_prices", stdout=self.stdout, stderr=self.stderr)
                self.stdout.write(self.style.SUCCESS("[OK] Ceny taryfowe zaktualizowane."))
            except Exception as exc:
                self.stderr.write(
                    self.style.WARNING(f"! Ostrzeżenie przy fetch_tariff_prices: {exc}")
                )
        else:
            self.stdout.write("\n[2/4] Pomijam pobieranie cen taryfowych (--no-tariffs).")

        # Krok 3: prepare_data
        if not options["no_data"]:
            self.stdout.write(
                self.style.NOTICE("\n[3/4] Przygotowanie danych scenariuszy (prepare_data)...")
            )
            try:
                call_command("prepare_data", stdout=self.stdout, stderr=self.stderr)
                self.stdout.write(self.style.SUCCESS("[OK] Dane i symulacje scenariuszy gotowe."))
            except Exception as exc:
                self.stderr.write(self.style.WARNING(f"! Ostrzeżenie przy prepare_data: {exc}"))
        else:
            self.stdout.write("\n[3/4] Pomijam przygotowanie danych (--no-data).")

        # Krok 4: runserver 0.0.0.0:8000
        if not options["no_server"]:
            self.stdout.write(
                self.style.NOTICE(f"\n[4/4] Start serwera Django na {addrport} (runserver)...")
            )
            cmd = [sys.executable, str(manage_py), "runserver", addrport]
            if options.get("noreload"):
                cmd.append("--noreload")
            try:
                subprocess.run(cmd, cwd=base_dir)
            except KeyboardInterrupt:
                self.stdout.write(self.style.SUCCESS("\nZatrzymano serwer."))
        else:
            self.stdout.write(
                self.style.SUCCESS("\n[OK] Zakończono pomyślnie. Serwer nie został uruchomiony (--no-server).")
            )
