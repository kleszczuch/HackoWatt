from django.urls import path

from energy.views import assumptions, dashboard, export_csv, hourly_history, pv_simulator

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("godziny/", hourly_history, name="hourly_history"),
    path("symulator-pv/", pv_simulator, name="pv_simulator"),
    path("zalozenia/", assumptions, name="assumptions"),
    path("export.csv", export_csv, name="export_csv"),
]
