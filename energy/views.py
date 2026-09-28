"""Widoki: pulpit scenariusza, symulator PV, założenia i eksport CSV."""

import csv
from decimal import Decimal

from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from energy import data, pv
from energy.charts import (
    CATEGORY_LABELS,
    build_backtest_chart,
    build_forecast_chart,
    build_history_chart,
    build_pv_chart,
)
from energy.explanations import explain_peaks
from energy.forms import DateRangeForm, HorizonForm, PvForm
from energy.household import CATEGORIES
from energy.tariffs import CURRENCY

PLOTLY_CONFIG = {"responsive": True, "scrollZoom": True}


def _chart_html(figure, include_plotlyjs: bool = False) -> str:
    return figure.to_html(full_html=False, include_plotlyjs=include_plotlyjs, config=PLOTLY_CONFIG)


def _date_range(request: HttpRequest, history):
    if request.GET.get("start") or request.GET.get("end"):
        form = DateRangeForm(request.GET)
    else:
        start, end = data.default_dates(history)
        form = DateRangeForm({"start": start.isoformat(), "end": end.isoformat()})
    return form


def _horizon(request: HttpRequest) -> tuple[HorizonForm, int]:
    form = HorizonForm({"horyzont": request.GET.get("horyzont", "24")})
    if form.is_valid():
        return form, int(form.cleaned_data["horyzont"])
    return HorizonForm({"horyzont": "24"}), 24


def dashboard(request: HttpRequest) -> HttpResponse:
    try:
        history = data.load_history()
        forecast = data.load_forecast()
        weather_history = data.load_weather_history()
        weather_forecast = data.load_weather_forecast()
        backtest_rows = data.load_backtest()
        metrics = data.load_metrics()
    except (FileNotFoundError, data.DemoDataError) as exc:
        return render(request, "energy/dashboard.html", {"data_error": str(exc)})

    form = _date_range(request, history)
    horizon_form, horizon_hours = _horizon(request)
    forecast_slice = forecast[:horizon_hours]
    weather_by_timestamp = {record.timestamp: record for record in weather_forecast}
    weather_forecast_slice = [
        weather_by_timestamp[record.timestamp]
        for record in forecast_slice
        if record.timestamp in weather_by_timestamp
    ]

    context = {
        "form": form,
        "horizon_form": horizon_form,
        "category_labels": CATEGORY_LABELS,
        "metrics": metrics,
        "horizon_hours": horizon_hours,
        "backtest_chart": _chart_html(build_backtest_chart(backtest_rows)),
    }

    if form.is_valid():
        start = form.cleaned_data["start"]
        end = form.cleaned_data["end"]
        selected_history = data.filter_records(history, start, end)
        selected_weather = data.filter_records(weather_history, start, end)
        page = Paginator(selected_history, 48).get_page(request.GET.get("page"))
        context.update(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "page": page,
                "selected_count": len(selected_history),
                "selected_total": sum((record.total for record in selected_history), Decimal(0)),
                "history_chart": _chart_html(
                    build_history_chart(selected_history, selected_weather), include_plotlyjs=True
                ),
            }
        )

    forecast_total = sum((record.total for record in forecast_slice), Decimal(0))
    context.update(
        {
            "forecast_total": forecast_total,
            "forecast_chart": _chart_html(
                build_forecast_chart(forecast_slice, weather_forecast_slice)
            ),
            "peaks": explain_peaks(forecast_slice, weather_forecast_slice),
        }
    )
    return render(request, "energy/dashboard.html", context)


def pv_simulator(request: HttpRequest) -> HttpResponse:
    try:
        records, weather, events = data.load_annual()
    except (FileNotFoundError, data.DemoDataError) as exc:
        return render(request, "energy/pv.html", {"data_error": str(exc)})

    form = PvForm(request.GET) if request.GET else PvForm({"kwp": "5", "miesiac": "6"})
    context = {"form": form, "currency": CURRENCY}
    if not form.is_valid():
        return render(request, "energy/pv.html", context)

    kwp = form.cleaned_data["kwp"]
    month = int(form.cleaned_data["miesiac"])
    comparison = pv.compare_variants(records, weather, events)
    selected = next(
        (result for result in comparison if result.kwp == kwp),
        pv.simulate(records, weather, events, kwp),
    )
    effects = pv.device_effects(records, weather, events, kwp)
    week = pv.representative_week(records, weather, events, kwp, month)
    context.update(
        {
            "kwp": kwp,
            "comparison": comparison,
            "selected": selected,
            "effects": effects,
            "pv_chart": _chart_html(build_pv_chart(week, kwp), include_plotlyjs=True),
            "consumption_kwh": selected.consumption_kwh,
        }
    )
    return render(request, "energy/pv.html", context)


def assumptions(request: HttpRequest) -> HttpResponse:
    context: dict = {"currency": CURRENCY}
    try:
        history = data.load_history()
        forecast = data.load_forecast()
        records, weather, _ = data.load_annual()
        context["metrics"] = data.load_metrics()
        context["spans"] = {
            "history": (history[0].timestamp, history[-1].timestamp, len(history)),
            "forecast": (forecast[0].timestamp, forecast[-1].timestamp, len(forecast)),
            "annual": (records[0].timestamp, records[-1].timestamp, len(records)),
            "weather_annual": (weather[0].timestamp, weather[-1].timestamp, len(weather)),
        }
    except (FileNotFoundError, data.DemoDataError) as exc:
        context["data_error"] = str(exc)
    return render(request, "energy/zalozenia.html", context)


def export_csv(request: HttpRequest) -> HttpResponse:
    try:
        history = data.load_history()
        forecast = data.load_forecast()
    except (FileNotFoundError, data.DemoDataError) as exc:
        return HttpResponse(str(exc), status=400)

    form = _date_range(request, history)
    if not form.is_valid():
        return HttpResponse("Niepoprawny zakres dat.", status=400)

    start = form.cleaned_data["start"]
    end = form.cleaned_data["end"]
    selected = sorted(
        [("Symulacja", record) for record in data.filter_records(history, start, end)]
        + [("Prognoza", record) for record in data.filter_records(forecast, start, end)],
        key=lambda item: item[1].timestamp,
    )
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="hackowatt_dane.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["Data_Czas", "Typ_danych", *CATEGORIES, "Calkowite_Zuzycie_kWh", "Zdarzenia"])
    for kind, record in selected:
        writer.writerow(
            [
                record.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                kind,
                *[f"{value:.3f}" for value in record.categories],
                f"{record.total:.3f}",
                record.events,
            ]
        )
    return response
