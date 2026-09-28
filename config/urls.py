from django.urls import include, path

from energy.views import (
    assumptions,
    change_language,
    dashboard,
    export_csv,
    hourly_history,
    pv_simulator,
    switch_scenario_view,
)

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("godziny/", hourly_history, name="hourly_history"),
    path("symulator-pv/", pv_simulator, name="pv_simulator"),
    path("zalozenia/", assumptions, name="assumptions"),
    path("export.csv", export_csv, name="export_csv"),
    path("lang/<str:lang_code>/", change_language, name="change_language"),
    path("api/v1/", include("energy.api_urls")),
    path("switch-scenario/<int:scenario_id>/", switch_scenario_view, name="switch_scenario"),
]
