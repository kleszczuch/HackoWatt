from django.urls import path

from energy.views import assumptions, dashboard, export_csv, pv_simulator

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("symulator-pv/", pv_simulator, name="pv_simulator"),
    path("zalozenia/", assumptions, name="assumptions"),
    path("export.csv", export_csv, name="export_csv"),
]
