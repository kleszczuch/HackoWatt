"""Pełny lokalny rozruch: zależności, dane, rekomendacje i serwer Django."""

import shutil
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Wykonuje pełny rozruch systemu HackoWatt / EkoDzik: "
        "synchronizuje zależności (uv sync), pobiera ceny RCE (fetch_tariff_prices), "
        "generuje dane i symulacje scenariuszy (prepare_data), liczy rekomendacje "
        "pracy urządzeń (prepare_recommendations) "
        "oraz uruchamia lokalny serwer deweloperski."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--addrport",
            default="localhost:8000",
            help="Adres i port dla serwera deweloperskiego (domyślnie: localhost:8000).",
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
            "--no-recommendations",
            action="store_true",
            help="Pomiń liczenie rekomendacji pracy urządzeń (prepare_recommendations).",
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
                "\n" + "=" * 62 + "\n  EkoDzik / HackoWatt: Kompleksowy rozruch (all)\n" + "=" * 62
            )
        )

        # Krok 1: uv sync
        if not options["no_sync"]:
            self.stdout.write(self.style.NOTICE("\n[1/5] Synchronizacja bibliotek (uv sync)..."))
            uv_path = shutil.which("uv") or "uv"
            try:
                subprocess.run([uv_path, "sync"], cwd=base_dir, check=True)
                self.stdout.write(self.style.SUCCESS("[OK] Zależności uv zsynchronizowane."))
            except FileNotFoundError:
                raise CommandError("Nie znaleziono 'uv' w PATH.") from None
            except subprocess.CalledProcessError as exc:
                raise CommandError(f"Synchronizacja uv nie powiodła się: {exc}.") from exc
        else:
            self.stdout.write("\n[1/5] Pomijam synchronizację uv (--no-sync).")

        # Krok 2: fetch_tariff_prices
        if not options["no_tariffs"]:
            self.stdout.write(
                self.style.NOTICE("\n[2/5] Pobieranie cen taryfowych RCE (fetch_tariff_prices)...")
            )
            try:
                call_command("fetch_tariff_prices", stdout=self.stdout, stderr=self.stderr)
                self.stdout.write(
                    self.style.SUCCESS("[OK] Sprawdzono ceny RCE; brakujące godziny użyją taryfy stałej.")
                )
            except Exception as exc:
                self.stderr.write(
                    self.style.WARNING(f"! Ostrzeżenie przy fetch_tariff_prices: {exc}")
                )
        else:
            self.stdout.write("\n[2/5] Pomijam pobieranie cen taryfowych (--no-tariffs).")

        # Dane i rekomendacje są wymagane: serwer z niekompletnym planem nie
        # powinien być ogłaszany jako gotowe demo. Ceny RCE mają jawny fallback.
        # Krok 3: prepare_data
        if not options["no_data"]:
            self.stdout.write(
                self.style.NOTICE("\n[3/5] Przygotowanie danych scenariuszy (prepare_data)...")
            )
            try:
                call_command("prepare_data", stdout=self.stdout, stderr=self.stderr)
                self.stdout.write(self.style.SUCCESS("[OK] Dane i symulacje scenariuszy gotowe."))
            except Exception as exc:
                raise CommandError(f"Przygotowanie danych nie powiodło się: {exc}") from exc
        else:
            self.stdout.write("\n[3/5] Pomijam przygotowanie danych (--no-data).")

        # Krok 4: prepare_recommendations
        if not options["no_recommendations"]:
            self.stdout.write(
                self.style.NOTICE(
                    "\n[4/5] Liczenie rekomendacji pracy urządzeń (prepare_recommendations)..."
                )
            )
            try:
                call_command("prepare_recommendations", stdout=self.stdout, stderr=self.stderr)
                self.stdout.write(self.style.SUCCESS("[OK] Rekomendacje urządzeń gotowe."))
            except Exception as exc:
                raise CommandError(f"Przygotowanie rekomendacji nie powiodło się: {exc}") from exc
        else:
            self.stdout.write("\n[4/5] Pomijam rekomendacje urządzeń (--no-recommendations).")

        # Krok 5: lokalny runserver
        if not options["no_server"]:
            self.stdout.write(
                self.style.NOTICE(f"\n[5/5] Start serwera Django na {addrport} (runserver)...")
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
                self.style.SUCCESS(
                    "\n[OK] Zakończono pomyślnie. Serwer nie został uruchomiony (--no-server)."
                )
            )
