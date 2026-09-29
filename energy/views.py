"""Widoki: pulpit scenariusza, symulator PV, założenia i eksport CSV.

Plik obsługuje widoki aplikacji Django.

Głównym zadaniem modułu jest renderowanie stron interfejsu użytkownika
oraz przygotowywanie danych dla dashboardu, historii godzinowej i symulatora PV."""

import csv
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from html import escape
from uuid import uuid4

from django.conf import settings as django_settings
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.utils.http import url_has_allowed_host_and_scheme

from energy import data, pv, tariffs
from energy.charts import (
    CATEGORY_LABELS_EN,
    CATEGORY_LABELS_PL,
    build_backtest_chart,
    build_history_chart,
    build_overview_chart,
    build_pv_chart,
    build_tariff_price_chart,
)
from energy.currency import (
    CURRENCY_COOKIE,
    SYMBOLS,
    convert_plan_currency,
    from_eur,
    selected_currency,
    to_eur,
)
from energy.explanations import explain_peaks
from energy.forms import DateRangeForm, HorizonForm, PvForm, TariffSettingsForm
from energy.language import selected_language
from energy.presentation import event_names
from energy.scenarios import (
    SCENARIOS,
    get_active_scenario,
    get_scenario_data_dir,
    localized_scenario,
)
from models import recommendations as reco

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
    return selected_language(request)


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


def _chart_html(
    figure, include_plotlyjs: bool = False, lang: str = "en", compact: bool = False
) -> str:
    # Class strings must stay static so Tailwind can detect them when scanning this file.
    chart_id = f"chart-{uuid4().hex}"
    series_cls = (
        (
            "relative inline-flex min-h-[29px] cursor-pointer items-center gap-[7px] rounded-[9px] "
            "border border-line bg-white/[0.88] px-[7px] py-1 text-[10px] font-[650] leading-[1.2] "
        )
        if compact
        else (
            "relative inline-flex min-h-[34px] cursor-pointer items-center gap-[7px] rounded-[9px] "
            "border border-line bg-white/[0.88] py-[5px] pl-2 pr-2.5 text-xs font-[650] "
        )
    )
    series_cls += (
        "leading-[1.2] "
        "text-charcoal transition-[background-color,border-color,opacity] duration-150 "
        "hover:border-sage hover:bg-chartreuse/[0.15] "
        "has-[input:not(:checked)]:bg-white/[0.55] has-[input:not(:checked)]:opacity-60 "
        "has-[input:focus-visible]:outline-2 has-[input:focus-visible]:outline-offset-2 "
        "has-[input:focus-visible]:outline-charcoal"
    )
    check_cls = (
        "relative inline-block size-4 shrink-0 rounded border-[1.5px] border-slate bg-white "
        "peer-checked:border-charcoal peer-checked:bg-chartreuse "
        "peer-checked:after:absolute peer-checked:after:left-[4px] peer-checked:after:top-[1px] "
        "peer-checked:after:h-2 peer-checked:after:w-1 peer-checked:after:rotate-45 "
        "peer-checked:after:border-b-2 peer-checked:after:border-r-2 "
        "peer-checked:after:border-solid peer-checked:after:border-charcoal "
        "peer-checked:after:content-['']"
    )
    mark_base = "inline-block shrink-0 "
    mark_line = (
        "h-[10px] w-[21px] border-t-[3px] "
        "[border-top-color:var(--series-color)] [background:var(--series-fill)]"
    )
    mark_marker = (
        "mx-[5px] size-[11px] rotate-45 border-[1.5px] border-charcoal "
        "[background:var(--series-color)]"
    )
    dash_styles = {
        "dash": "[border-top-style:dashed]",
        "dot": "[border-top-style:dotted]",
        "dashdot": "[border-top-style:dashed]",
    }

    controls = []
    for index, trace in enumerate(figure.data):
        is_marker = trace.mode == "markers"
        color = trace.marker.color if is_marker else trace.line.color
        mark_cls = mark_base + (mark_marker if is_marker else mark_line)
        if not is_marker and trace.line.dash in dash_styles:
            mark_cls += f" {dash_styles[trace.line.dash]}"
        controls.append(
            f'<label class="{series_cls}">'
            f'<input type="checkbox" class="peer sr-only" data-trace-index="{index}" checked>'
            f'<span class="{check_cls}" aria-hidden="true"></span>'
            f'<span class="{mark_cls}" '
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

    action_btn_cls = (
        (
            "min-h-[29px] cursor-pointer rounded-lg border border-slate bg-white px-2.5 py-[5px] "
            "text-[10px] font-extrabold text-charcoal hover:border-charcoal hover:bg-chartreuse"
        )
        if compact
        else (
            "min-h-[34px] cursor-pointer rounded-lg border border-slate bg-white px-2.5 py-[5px] "
            "text-[11px] font-extrabold text-charcoal hover:border-charcoal hover:bg-chartreuse"
        )
    )
    zoom_btn_cls = (
        ("min-h-[29px] w-[29px] cursor-pointer bg-transparent text-xl font-bold ")
        if compact
        else ("min-h-[34px] w-[34px] cursor-pointer bg-transparent text-xl font-bold ")
    )
    zoom_btn_cls += (
        "leading-none text-charcoal enabled:hover:bg-chartreuse disabled:cursor-default "
        "disabled:text-slate disabled:opacity-45"
    )
    toolbar_cls = "flex flex-wrap items-start justify-between gap-x-[18px] gap-y-2.5 " + (
        "px-2.5 pt-[9px]" if compact else "px-3.5 pb-0.5 pt-3 max-md:px-[7px] max-md:pt-2.5"
    )
    legend = (
        f'<div class="{toolbar_cls}">'
        f'<div class="flex flex-[1_1_520px] flex-wrap items-center gap-1.5 max-md:basis-full" '
        f'role="group" aria-label="{legend_aria}">'
        + "".join(controls)
        + '</div><div class="flex flex-wrap gap-[5px] max-md:w-full">'
        f'<button type="button" class="{action_btn_cls}" '
        f'data-chart-action="select-all">{select_all}</button>'
        f'<button type="button" class="{action_btn_cls}" '
        f'data-chart-action="deselect-all">{deselect_all}</button>'
        f'</div><div class="ml-auto inline-flex overflow-hidden rounded-lg border '
        f'border-slate bg-white" role="group" aria-label="{zoom_aria}">'
        f'<button type="button" class="{zoom_btn_cls}" data-chart-zoom="in" '
        f'aria-label="{zoom_in}" title="{zoom_in}">+</button>'
        f'<button type="button" class="{zoom_btn_cls} border-l border-line" '
        f'data-chart-zoom="out" '
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
    currency = selected_currency(request)
    data_dir = get_scenario_data_dir(request)
    active_scenario = localized_scenario(get_active_scenario(request), lang)
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
    prices = data.load_tariff_prices()
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
            build_overview_chart(
                selected_history, selected_weather, prices=prices, lang=lang, currency=currency
            ),
            include_plotlyjs=True,
            lang=lang,
            compact=True,
        ),
        "backtest_chart": _chart_html(
            build_backtest_chart(backtest_rows, prices=prices, lang=lang, currency=currency),
            lang=lang,
        ),
    }
    forecast_total = sum((record.total for record in forecast_slice), Decimal(0))
    context.update(
        {
            "forecast_total": forecast_total,
            "forecast_chart": _chart_html(
                build_overview_chart(
                    forecast_slice,
                    weather_forecast_slice,
                    prices=prices,
                    forecast=True,
                    lang=lang,
                    currency=currency,
                ),
                lang=lang,
                compact=True,
            ),
            "peaks": explain_peaks(forecast_slice, weather_forecast_slice, lang=lang),
        }
    )
    return render(request, "energy/dashboard.html", context)


def hourly_history(request: HttpRequest) -> HttpResponse:
    lang = _current_lang(request)
    currency = selected_currency(request)
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
        prices = data.load_tariff_prices()
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
                    build_history_chart(
                        selected_history,
                        selected_weather,
                        prices=prices,
                        lang=lang,
                        currency=currency,
                    ),
                    include_plotlyjs=True,
                    lang=lang,
                ),
            }
        )
    return render(request, "energy/hourly.html", context)


def _tariff_for_calculation(
    config: tariffs.TariffConfig,
    dynamic: dict | None,
    annual_timestamps: list,
    lang: str,
    currency: str = "EUR",
) -> tuple[tariffs.TariffConfig, dict | None, str]:
    """Zwraca (taryfa, ceny dynamiczne, komunikat) z zasadą pełnego pokrycia rocznego."""
    if config.mode != tariffs.MODE_DYNAMIC:
        text = (
            "Fixed tariff with the rates from Settings."
            if lang == "en"
            else "Taryfa stała z kwotami z ustawień."
        )
        return config, None, text
    fixed = tariffs.TariffConfig(
        mode=tariffs.MODE_FIXED,
        fixed_prices=config.fixed_prices,
        provider_id=config.provider_id,
    )
    if dynamic is None:
        text = (
            "Dynamic tariff selected, but no prices were downloaded — calculating with "
            "the fixed tariff. Run fetch_tariff_prices."
            if lang == "en"
            else "Wybrano taryfę dynamiczną, ale brak pobranych cen — liczę taryfą stałą. "
            "Uruchom fetch_tariff_prices."
        )
        return fixed, None, text
    coverage = tariffs.dynamic_coverage(annual_timestamps, dynamic)
    if coverage < 1:
        percent = (coverage * 100).quantize(Decimal("0.1"))
        text = (
            f"Dynamic prices cover {percent}% of the model year — calculating with "
            "the fixed tariff."
            if lang == "en"
            else f"Ceny dynamiczne pokrywają {percent}% roku modelowego — liczę taryfą stałą."
        )
        return fixed, None, text
    provider = config.provider
    name = provider.name_en if lang == "en" else provider.name_pl
    margin_display = (
        provider.margin_pln
        if currency == "PLN"
        else from_eur(provider.margin, currency).quantize(Decimal("0.00001"))
    )
    text = (
        f"Dynamic tariff · {name} · margin {provider.margin_pln} zł/kWh "
        f"({margin_display} {SYMBOLS[currency]}/kWh) · PSE day-ahead prices."
        if lang == "en"
        else f"Taryfa dynamiczna · {name} · marża {provider.margin_pln} zł/kWh "
        f"({margin_display} {SYMBOLS[currency]}/kWh) · ceny RCE z PSE."
    )
    return config, dynamic, text


RECO_DEVICE_LABELS = {
    "pl": {"dishwasher": "Zmywarka", "washer": "Pralka", "dryer": "Suszarka"},
    "en": {"dishwasher": "Dishwasher", "washer": "Washing machine", "dryer": "Tumble dryer"},
}


def _device_plan(
    request: HttpRequest, data_dir, kwp: Decimal, storage: pv.StorageConfig, lang: str
) -> dict:
    """Plan pracy urządzeń na jutro dla taryfy i scenariusza z żądania (kwoty w EUR)."""
    tariff_config, dynamic_prices = tariffs.tariff_for_request(
        request, django_settings.DEMO_DATA_DIR
    )
    return reco.build_plan(
        scenario_id=get_active_scenario(request)["folder"],
        data_dir=data_dir,
        tariff=tariff_config,
        dynamic=dynamic_prices,
        kwp=kwp,
        storage=storage,
        lang=lang,
        cache_dir=django_settings.DEMO_DATA_DIR / reco.CACHE_DIRNAME,
    )


def _plan_display(plan: dict, currency: str, lang: str) -> dict:
    """Plan po konwersji waluty, z etykietami urządzeń do prezentacji w szablonie."""
    display = convert_plan_currency(plan, currency)
    if display["status"] == "no_data":
        display["no_data_message"] = _reco_no_data_message(display.get("missing_data"), lang)
    display["tariff_notice"] = _reco_tariff_notice(display, lang)
    names = RECO_DEVICE_LABELS.get(lang, RECO_DEVICE_LABELS["pl"])
    for item in display.get("recommendations", []):
        item["label"] = names[item["device"]]
    for item in display["observed_events"]:
        item["label"] = event_names(item["event"], lang=lang)
    return display


def _reco_tariff_notice(plan: dict, lang: str) -> str:
    missing = plan.get("tariff_fallback_hours", 0)
    if not missing:
        return ""
    if lang == "en":
        return (
            f"No PSE price for {missing} of 24 hours. Those hours use your fixed tariff "
            "rate and are marked on the tariff chart."
        )
    return (
        f"Brak ceny PSE dla {missing} z 24 godzin. W tych godzinach używamy Twojej "
        "stawki taryfy stałej; są oznaczone na wykresie taryfy."
    )


def _reco_no_data_message(missing_data: str | None, lang: str) -> str:
    messages = {
        "pl": {
            "dynamic_prices": (
                "Brak cen taryfy dynamicznej na jutro. Sprawdź ponownie po ich publikacji "
                "albo wybierz taryfę stałą."
            ),
            "forecast": "Brak pełnej prognozy zużycia na jutro. Uruchom ponownie prepare_data.",
            "weather": "Brak pełnej prognozy pogody na jutro. Uruchom ponownie prepare_data.",
            "history": "Brak historii cykli urządzeń. Uruchom ponownie prepare_data.",
        },
        "en": {
            "dynamic_prices": (
                "Tomorrow's dynamic tariff prices are unavailable. "
                "Check again after publication or choose a fixed tariff."
            ),
            "forecast": (
                "The complete consumption forecast for tomorrow is unavailable. "
                "Run prepare_data again."
            ),
            "weather": (
                "The complete weather forecast for tomorrow is unavailable. Run prepare_data again."
            ),
            "history": "Appliance cycle history is unavailable. Run prepare_data again.",
        },
    }
    language = lang if lang in messages else "pl"
    return messages[language].get(
        missing_data,
        "Complete data for tomorrow are unavailable."
        if language == "en"
        else "Brak kompletnych danych na jutro.",
    )


def _reco_labels(lang: str, currency: str) -> dict:
    """Teksty kart rekomendacji dla renderowania po stronie klienta (JSON w szablonie)."""
    labels = {
        "devices": RECO_DEVICE_LABELS.get(lang, RECO_DEVICE_LABELS["pl"]),
        "currency_symbol": SYMBOLS[currency],
    }
    if lang == "en":
        labels.update(
            {
                "move_start": "Move start",
                "per_cycle": "Saving per cycle",
                "tomorrow": "tomorrow",
                "annual": "Annual estimate",
                "year_suffix": "year",
                "no_cycle": "No cycle predicted for tomorrow",
                "no_data": "Complete data for tomorrow are unavailable.",
                "total_tomorrow": "Total for tomorrow",
                "source_label": "source",
                "source_local_ai": "local AI",
                "source_fallback": "calculated fallback",
                "history_counts": "Observed in 35 days / matching weekday",
                "observed_heading": "Other activities in this scenario",
                "observed_caption": "Historical observations; no calculated shifting advice",
                "observed_days": "Days in history",
                "matching_days": "Matching weekdays",
                "observed_repeated": "Repeated on matching weekdays",
                "observed_only": "Observed in history",
                "observed_empty": "No other activities were recorded in this scenario.",
                "ev_crosses_midnight": (
                    "Charging crosses midnight; a full cycle cannot be priced from "
                    "tomorrow's 24-hour forecast."
                ),
                "activity_no_advice": "Historical activity; no reliable time-shift calculation.",
                "keep_at": "Keep at",
            }
        )
    else:
        labels.update(
            {
                "move_start": "Przesuń start",
                "per_cycle": "Oszczędność na cyklu",
                "tomorrow": "jutro",
                "annual": "Szacunek roczny",
                "year_suffix": "rok",
                "no_cycle": "Brak przewidywanego cyklu na jutro",
                "no_data": "Brak kompletnych danych na jutro.",
                "total_tomorrow": "Razem na jutro",
                "source_label": "źródło",
                "source_local_ai": "lokalne AI",
                "source_fallback": "wyliczenie zastępcze",
                "history_counts": "Wystąpienia w 35 dniach / w tym dniu tygodnia",
                "observed_heading": "Inne aktywności w tym scenariuszu",
                "observed_caption": "Obserwacje z historii; bez wyliczonej porady przesunięcia",
                "observed_days": "Dni w historii",
                "matching_days": "Pasujące dni tygodnia",
                "observed_repeated": "Powtarzało się w pasujące dni tygodnia",
                "observed_only": "Zaobserwowano w historii",
                "observed_empty": "W tym scenariuszu nie zapisano innych aktywności.",
                "ev_crosses_midnight": (
                    "Ładowanie przechodzi przez północ; pełnego cyklu nie da się "
                    "wycenić z 24-godzinnej prognozy na jutro."
                ),
                "activity_no_advice": (
                    "Aktywność historyczna; brak wiarygodnego wyliczenia przesunięcia."
                ),
                "keep_at": "Pozostaw o",
            }
        )
    return labels


def recommendations_view(request: HttpRequest) -> JsonResponse:
    """Sesyjny endpoint strony PV: plan pracy urządzeń na jutro dla bieżących ustawień."""
    lang = _current_lang(request)
    currency = selected_currency(request)
    form = PvForm({**PV_DEFAULTS, **request.GET.dict()}, lang=lang, currency=currency)
    if not form.is_valid():
        message = (
            "Invalid PV parameters." if lang == "en" else "Niepoprawne parametry instalacji PV."
        )
        return JsonResponse(
            {"status": "error", "message": message, "errors": form.errors.get_json_data()},
            status=400,
        )
    storage = pv.StorageConfig(
        form.cleaned_data["magazyn_kwh"],
        form.cleaned_data["magazyn_moc_kw"],
        to_eur(form.cleaned_data["magazyn_koszt_eur"], currency),
    )
    plan = _device_plan(
        request, get_scenario_data_dir(request), form.cleaned_data["kwp"], storage, lang
    )
    display = _plan_display(plan, currency, lang)
    return JsonResponse(display)


def pv_simulator(request: HttpRequest) -> HttpResponse:
    lang = _current_lang(request)
    currency = selected_currency(request)
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
    form = PvForm(parameters, lang=lang, currency=currency)
    context = {
        "form": form,
        "currency": currency,
        "pv_cost_display": from_eur(tariffs.PV_COST_PER_KWP, currency),
        "export_price_display": from_eur(tariffs.EXPORT_PRICE, currency),
    }
    if not form.is_valid():
        return render(request, "energy/pv.html", context)

    kwp = form.cleaned_data["kwp"]
    month = int(form.cleaned_data["miesiac"])
    tariff_config, dynamic_prices = tariffs.tariff_for_request(
        request, django_settings.DEMO_DATA_DIR
    )
    tariff_used, dynamic_used, tariff_notice = _tariff_for_calculation(
        tariff_config, dynamic_prices, [r.timestamp for r in records], lang, currency
    )
    storage = pv.StorageConfig(
        form.cleaned_data["magazyn_kwh"],
        form.cleaned_data["magazyn_moc_kw"],
        to_eur(form.cleaned_data["magazyn_koszt_eur"], currency),
    )
    if goal in {"coverage", "payback"}:
        choice = pv.choose_capacity(
            records, weather, events, goal, storage, tariff_used, dynamic_used
        )
        context.update({"auto_goal": goal, "capacity_choice": choice})
        if choice.kwp is not None:
            kwp = choice.kwp
            parameters["kwp"] = str(kwp)
            form = PvForm(parameters, lang=lang, currency=currency)
            context["form"] = form
    comparison = pv.compare_variants(
        records, weather, events, storage=storage, tariff=tariff_used, dynamic=dynamic_used
    )
    selected = next((result for result in comparison if result.kwp == kwp), None)
    if selected is None:
        selected = pv.simulate(records, weather, events, kwp, storage)

    selected = pv.simulate(records, weather, events, kwp, storage, tariff_used, dynamic_used)

    plan = _device_plan(request, data_dir, kwp, storage, lang)

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
            "tariff_notice": tariff_notice,
            "recommendation_plan": _plan_display(plan, currency, lang),
            "reco_labels": _reco_labels(lang, currency),
            "pv_chart": _chart_html(
                build_pv_chart(
                    week,
                    kwp,
                    prices=data.load_tariff_prices(),
                    lang=lang,
                    currency=currency,
                ),
                include_plotlyjs=True,
                lang=lang,
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


def _dynamic_status(dynamic: dict | None, payload: dict | None, lang: str) -> dict:
    """Opisuje stan pobranych cen dynamicznych dla strony ustawień."""
    if dynamic is None or payload is None:
        text = (
            "No downloaded dynamic prices. Run python manage.py fetch_tariff_prices "
            "to download PSE day-ahead prices."
            if lang == "en"
            else "Brak pobranych cen dynamicznych. Uruchom python manage.py "
            "fetch_tariff_prices, aby pobrać ceny RCE z PSE."
        )
        return {"available": False, "text": text}
    first, last = min(dynamic), max(dynamic)
    fetched_at = payload.get("fetched_at", "—")
    source = payload.get("source", "PSE")
    text = (
        f"{len(dynamic)} hourly prices · {first:%d.%m.%Y %H:%M} – {last:%d.%m.%Y %H:%M} · "
        f"source: {source} · downloaded {fetched_at}"
        if lang == "en"
        else f"{len(dynamic)} cen godzinowych · {first:%d.%m.%Y %H:%M} – "
        f"{last:%d.%m.%Y %H:%M} · źródło: {source} · pobrano {fetched_at}"
    )
    return {"available": True, "text": text}


def _dynamic_day_prices(
    config: tariffs.TariffConfig, dynamic: dict | None, day: datetime
) -> list[dict]:
    """Godzinowe ceny dynamiczne z marżą dostawcy; braki liczy po stawce stałej."""
    rows = []
    for hour in range(24):
        moment = day.replace(hour=hour, minute=0, second=0, microsecond=0)
        if dynamic is not None and moment in dynamic:
            price = dynamic[moment] + config.provider.margin
            rows.append(
                {"timestamp": moment, "hour": f"{hour:02d}:00", "price": price, "fallback": False}
            )
        else:
            rows.append(
                {
                    "timestamp": moment,
                    "hour": f"{hour:02d}:00",
                    "price": config.price_for_hour(hour),
                    "fallback": True,
                }
            )
    return rows


def _selected_tariff_day(request: HttpRequest, today: date, lang: str) -> tuple[date, str]:
    """Restrict the price preview to the past 365 days, today, or tomorrow."""
    raw = request.GET.get("date")
    if not raw:
        return today, ""
    try:
        selected = date.fromisoformat(raw)
    except ValueError:
        selected = None
    if selected is not None and today - timedelta(days=365) <= selected <= today + timedelta(
        days=1
    ):
        return selected, ""
    message = (
        "Choose today, tomorrow, or a date from the past 365 days. Showing today's prices."
        if lang == "en"
        else "Wybierz dziś, jutro lub datę z ostatnich 365 dni. Pokazano ceny na dziś."
    )
    return today, message


def settings_view(request: HttpRequest) -> HttpResponse:
    """Strona ustawień taryfy: tryb, kwoty stałe i dostawca; zapis w sesji i ciastku."""
    lang = _current_lang(request)
    currency = selected_currency(request)
    if request.method == "POST" and request.POST.get("intent") == "preferences":
        new_lang = request.POST.get("language")
        new_currency = request.POST.get("currency")
        if new_lang in {"pl", "en"} and new_currency in {"EUR", "PLN", "DKK"}:
            request.session["django_language"] = new_lang
            request.session["lang"] = new_lang
            request.session[CURRENCY_COOKIE] = new_currency
            response = HttpResponseRedirect(request.get_full_path())
            response.set_cookie(
                "django_language", new_lang, max_age=365 * 24 * 3600, samesite="Lax"
            )
            response.set_cookie(
                CURRENCY_COOKIE, new_currency, max_age=365 * 24 * 3600, samesite="Lax"
            )
            return response
    base_data_dir = django_settings.DEMO_DATA_DIR
    config, dynamic = tariffs.tariff_for_request(request, base_data_dir)
    if request.method == "POST":
        form = TariffSettingsForm(request.POST, lang=lang, currency=currency)
        if form.is_valid():
            new_config = tariffs.TariffConfig(
                mode=form.cleaned_data["mode"],
                fixed_prices=form.fixed_prices(),
                provider_id=form.cleaned_data["provider"],
            )
            payload = tariffs.serialize_tariff(new_config)
            request.session[tariffs.TARIFF_COOKIE] = payload
            next_url = (
                request.POST.get("next") or request.GET.get("next") or request.get_full_path()
            )
            if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                next_url = "/"
            response = HttpResponseRedirect(next_url)
            response.set_cookie(
                tariffs.TARIFF_COOKIE,
                json.dumps(payload),
                max_age=365 * 24 * 3600,
                samesite="Lax",
            )
            return response
    else:
        form = TariffSettingsForm(lang=lang, currency=currency, config=config)
        if request.GET.get("mode") in (tariffs.MODE_FIXED, tariffs.MODE_DYNAMIC):
            form.initial["mode"] = request.GET["mode"]
    payload = tariffs.load_dynamic_payload(base_data_dir / "tariff_prices.json")
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    selected_day, date_error = _selected_tariff_day(request, today, lang)
    selected_rows = _dynamic_day_prices(
        config, dynamic, datetime.combine(selected_day, datetime.min.time())
    )
    market_count = sum(not row["fallback"] for row in selected_rows)
    cheapest_block, highest_block = tariffs.four_hour_price_blocks(
        [row["price"] for row in selected_rows]
    )
    return render(
        request,
        "energy/settings.html",
        {
            "form": form,
            "dynamic_status": _dynamic_status(dynamic, payload, lang),
            "today_iso": today.isoformat(),
            "tomorrow_iso": tomorrow.isoformat(),
            "min_date_iso": (today - timedelta(days=365)).isoformat(),
            "selected_date_iso": selected_day.isoformat(),
            "selected_date_label": selected_day.strftime("%d.%m.%Y"),
            "selected_is_today": selected_day == today,
            "selected_is_tomorrow": selected_day == tomorrow,
            "date_error": date_error,
            "selected_prices": selected_rows,
            "tariff_chart": _chart_html(
                build_tariff_price_chart(
                    selected_rows,
                    cheapest_block,
                    highest_block,
                    currency=currency,
                    lang=lang,
                ),
                include_plotlyjs=True,
                lang=lang,
            ),
            "market_count": market_count,
            "fallback_count": 24 - market_count,
            "cheapest_block": cheapest_block,
            "highest_block": highest_block,
            "blocks_tied": cheapest_block.average == highest_block.average,
            "form_errors": form.errors,
        },
    )


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
