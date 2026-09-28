from django.urls import path

from energy.views import dashboard, export_csv

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("export.csv", export_csv, name="export_csv"),
]
