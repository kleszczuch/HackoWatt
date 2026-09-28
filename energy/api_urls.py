"""Trasy URL dla REST API aplikacji mobilnej (odczyt bez logowania)."""

from django.urls import path

from energy import api

urlpatterns = [
    # Inteligentny harmonogram i wskazówki dla domowników (seniorzy i młodzież)
    path("smart-schedule/today/", api.smart_schedule_today, name="api_smart_schedule_today"),
    path("devices/guidance/", api.devices_guidance, name="api_devices_guidance"),
    # Pulpit mobilny / bieżący status
    path("dashboard/summary/", api.dashboard_summary, name="api_dashboard_summary"),
    # Zużycie i prognoza
    path("consumption/history/", api.consumption_history, name="api_consumption_history"),
    path("consumption/forecast/", api.consumption_forecast, name="api_consumption_forecast"),
    # Taryfa godzinowa
    path("tariffs/", api.tariffs_info, name="api_tariffs_info"),
    # Fotowoltaika (PV)
    path("pv/simulate/", api.pv_simulate_api, name="api_pv_simulate"),
    path("pv/variants/", api.pv_variants_list, name="api_pv_variants"),
    # Urządzenia elastyczne i kalkulator przesunięcia
    path("devices/flexible-events/", api.flexible_events_list, name="api_flexible_events"),
    path("devices/shift-simulation/", api.shift_simulation, name="api_shift_simulation"),
    # Metadane i metryki systemu
    path("system/assumptions/", api.system_assumptions, name="api_system_assumptions"),
    path("system/metrics/", api.system_metrics, name="api_system_metrics"),
]
