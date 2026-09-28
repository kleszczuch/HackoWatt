"""Widoki: pulpit scenariusza, symulator PV, założenia i eksport CSV.

Plik obsługuje widoki aplikacji Django.

Głównym zadaniem modułu jest renderowanie stron interfejsu użytkownika
oraz przygotowywanie danych dla dashboardu, historii godzinowej i symulatora PV."""

import csv
from decimal import Decimal
from html import escape
from uuid import uuid4

from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.utils.http import url_has_allowed_host_and_scheme

from energy import data, pv
from energy.charts import (
    CATEGORY_LABELS_EN,
    CATEGORY_LABELS_PL,
    build_backtest_chart,
    build_history_chart,
    build_overview_chart,
    build_pv_chart,
)
from energy.explanations import explain_peaks
from energy.forms import DateRangeForm, HorizonForm, PvForm
from energy.presentation import device_name, event_names
from energy.scenarios import SCENARIOS, get_active_scenario, get_scenario_data_dir
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


def switch_scenario_view(request: HttpRequest, scenario_id: int) -> HttpResponse:
    if scenario_id in SCENARIOS:
        request.session["active_scenario"] = scenario_id
    next_url = request.META.get("HTTP_REFERER", "/")
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = "/"
    return HttpResponseRedirect(next_url)


def _current_lang(request: HttpRequest) -> str:
    lang = request.session.get("django_language") or request.COOKIES.get("django_language") or "pl"
    return lang if lang in ("pl", "en") else "pl"


def change_language(request: HttpRequest, lang_code: str) -> HttpResponse:
    if lang_code not in ("pl", "en"):
        lang_code = "pl"
    request.session["django_language"] = lang_code
    request.session["lang"] = lang_code

    next_url = request.GET.get("next") or request.META.get("HTTP_REFERER") or "/"
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = "/"

    response = HttpResponseRedirect(next_url)
    response.set_cookie("django_language", lang_code, max_age=365 * 24 * 3600, samesite="Lax")
    return response


def _chart_html(figure, include_plotlyjs: bool = False, lang: str = "en") -> str:
    chart_id = f"chart-{uuid4().hex}"
    controls = []
    for index, trace in enumerate(figure.data):
        is_marker = trace.mode == "markers"
        color = trace.marker.color if is_marker else trace.line.color
        line_style = "legend-mark-marker" if is_marker else "legend-mark-line"
        if not is_marker and trace.line.dash in {"dash", "dot", "dashdot"}:
            line_style += f" legend-mark-{trace.line.dash}"
        controls.append(
            f'<label class="chart-series"><input type="checkbox" data-trace-index="{index}" '
            'checked><span class="chart-series-check" aria-hidden="true"></span>'
            f'<span class="chart-series-mark {line_style}" '
            f'style="--series-color:{escape(str(color))};'
            f'--series-fill:{escape(str(trace.fillcolor or "transparent"))}" '
            f'aria-hidden="true"></span><span>{escape(str(trace.name))}</span></label>'
        )

    if lang == "en":
        legend_aria = "Chart series"
        select_all = "Select all"
        deselect_all = "Deselect all"
        zoom_aria = "Chart zoom"
        zoom_in = "Zoom in"
        zoom_out = "Zoom out"
    else:
        legend_aria = "Serie wykresu"
        select_all = "Zaznacz wszystkie"
        deselect_all = "Odznacz wszystkie"
        zoom_aria = "Przybliżenie wykresu"
        zoom_in = "Przybliż"
        zoom_out = "Oddal"

    legend = (
        f'<div class="chart-toolbar">'
        f'<div class="chart-legend" role="group" aria-label="{legend_aria}">'
        + "".join(controls)
        + '</div><div class="chart-legend-actions">'
        f'<button type="button" data-chart-action="select-all">{select_all}</button>'
        f'<button type="button" data-chart-action="deselect-all">{deselect_all}</button>'
        f'</div><div class="chart-zoom-actions" role="group" aria-label="{zoom_aria}">'
        f'<button type="button" data-chart-zoom="in" '
        f'aria-label="{zoom_in}" title="{zoom_in}">+</button>'
        f'<button type="button" data-chart-zoom="out" '
        f'aria-label="{zoom_out}" title="{zoom_out}">−</button>'
        "</div></div>"
    )
    plot = figure.to_html(
        full_html=False, include_plotlyjs=include_plotlyjs, config=PLOTLY_CONFIG, div_id=chart_id
    )
    return f'<div class="interactive-chart" data-chart-id="{chart_id}">{legend}{plot}</div>'


def _date_range(request: HttpRequest, history, lang: str = "pl"):
    """Buduje formularz zakresu dat z danych historycznych lub z parametrów GET."""
    if request.GET.get("start") or request.GET.get("end"):
        form = DateRangeForm(request.GET, lang=lang)
    else:
        start, end = data.default_dates(history)
        form = DateRangeForm({"start": start.isoformat(), "end": end.isoformat()}, lang=lang)
    return form


def _horizon(request: HttpRequest, lang: str = "pl") -> int:
    """Pobiera horyzont prognozy z formularza lub zwraca wartość domyślną."""
    form = HorizonForm({"horyzont": request.GET.get("horyzont", "24")}, lang=lang)
    if form.is_valid():
        return int(form.cleaned_data["horyzont"])
    return 24


def _simulation_days(request: HttpRequest) -> int:
    """Validaduje liczbę dni symulacji i zwraca jedną z dozwolonych wartości."""
    try:
        days = int(request.GET.get("dni", "7"))
    except TypeError, ValueError:
        return 7
    return days if days in SIMULATION_DAYS else 7


def dashboard(request: HttpRequest) -> HttpResponse:
    lang = _current_lang(request)
    data_dir = get_scenario_data_dir(request)
    active_scenario = get_active_scenario(request)
    try:
        history = data.load_history(data_dir)
        forecast = data.load_forecast(data_dir)
        weather_history = data.load_weather_history(data_dir)
        weather_forecast = data.load_weather_forecast(data_dir)
        backtest_rows = data.load_backtest(data_dir)
        metrics = data.load_metrics(data_dir)
    except FileNotFoundError, data.DemoDataError:
        err = (
            "Dane są chwilowo niedostępne."
            if lang == "pl"
            else "Demo data is temporarily unavailable."
        )
        return render(request, "energy/dashboard.html", {"data_error": err})

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
    horizon_hours = _horizon(request, lang=lang)
    forecast_slice = forecast[:horizon_hours]
    weather_by_timestamp = {record.timestamp: record for record in weather_forecast}
    weather_forecast_slice = [
        weather_by_timestamp[record.timestamp]
        for record in forecast_slice
        if record.timestamp in weather_by_timestamp
    ]

    forecast_options = (
        ((24, "24 h"), (72, "3 days"), (168, "7 days"))
        if lang == "en"
        else ((24, "24 h"), (72, "3 dni"), (168, "7 dni"))
    )

    context = {
        "active_scenario": active_scenario,
        "simulation_days": days,
        "simulation_options": SIMULATION_DAYS,
        "metrics": metrics,
        "horizon_hours": horizon_hours,
        "forecast_options": forecast_options,
        "start": selected_history[0].timestamp.date().isoformat(),
        "end": selected_history[-1].timestamp.date().isoformat(),
        "selected_count": len(selected_history),
        "selected_total": sum((record.total for record in selected_history), Decimal(0)),
        "history_chart": _chart_html(
            build_overview_chart(selected_history, selected_weather, lang=lang),
            include_plotlyjs=True,
            lang=lang,
        ),
        "backtest_chart": _chart_html(build_backtest_chart(backtest_rows, lang=lang), lang=lang),
    }
    forecast_total = sum((record.total for record in forecast_slice), Decimal(0))
    context.update(
        {
            "forecast_total": forecast_total,
            "forecast_chart": _chart_html(
                build_overview_chart(
                    forecast_slice, weather_forecast_slice, forecast=True, lang=lang
                ),
                lang=lang,
            ),
            "peaks": explain_peaks(forecast_slice, weather_forecast_slice, lang=lang),
        }
    )
    return render(request, "energy/dashboard.html", context)


def hourly_history(request: HttpRequest) -> HttpResponse:
    lang = _current_lang(request)
    data_dir = get_scenario_data_dir(request)
    try:
        history = data.load_history(data_dir)
        weather_history = data.load_weather_history(data_dir)
    except FileNotFoundError, data.DemoDataError:
        err = (
            "Dane są chwilowo niedostępne."
            if lang == "pl"
            else "Demo data is temporarily unavailable."
        )
        return render(request, "energy/hourly.html", {"data_error": err})

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
            },
            lang=lang,
        )
    else:
        form = _date_range(request, history, lang=lang)

    category_labels = CATEGORY_LABELS_EN if lang == "en" else CATEGORY_LABELS_PL
    context = {"form": form, "category_labels": category_labels, "rolling_days": rolling_days}
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
                    build_history_chart(selected_history, selected_weather, lang=lang),
                    include_plotlyjs=True,
                    lang=lang,
                ),
            }
        )
    return render(request, "energy/hourly.html", context)


def get_behavioral_advice(device_name: str, moved_kwh: Decimal, lang: str = "pl"):
    if lang == "pl":
        if moved_kwh <= 0:
            return {
                "headline": "Jest dobrze!",
                "action": (
                    "Urządzenie już teraz pracuje w godzinach najwyższej produkcji słonecznej."
                ),
                "comfort": "Nic nie zmieniaj - Wasze obecne nawyki są wzorowe.",
            }
        if device_name in ("Zmywarka", "Dishwasher"):
            return {
                "headline": "Opóźniony start",
                "action": (
                    "Zamiast czekać do wieczora, można załadować zmywarkę po obiedzie i używać "
                    "funkcji opóźnionego startu celując w okolice 13:00."
                ),
                "comfort": (
                    "Zmywarka pracuje bezgłośnie, gdy jesteście poza domem. "
                    "Wieczorem macie puste zlewy - zero stresu!"
                ),
            }
        if device_name in ("Pralka", "Washing machine"):
            return {
                "headline": "Darmowe pranie",
                "action": (
                    "Skoro dziadkowie lub osoby na Home Office są rano w domu, nastawiajcie pranie "
                    "w okolicach 10:00 - 12:00."
                ),
                "comfort": (
                    "Pralka skończy cykl w dzień, co ułatwi szybkie suszenie ubrań "
                    "na świeżym powietrzu."
                ),
            }
        if device_name in ("Suszarka", "Tumble dryer"):
            return {
                "headline": "Wykorzystaj ciepło dnia",
                "action": (
                    "Należy unikać uruchamiania suszarki w nocy. "
                    "Najlepsze okno to wczesne popołudnie."
                ),
                "comfort": (
                    "Suszarka generuje ciepło. Uruchomienie jej w dzień, gdy mniej osób "
                    "jest w domu, zmniejszy wieczorny zaduch."
                ),
            }
        return {
            "headline": "Drobna zmiana, duży efekt",
            "action": "Spróbujcie przenieść pracę tego urządzenia na godziny wczesnopopołudniowe.",
            "comfort": (
                "Każde zasilenie urządzenia w dzień to mniejszy rachunek i więcej oszczędności."
            ),
        }
    else:
        if moved_kwh <= 0:
            return {
                "headline": "Already within the solar window",
                "action": "No recorded cycles of this appliance start outside 9:00–15:00.",
                "comfort": "The model can still compare different start times within that window.",
            }
        if device_name in ("Zmywarka", "Dishwasher"):
            return {
                "headline": "Shift dishwasher cycles",
                "action": "A delayed start can move a cycle into the 9:00–15:00 solar window.",
                "comfort": "Choose a start time that suits the household's routine.",
            }
        if device_name in ("Pralka", "Washing machine"):
            return {
                "headline": "Shift washing cycles",
                "action": "A daytime start can align a washing cycle with solar production.",
                "comfort": "The simulated benefit is shown above for this appliance alone.",
            }
        if device_name in ("Suszarka", "Tumble dryer"):
            return {
                "headline": "Shift drying cycles",
                "action": (
                    "Running the tumble dryer during solar production may reduce grid purchases."
                ),
                "comfort": "The simulated benefit is shown above for this appliance alone.",
            }
        return {
            "headline": "Consider a daytime start",
            "action": "The model compares this appliance's schedule with a solar-window start.",
            "comfort": "Check the calculated change in grid use and savings above.",
        }


def pv_simulator(request: HttpRequest) -> HttpResponse:
    lang = _current_lang(request)
    data_dir = get_scenario_data_dir(request)
    try:
        records, weather, events = data.load_annual(data_dir)
    except FileNotFoundError, data.DemoDataError:
        err = (
            "Dane są chwilowo niedostępne."
            if lang == "pl"
            else "Demo data is temporarily unavailable."
        )
        return render(request, "energy/pv.html", {"data_error": err})

    goal = request.GET.get("cel")
    parameters = {**PV_DEFAULTS, **request.GET.dict()}
    if goal in {"coverage", "payback"}:
        parameters["kwp"] = "5"
    form = PvForm(parameters, lang=lang)
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
            form = PvForm(parameters, lang=lang)
            context["form"] = form
    comparison = pv.compare_variants(records, weather, events, storage=storage)
    selected = next((result for result in comparison if result.kwp == kwp), None)
    if selected is None:
        selected = pv.simulate(records, weather, events, kwp, storage)

    selected = pv.simulate(records, weather, events, kwp, storage)

    oryginalne_efekty = pv.device_effects(records, weather, events, kwp, storage)

    effects = []
    for effect in oryginalne_efekty:
        porada = get_behavioral_advice(effect.device, effect.moved_kwh, lang=lang)
        effects.append(
            {
                "device": device_name(effect.device, lang=lang),
                "moved_kwh": effect.moved_kwh,
                "grid_saved_kwh": effect.grid_saved_kwh,
                "money_saved": effect.money_saved,
                "advice": porada,
            }
        )
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
            "pv_chart": _chart_html(
                build_pv_chart(week, kwp, lang=lang), include_plotlyjs=True, lang=lang
            ),
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
    data_dir = get_scenario_data_dir(request)
    context = {"currency": CURRENCY, "active_scenario": get_active_scenario(request)}
    try:
        history = data.load_history(data_dir)
        forecast = data.load_forecast(data_dir)
        records, weather, _ = data.load_annual(data_dir)
        context["metrics"] = data.load_metrics(data_dir)
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
    lang = _current_lang(request)
    data_dir = get_scenario_data_dir(request)
    try:
        history = data.load_history(data_dir)
        forecast = data.load_forecast(data_dir)
    except FileNotFoundError, data.DemoDataError:
        err = (
            "Dane są chwilowo niedostępne."
            if lang == "pl"
            else "Demo data is temporarily unavailable."
        )
        return HttpResponse(err, status=400)

    sim_label = "Simulation" if lang == "en" else "Symulacja"
    forecast_label = "Forecast" if lang == "en" else "Prognoza"

    if request.GET.get("dni") and not (request.GET.get("start") or request.GET.get("end")):
        days = _simulation_days(request)
        selected = [(sim_label, record) for record in history[-days * 24 :]]
    else:
        form = _date_range(request, history, lang=lang)
        if not form.is_valid():
            err_msg = (
                "The end date cannot be earlier than the start date."
                if lang == "en"
                else "Niepoprawny zakres dat."
            )
            return HttpResponse(err_msg, status=400)

        start = form.cleaned_data["start"]
        end = form.cleaned_data["end"]
        selected = sorted(
            [(sim_label, record) for record in data.filter_records(history, start, end)]
            + [(forecast_label, record) for record in data.filter_records(forecast, start, end)],
            key=lambda item: item[1].timestamp,
        )
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    filename = "hackowatt_energy.csv" if lang == "en" else "hackowatt_dane.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")
    writer = csv.writer(response)

    if lang == "en":
        writer.writerow(
            [
                "Date_Time",
                "Data_Type",
                "Base_kWh",
                "Heating_kWh",
                "Lighting_kWh",
                "Cooking_kWh",
                "TV_Computers_kWh",
                "Major_Appliances_kWh",
                "Total_Consumption_kWh",
                "Events",
            ]
        )
    else:
        writer.writerow(
            [
                "Data_Czas",
                "Typ_danych",
                "Baza_kWh",
                "Ogrzewanie_kWh",
                "Oswietlenie_kWh",
                "Gotowanie_kWh",
                "RTV_PC_kWh",
                "Duze_AGD_kWh",
                "Calkowite_Zuzycie_kWh",
                "Zdarzenia",
            ]
        )

    for kind, record in selected:
        writer.writerow(
            [
                record.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                kind,
                *[f"{value:.3f}" for value in record.categories],
                f"{record.total:.3f}",
                event_names(record.events, lang=lang),
            ]
        )
    return response
