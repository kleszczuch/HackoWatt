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
    build_history_chart,
    build_overview_chart,
    build_pv_chart,
)
from energy.explanations import explain_peaks
from energy.forms import DateRangeForm, HorizonForm, PvForm
from energy.household import CATEGORIES
from energy.tariffs import CURRENCY

PLOTLY_CONFIG = {
    "responsive": True,
    "scrollZoom": False,
    "doubleClick": False,
    "displayModeBar": False,
}
SIMULATION_DAYS = (1, 3, 5, 7, 14, 31)
PV_DEFAULTS = {
    "kwp": "5",
    "miesiac": "6",
    "magazyn_kwh": "0",
    "magazyn_moc_kw": "5",
    "magazyn_koszt_eur": "0",
}


def _chart_html(figure, include_plotlyjs=False):
    return figure.to_html(
        full_html=False,
        include_plotlyjs=include_plotlyjs,
        config={"scrollZoom": True}
    )


def _date_range(request: HttpRequest, history):
    if request.GET.get("start") or request.GET.get("end"):
        form = DateRangeForm(request.GET)
    else:
        start, end = data.default_dates(history)
        form = DateRangeForm({"start": start.isoformat(), "end": end.isoformat()})
    return form


def _horizon(request: HttpRequest) -> int:
    form = HorizonForm({"horyzont": request.GET.get("horyzont", "24")})
    if form.is_valid():
        return int(form.cleaned_data["horyzont"])
    return 24


def _simulation_days(request: HttpRequest) -> int:
    try:
        days = int(request.GET.get("dni", "7"))
    except TypeError, ValueError:
        return 7
    return days if days in SIMULATION_DAYS else 7


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

    days = _simulation_days(request)
    selected_history = history[-days * 24 :]
    selected_weather = data.filter_records(
        weather_history,
        selected_history[0].timestamp.date(),
        selected_history[-1].timestamp.date(),
    )
    selected_timestamps = {record.timestamp for record in selected_history}
    selected_weather = [
        record for record in selected_weather if record.timestamp in selected_timestamps
    ]
    horizon_hours = _horizon(request)
    forecast_slice = forecast[:horizon_hours]
    weather_by_timestamp = {record.timestamp: record for record in weather_forecast}
    weather_forecast_slice = [
        weather_by_timestamp[record.timestamp]
        for record in forecast_slice
        if record.timestamp in weather_by_timestamp
    ]

    context = {
        "simulation_days": days,
        "simulation_options": SIMULATION_DAYS,
        "metrics": metrics,
        "horizon_hours": horizon_hours,
        "forecast_options": ((24, "24 h"), (72, "3 dni"), (168, "7 dni")),
        "start": selected_history[0].timestamp.date().isoformat(),
        "end": selected_history[-1].timestamp.date().isoformat(),
        "selected_count": len(selected_history),
        "selected_total": sum((record.total for record in selected_history), Decimal(0)),
        "history_chart": _chart_html(
            build_overview_chart(selected_history, selected_weather), include_plotlyjs=True
        ),
        "backtest_chart": _chart_html(build_backtest_chart(backtest_rows)),
    }
    forecast_total = sum((record.total for record in forecast_slice), Decimal(0))
    context.update(
        {
            "forecast_total": forecast_total,
            "forecast_chart": _chart_html(
                build_overview_chart(forecast_slice, weather_forecast_slice, forecast=True)
            ),
            "peaks": explain_peaks(forecast_slice, weather_forecast_slice),
        }
    )
    return render(request, "energy/dashboard.html", context)


def hourly_history(request: HttpRequest) -> HttpResponse:
    try:
        history = data.load_history()
        weather_history = data.load_weather_history()
    except (FileNotFoundError, data.DemoDataError) as exc:
        return render(request, "energy/hourly.html", {"data_error": str(exc)})

    rolling_days = (
        _simulation_days(request)
        if request.GET.get("dni") and not (request.GET.get("start") or request.GET.get("end"))
        else None
    )
    if rolling_days:
        selected = history[-rolling_days * 24 :]
        form = DateRangeForm(
            {
                "start": selected[0].timestamp.date().isoformat(),
                "end": selected[-1].timestamp.date().isoformat(),
            }
        )
    else:
        form = _date_range(request, history)
    context = {"form": form, "category_labels": CATEGORY_LABELS, "rolling_days": rolling_days}
    if form.is_valid():
        start = form.cleaned_data["start"]
        end = form.cleaned_data["end"]
        selected_history = selected if rolling_days else data.filter_records(history, start, end)
        selected_weather = data.filter_records(weather_history, start, end)
        if rolling_days:
            selected_timestamps = {record.timestamp for record in selected_history}
            selected_weather = [
                record for record in selected_weather if record.timestamp in selected_timestamps
            ]
        context.update(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "page": Paginator(selected_history, 48).get_page(request.GET.get("page")),
                "selected_count": len(selected_history),
                "selected_total": sum((record.total for record in selected_history), Decimal(0)),
                "history_chart": _chart_html(
                    build_history_chart(selected_history, selected_weather), include_plotlyjs=True
                ),
            }
        )
    return render(request, "energy/hourly.html", context)

def get_behavioral_advice(device_name, moved_kwh):
    if moved_kwh <= 0:
        return {
            "headline": "Jest dobrze!",
            "action": "Urządzenie już teraz pracuje w godzinach najwyższej produkcji słonecznej.",
            "comfort": "Nic nie zmieniaj - Wasze obecne nawyki są wzorowe."
        }
        
    device_lower = str(device_name).lower()
    
    if "zmywarka" in device_lower or "duze" in device_lower:
        return {
            "headline": "Opóźniony start",
            "action": "Zamiast czekać do wieczora, można załadować zmywarkę po obiedzie i używać funkcji opóźnionego startu celując w okolice 13:00.",
            "comfort": "Zmywarka pracuje bezgłośnie, gdy jesteście poza domem. Wieczorem macie puste zlewy - zero stresu!"
        }
    elif "pralka" in device_lower:
        return {
            "headline": "Darmowe pranie",
            "action": "Skoro dziadkowie lub osoby na Home Office są rano w domu, nastawiajcie pranie w okolicach 10:00 - 12:00.",
            "comfort": "Pralka skończy cykl w dzień, co ułatwi szybkie suszenie ubrań na świeżym powietrzu."
        }
    elif "suszarka" in device_lower:
        return {
            "headline": "Wykorzystaj ciepło dnia",
            "action": "Należy unikać uruchamiania suszarki w nocy. Najlepsze okno to wczesne popołudnie.",
            "comfort": "Suszarka generuje ciepło. Uruchomienie jej w dzień, gdy miej osób jest w domu, zmniejszy wieczorny zaduch."
        }
    else:
        return {
            "headline": "Drobna zmiana, duży efekt",
            "action": "Spróbujcie przenieść pracę tego urządzenia na godziny wczesnopopołudniowe.",
            "comfort": "Każde zasilenie urządzenia w dzień to mniejszy rachunek i więcej oszczędności."
        }

def pv_simulator(request: HttpRequest) -> HttpResponse:
    try:
        records, weather, events = data.load_annual()
    except (FileNotFoundError, data.DemoDataError) as exc:
        return render(request, "energy/pv.html", {"data_error": str(exc)})

    goal = request.GET.get("cel")
    parameters = {**PV_DEFAULTS, **request.GET.dict()}
    if goal in {"coverage", "payback"}:
        parameters["kwp"] = "5"
    form = PvForm(parameters)
    context = {"form": form, "currency": CURRENCY}
    if not form.is_valid():
        return render(request, "energy/pv.html", context)

    kwp = form.cleaned_data["kwp"]
    month = int(form.cleaned_data["miesiac"])
    storage = pv.StorageConfig(
        form.cleaned_data["magazyn_kwh"],
        form.cleaned_data["magazyn_moc_kw"],
        form.cleaned_data["magazyn_koszt_eur"],
    )
    if goal in {"coverage", "payback"}:
        choice = pv.choose_capacity(records, weather, events, goal, storage)
        context.update({"auto_goal": goal, "capacity_choice": choice})
        if choice.kwp is not None:
            kwp = choice.kwp
            parameters["kwp"] = str(kwp)
            form = PvForm(parameters)
            context["form"] = form
    comparison = pv.compare_variants(records, weather, events, storage=storage)
    selected = next((result for result in comparison if result.kwp == kwp), None)
    if selected is None:
        selected = pv.simulate(records, weather, events, kwp, storage)

    selected = pv.simulate(records, weather, events, kwp, storage)

    # 1. Pobieramy oryginalne efekty (zamrożone)
    oryginalne_efekty = pv.device_effects(records, weather, events, kwp, storage)

    # 2. Przepisujemy je do nowej, "odmrożonej" listy
    effects = []
    for effect in oryginalne_efekty:
        # Pobieramy poradę (tu używamy kropek, bo czytamy z zamrożonego obiektu)
        porada = get_behavioral_advice(effect.device, effect.moved_kwh)
        
        # Tworzymy nowy, elastyczny słownik ze starymi danymi + naszą poradą!
        effects.append({
            "device": effect.device,
            "moved_kwh": effect.moved_kwh,
            "grid_saved_kwh": effect.grid_saved_kwh,
            "money_saved": effect.money_saved,
            "advice": porada
        })
    week = pv.representative_week(records, weather, events, kwp, month, storage)
    max_production = sum(
        (pv.pv_production(hour.radiation, pv.MAX_KWP) for hour in weather), Decimal(0)
    )
    day_count = len({record.timestamp.date() for record in records})
    context.update(
        {
            "kwp": kwp,
            "storage": storage,
            "battery_enabled": storage.capacity_kwh > 0,
            "comparison": comparison,
            "selected": selected,
            "effects": effects,
            "pv_chart": _chart_html(build_pv_chart(week, kwp), include_plotlyjs=True),
            "consumption_kwh": selected.consumption_kwh,
            "daily_average_kwh": selected.consumption_kwh / Decimal(day_count),
            "week_days": pv.daily_week_summary(week),
            "annual_energy_shortfall": max_production < selected.consumption_kwh,
            "max_production_kwh": max_production,
            "max_kwp": pv.MAX_KWP,
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

    if request.GET.get("dni") and not (request.GET.get("start") or request.GET.get("end")):
        days = _simulation_days(request)
        selected = [("Symulacja", record) for record in history[-days * 24 :]]
    else:
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
