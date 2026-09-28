"""Widok lokalnego dashboardu i eksportu danych godzinowych."""

import csv
from decimal import Decimal

from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import render

from energy.charts import build_details, build_overview
from energy.data import DemoDataError, default_dates, filter_records, load_demo_data
from energy.forms import DateRangeForm
from generuj_zuzycie import CATEGORIES


def _selection(request: HttpRequest, history, forecast):
    if request.GET.get("start") or request.GET.get("end"):
        form = DateRangeForm(request.GET)
    else:
        start, end = default_dates(history, forecast)
        form = DateRangeForm({"start": start.isoformat(), "end": end.isoformat()})
    if not form.is_valid():
        return form, [], []
    start = form.cleaned_data["start"]
    end = form.cleaned_data["end"]
    return form, filter_records(history, start, end), filter_records(forecast, start, end)


def dashboard(request: HttpRequest) -> HttpResponse:
    try:
        history, forecast = load_demo_data()
    except (FileNotFoundError, DemoDataError) as exc:
        return render(request, "energy/dashboard.html", {"data_error": str(exc)})

    form, selected_history, selected_forecast = _selection(request, history, forecast)
    selected = sorted(selected_history + selected_forecast, key=lambda record: record.timestamp)
    page = Paginator(selected, 48).get_page(request.GET.get("page"))
    selected_total = sum((record.total_decimal for record in selected), Decimal(0))
    selected_history_total = sum((record.total_decimal for record in selected_history), Decimal(0))
    selected_forecast_total = sum(
        (record.total_decimal for record in selected_forecast), Decimal(0)
    )

    context = {
        "form": form,
        "page": page,
        "selected_count": len(selected),
        "selected_total": selected_total,
        "selected_history_total": selected_history_total,
        "selected_forecast_total": selected_forecast_total,
        "history_count": len(history),
        "forecast_count": len(forecast),
        "category_labels": (
            "Baza",
            "Ogrzewanie",
            "Oświetlenie",
            "Gotowanie",
            "RTV / PC",
            "Duże AGD",
        ),
    }
    if form.is_valid():
        context["start"] = form.cleaned_data["start"].isoformat()
        context["end"] = form.cleaned_data["end"].isoformat()
        context["overview_chart"] = build_overview(history, forecast).to_html(
            full_html=False, include_plotlyjs=True, config={"responsive": True, "scrollZoom": True}
        )
        if selected:
            context["detail_chart"] = build_details(selected_history, selected_forecast).to_html(
                full_html=False,
                include_plotlyjs=False,
                config={"responsive": True, "scrollZoom": True},
            )
    return render(request, "energy/dashboard.html", context)


def export_csv(request: HttpRequest) -> HttpResponse:
    try:
        history, forecast = load_demo_data()
    except (FileNotFoundError, DemoDataError) as exc:
        return HttpResponseBadRequest(str(exc))

    form, selected_history, selected_forecast = _selection(request, history, forecast)
    if not form.is_valid():
        return HttpResponseBadRequest("Niepoprawny zakres dat.")

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="hackowatt_dane.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["Data_Czas", "Typ_danych", *CATEGORIES, "Calkowite_Zuzycie_kWh"])
    selected = sorted(selected_history + selected_forecast, key=lambda record: record.timestamp)
    for record in selected:
        writer.writerow(
            [
                record.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                record.kind,
                *record.categories,
                record.total,
            ]
        )
    return response
