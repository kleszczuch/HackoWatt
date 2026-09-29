"""Liczy rekomendacje pracy urządzeń na jutro dla scenariuszy i zapisuje bufor."""

from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from energy import tariffs
from energy.pv import DEFAULT_STORAGE
from energy.scenarios import SCENARIOS
from energy.views import PV_DEFAULTS
from models import recommendations


class Command(BaseCommand):
    help = (
        "Przygotowuje plan pracy urządzeń na jutro dla pięciu scenariuszy "
        "i domyślnych ustawień (taryfa stała, domyślna moc PV, bez magazynu). "
        "Wyniki trafiają do bufora data/recommendations/; bez Ollamy działa "
        "wyliczony wariant zastępczy (calculated_fallback)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--scenario", type=int, choices=SCENARIOS)

    def handle(self, *args, **options):
        base_data_dir = settings.DEMO_DATA_DIR
        cache_dir = base_data_dir / recommendations.CACHE_DIRNAME
        scenario_ids = [options["scenario"]] if options["scenario"] else list(SCENARIOS)
        missing_scenarios = []
        for scen_id in scenario_ids:
            scen = SCENARIOS[scen_id]
            data_dir = base_data_dir / scen["folder"]
            plan = recommendations.build_plan(
                scenario_id=scen["folder"],
                data_dir=data_dir,
                tariff=tariffs.TariffConfig(),
                dynamic=None,
                kwp=Decimal(PV_DEFAULTS["kwp"]),
                storage=DEFAULT_STORAGE,
                lang="pl",
                cache_dir=cache_dir,
            )
            if plan["status"] != "ready":
                missing_scenarios.append(scen["name"])
                self.stdout.write(
                    self.style.WARNING(
                        f"{scen['name']}: brak danych na jutro (status: {plan['status']}) — "
                        "pomijam zapis bufora."
                    )
                )
                continue
            planned = sum(
                1
                for item in plan["recommendations"]
                if item.get("status") not in ("no_cycle", "keep")
            )
            kept = sum(1 for item in plan["recommendations"] if item.get("status") == "keep")
            no_cycle = sum(
                1 for item in plan["recommendations"] if item.get("status") == "no_cycle"
            )
            cache_file = max(
                cache_dir.glob(f"{scen['folder']}_{plan['date']}_*.json"),
                key=lambda path: path.stat().st_mtime_ns,
                default=None,
            )
            source_note = ""
            if plan["source"] == "calculated_fallback":
                if plan.get("fallback_cause") == "invalid_response":
                    source_note = " (odpowiedź modelu odrzucona — wyliczony wariant zastępczy)"
                elif plan.get("fallback_cause") == "ollama_unavailable":
                    source_note = " (Ollama niedostępna — wyliczony wariant zastępczy)"
                else:
                    source_note = " (brak opłacalnej zmiany godziny)"
            self.stdout.write(
                self.style.SUCCESS(
                    f"{scen['name']}: {plan['status']}, {planned} rekomendacji, "
                    f"{kept} pozostawionych, {no_cycle} bez cyklu, dzień {plan['date']}, "
                    f"bufor: {cache_file}{source_note}"
                )
            )
        if missing_scenarios:
            raise CommandError(
                "Nie przygotowano rekomendacji dla: " + ", ".join(missing_scenarios)
            )
        self.stdout.write(self.style.SUCCESS("Rekomendacje są gotowe."))
