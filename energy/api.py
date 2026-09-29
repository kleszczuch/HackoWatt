"""Endpointy REST API dla aplikacji mobilnej eko-dziki.

Zapewnia szybki i bezpieczny odczyt informacji o optymalnych godzinach
użycia urządzeń elektrycznych dla osób starszych (dziadków), młodzieży i rodziców.
Wymaga autoryzacji za pomocą tokenu Bearer (nagłówek Authorization: Bearer <token>).
"""

import functools
import json
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods
from dotenv import load_dotenv

from energy import data, household, pv, tariffs
from energy.charts import CATEGORY_LABELS_EN, CATEGORY_LABELS_PL
from energy.explanations import explain_peaks
from energy.forms import DateRangeForm, HorizonForm, PvForm
from energy.language import selected_language
from energy.presentation import device_name, event_names
from energy.scenarios import SCENARIOS, get_active_scenario, get_scenario_data_dir


def _tr(request: HttpRequest, pl: str, en: str) -> str:
    return en if selected_language(request) == "en" else pl


def api_success(data_payload: Any, status: int = 200) -> JsonResponse:
    """Zwraca ujednoliconą odpowiedź sukcesu JSON."""
    return JsonResponse({"status": "success", "data": data_payload}, status=status)


def api_error(
    message: str, code: str = "ERROR", status: int = 400, details: Any = None
) -> JsonResponse:
    """Zwraca ujednoliconą odpowiedź błędu JSON."""
    payload: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        payload["details"] = details
    return JsonResponse({"status": "error", "error": payload}, status=status)


def get_expected_api_key() -> str:
    """Odczytuje klucz API_KEY z pliku .env za pomocą dotenv oraz ze zmiennych środowiskowych."""
    base_dir = getattr(settings, "BASE_DIR", Path(__file__).resolve().parent.parent)
    load_dotenv(base_dir / ".env", override=True)
    return os.getenv("API_KEY") or getattr(settings, "API_KEY", "")


def check_api_secret(request: HttpRequest) -> bool:
    """Weryfikuje autoryzację API za pomocą tokenu Bearer na podstawie API_KEY z pliku .env."""
    expected_key = get_expected_api_key()
    if not expected_key:
        return False

    # 1. Token Bearer w nagłówku Authorization (główny dla aplikacji mobilnej)
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.startswith("Bearer "):
        token = auth_header.split("Bearer ", 1)[1].strip()
        if token == expected_key:
            return True

    return False


def require_api_secret(view_func):
    """Dekorator wymuszający autoryzację za pomocą tokenu Bearer."""

    @functools.wraps(view_func)
    def _wrapped_view(request: HttpRequest, *args, **kwargs):
        if not check_api_secret(request):
            return api_error(
                _tr(
                    request,
                    "Wymagana autoryzacja za pomocą tokenu Bearer "
                    "(nagłówek: Authorization: Bearer <token>).",
                    "Bearer token authorization is required "
                    "(header: Authorization: Bearer <token>).",
                ),
                code="UNAUTHORIZED",
                status=401,
            )
        return view_func(request, *args, **kwargs)

    return _wrapped_view


def handle_data_errors(view_func):
    """Dekorator przechwytujący brak lub błędy plików demonstracyjnych."""

    @functools.wraps(view_func)
    def _wrapped_view(request: HttpRequest, *args, **kwargs):
        try:
            return view_func(request, *args, **kwargs)
        except FileNotFoundError, data.DemoDataError:
            return api_error(
                _tr(
                    request,
                    "Dane demonstracyjne są niedostępne lub niepoprawne.",
                    "Demo data is unavailable or invalid.",
                ),
                code="DATA_NOT_FOUND",
                status=503,
            )

    return _wrapped_view


def _to_float(val: Decimal | float | int | None, round_digits: int = 3) -> float | None:
    if val is None:
        return None
    return round(float(val), round_digits)


def _tariff(request: HttpRequest) -> tuple[tariffs.TariffConfig, dict | None]:
    """Zwraca konfigurację taryfy użytkownika i pobrane ceny dynamiczne."""
    return tariffs.tariff_for_request(request, settings.DEMO_DATA_DIR)


def _parse_params(request: HttpRequest) -> tuple[dict, str | None]:
    """Pobiera parametry z query string (GET) lub z ciała JSON / formularza (POST)."""
    if request.method == "GET":
        return request.GET.dict(), None
    if not request.body:
        return request.POST.dict(), None
    try:
        data_dict = json.loads(request.body.decode("utf-8"))
        if not isinstance(data_dict, dict):
            return {}, _tr(
                request,
                "Ciało żądania musi być obiektem JSON.",
                "Request body must be a JSON object.",
            )
        return data_dict, None
    except json.JSONDecodeError:
        return {}, _tr(request, "Niepoprawny format JSON.", "Invalid JSON.")


# ----------------------------------------------------------------------
# 1. Inteligentny harmonogram dnia (dla seniorów i młodzieży)
# ----------------------------------------------------------------------


@require_http_methods(["GET"])
@require_api_secret
@handle_data_errors
def smart_schedule_today(request: HttpRequest) -> JsonResponse:
    """Zwraca czytelny dla seniorów i młodzieży harmonogram dnia.

    Dzieli dobę na proste strefy kolorystyczne (zielona, żółta, czerwona),
    wskazuje status na bieżącą godzinę oraz dedykowane wskazówki dla domowników.
    Wymaga autoryzacji api_secret.
    """
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    now_hour = now.hour
    tariff_config, dynamic_prices = _tariff(request)
    day_start = now.replace(hour=0)
    priced = [tariff_config.price_at(day_start.replace(hour=h), dynamic_prices) for h in range(24)]
    prices = [price for price, _ in priced]
    low = min(prices)
    high = max(prices)

    def band(price: Decimal) -> tuple[str, str]:
        if price == low:
            return "green", _tr(request, "Najniższa stawka", "Lowest rate")
        if price == high:
            return "red", _tr(request, "Najwyższa stawka", "Highest rate")
        return "yellow", _tr(request, "Stawka pośrednia", "Intermediate rate")

    current_code, current_title = band(prices[now_hour])
    timeline = [
        {
            "hour": hour,
            "hour_label": f"{hour:02d}:00 – {(hour + 1):02d}:00",
            "status_code": band(price)[0],
            "badge": band(price)[1],
            "price_per_kwh": _to_float(price),
            "is_fallback": priced[hour][1],
            "is_current": hour == now_hour,
        }
        for hour, price in enumerate(prices)
    ]
    scen = get_active_scenario(request)
    return api_success(
        {
            "scenario": {
                "id": scen["id"],
                "name": scen["name"],
                "city": scen["city"],
            },
            "current_hour": {
                "hour": now_hour,
                "status_code": current_code,
                "status_title": current_title,
                "price_per_kwh": _to_float(prices[now_hour]),
                "is_fallback": priced[now_hour][1],
                "currency": tariffs.CURRENCY,
            },
            "lowest_tariff_hours": [hour for hour, price in enumerate(prices) if price == low],
            "highest_tariff_hours": [hour for hour, price in enumerate(prices) if price == high],
            "timeline": timeline,
        }
    )


# ----------------------------------------------------------------------
# 2. Dane o pracy urządzeń w roku modelowym
# ----------------------------------------------------------------------


@require_http_methods(["GET"])
@require_api_secret
@handle_data_errors
def devices_guidance(request: HttpRequest) -> JsonResponse:
    """Rzeczywiste liczby cykli i energii w wygenerowanym roku modelowym."""
    data_dir = get_scenario_data_dir(request)
    scen = get_active_scenario(request)
    records, _, events = data.load_annual(data_dir)
    devices = []
    for device, display_name in (
        ("Zmywarka", "Zmywarka"),
        ("Pralka", "Pralka"),
        ("Suszarka", "Suszarka bębnowa"),
    ):
        selected = [event for event in events if event.device == device]
        total = sum((event.energy_kwh for event in selected), Decimal(0))
        outside = sum(
            (event.energy_kwh for event in selected if event.start_hour not in pv.PV_WINDOW),
            Decimal(0),
        )
        devices.append(
            {
                "device": _tr(
                    request,
                    display_name,
                    "Tumble dryer" if device == "Suszarka" else device_name(device, lang="en"),
                ),
                "annual_events": len(selected),
                "annual_energy_kwh": _to_float(total),
                "energy_per_cycle_kwh": _to_float(total / len(selected)) if selected else None,
                "energy_started_outside_pv_window_kwh": _to_float(outside),
            }
        )
    for label, label_en, index in (
        ("Komputery i RTV", "Computers and TV", 4),
        ("Gotowanie", "Cooking", 3),
    ):
        total = sum((record.categories[index] for record in records), Decimal(0))
        devices.append(
            {"device": _tr(request, label, label_en), "annual_energy_kwh": _to_float(total)}
        )
    return api_success(
        {
            "scenario": {
                "id": scen["id"],
                "name": scen["name"],
                "city": scen["city"],
            },
            "devices": devices,
            "pv_window": "09:00–15:00",
        }
    )


# ----------------------------------------------------------------------
# 3. Pulpit mobilny / Status bieżący
# ----------------------------------------------------------------------


@require_http_methods(["GET"])
@require_api_secret
@handle_data_errors
def dashboard_summary(request: HttpRequest) -> JsonResponse:
    """Zwraca skonsolidowany status na ekran główny aplikacji mobilnej."""
    data_dir = get_scenario_data_dir(request)
    scen = get_active_scenario(request)
    history = data.load_history(data_dir)
    forecast = data.load_forecast(data_dir)
    weather_history = data.load_weather_history(data_dir)
    weather_forecast = data.load_weather_forecast(data_dir)

    last_hour = history[-1]
    weather_by_time = {w.timestamp: w for w in weather_history}
    last_weather = weather_by_time.get(last_hour.timestamp)

    # Ostatnie 24 godziny z historii
    last_24h_slice = history[-24:]
    sum_last_24h = sum((r.total for r in last_24h_slice), Decimal(0))

    # Prognoza 24h
    forecast_24h = forecast[:24]
    forecast_weather_by_time = {w.timestamp: w for w in weather_forecast}
    weather_24h = [
        forecast_weather_by_time[r.timestamp]
        for r in forecast_24h
        if r.timestamp in forecast_weather_by_time
    ]
    forecast_24h_sum = sum((r.total for r in forecast_24h), Decimal(0))

    # Wyjaśnienia szczytów
    peaks = explain_peaks(forecast_24h, weather_24h, top=1, lang=selected_language(request))
    next_peak = None
    if peaks:
        peak = peaks[0]
        next_peak = {
            "timestamp": peak.timestamp.isoformat(),
            "total_kwh": _to_float(peak.total),
            "explanation": peak.sentence,
        }

    # Bieżąca taryfa i prosta ocena
    tariff_config, dynamic_prices = _tariff(request)
    now_moment = datetime.now().replace(minute=0, second=0, microsecond=0)
    current_hour_idx = now_moment.hour
    current_price, _ = tariff_config.price_at(now_moment, dynamic_prices)
    if current_price >= Decimal("0.40"):
        period_label = _tr(request, "Szczyt popołudniowy (drogo)", "Afternoon peak (expensive)")
        period_color = "red"
    elif current_price <= Decimal("0.18"):
        period_label = _tr(request, "Dolina nocna (bardzo tanio)", "Night valley (very cheap)")
        period_color = "green"
    elif 9 <= current_hour_idx < 15:
        period_label = _tr(request, "Taryfa dzienna (okno modelu PV)", "Day rate (PV window)")
        period_color = "green"
    else:
        period_label = _tr(request, "Standardowa stawka dzienna", "Standard day rate")
        period_color = "yellow"

    annual_records, annual_weather, annual_events = data.load_annual(data_dir)
    pv_preview = pv.simulate(annual_records, annual_weather, annual_events, Decimal(5))

    # Dominująca kategoria w ostatniej godzinie
    max_cat_idx = max(range(len(last_hour.categories)), key=lambda i: last_hour.categories[i])
    category_key = household.CATEGORIES[max_cat_idx]
    category_labels = (
        CATEGORY_LABELS_EN if selected_language(request) == "en" else CATEGORY_LABELS_PL
    )
    category_label = (
        category_labels[max_cat_idx] if max_cat_idx < len(category_labels) else category_key
    )
    dominant_category = {
        "key": category_key,
        "label": category_label,
        "kwh": _to_float(last_hour.categories[max_cat_idx]),
    }

    return api_success(
        {
            "scenario": {
                "id": scen["id"],
                "name": scen["name"],
                "city": scen["city"],
                "country_code": scen.get("country_code", "DK"),
                "flag": scen.get("flag_emoji", "🇩🇰"),
                "household": scen.get("household", {}),
            },
            "last_reading": {
                "timestamp": last_hour.timestamp.isoformat(),
                "total_kwh": _to_float(last_hour.total),
                "temperature_c": last_weather.temperature if last_weather else None,
                "dominant_category": dominant_category,
                "events": event_names(last_hour.events, lang=selected_language(request)),
            },
            "tariff": {
                "current_hour": current_hour_idx,
                "price_eur": _to_float(current_price),
                "period_label": period_label,
                "period_color": period_color,
                "currency": tariffs.CURRENCY,
            },
            "history_last_24h_kwh": _to_float(sum_last_24h),
            "forecast_next_24h_kwh": _to_float(forecast_24h_sum),
            "next_peak": next_peak,
            "pv_preview": {
                "reference_kwp": 5.0,
                "typical_annual_coverage_percent": _to_float(pv_preview.coverage_a, 2),
                "optimized_annual_coverage_percent": _to_float(pv_preview.coverage_b, 2),
            },
        }
    )


# ----------------------------------------------------------------------
# 4. Historia zużycia energii (odczyt z paginacją i filtrem dat)
# ----------------------------------------------------------------------


@require_http_methods(["GET"])
@require_api_secret
@handle_data_errors
def consumption_history(request: HttpRequest) -> JsonResponse:
    """Pobiera historię zużycia energii z paginacją i filtrem dat."""
    data_dir = get_scenario_data_dir(request)
    scen = get_active_scenario(request)
    history = data.load_history(data_dir)
    weather_history = data.load_weather_history(data_dir)
    weather_by_time = {w.timestamp: w for w in weather_history}

    start_param = request.GET.get("start")
    end_param = request.GET.get("end")

    if start_param or end_param:
        form = DateRangeForm(request.GET, lang=selected_language(request))
        if not form.is_valid():
            return api_error(
                _tr(request, "Niepoprawny zakres dat.", "Invalid date range."),
                code="INVALID_DATE_RANGE",
                status=400,
                details=form.errors.get_json_data(),
            )
        start_date = form.cleaned_data["start"]
        end_date = form.cleaned_data["end"]
    else:
        start_date, end_date = data.default_dates(history)

    filtered_history = data.filter_records(history, start_date, end_date)

    # Paginacja
    page_param = request.GET.get("page", 1)
    page_size_param = request.GET.get("page_size", 24)

    try:
        page_num = int(page_param)
        page_size = int(page_size_param)
        if page_num < 1:
            raise ValueError(
                _tr(
                    request,
                    "Numer strony musi być większy lub równy 1.",
                    "Page number must be at least 1.",
                )
            )
        if page_size < 1 or page_size > 168:
            raise ValueError(
                _tr(
                    request,
                    "Rozmiar strony 'page_size' musi wynosić od 1 do 168.",
                    "Page size must be between 1 and 168.",
                )
            )
    except (ValueError, TypeError) as exc:
        message = (
            str(exc)
            if str(exc).startswith(("Numer strony", "Page number", "Rozmiar strony", "Page size"))
            else _tr(
                request, "Niepoprawne parametry stronicowania.", "Invalid pagination parameters."
            )
        )
        return api_error(message, code="INVALID_PAGINATION", status=400)

    paginator = Paginator(filtered_history, page_size)
    try:
        page_obj = paginator.get_page(page_num)
    except (EmptyPage, PageNotAnInteger) as exc:
        return api_error(str(exc), code="INVALID_PAGE", status=400)

    # Agregaty dla wybranego zakresu dat
    total_kwh = sum((r.total for r in filtered_history), Decimal(0))
    cat_sums = {
        name: _to_float(sum((r.categories[i] for r in filtered_history), Decimal(0)))
        for i, name in enumerate(household.CATEGORIES)
    }

    items = []
    for r in page_obj.object_list:
        w = weather_by_time.get(r.timestamp)
        items.append(
            {
                "timestamp": r.timestamp.isoformat(),
                "total_kwh": _to_float(r.total),
                "categories": {
                    name: _to_float(r.categories[i]) for i, name in enumerate(household.CATEGORIES)
                },
                "temperature_c": w.temperature if w else None,
                "events": event_names(r.events, lang=selected_language(request)),
            }
        )

    return api_success(
        {
            "scenario": {
                "id": scen["id"],
                "name": scen["name"],
                "city": scen["city"],
            },
            "pagination": {
                "page": page_obj.number,
                "page_size": page_size,
                "total_items": paginator.count,
                "total_pages": paginator.num_pages,
                "has_next": page_obj.has_next(),
                "has_previous": page_obj.has_previous(),
            },
            "summary": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "total_kwh": _to_float(total_kwh),
                "categories_totals": cat_sums,
            },
            "items": items,
        }
    )


# ----------------------------------------------------------------------
# 5. Prognoza zużycia energii (odczyt na 24, 72, 168 h)
# ----------------------------------------------------------------------


@require_http_methods(["GET"])
@require_api_secret
@handle_data_errors
def consumption_forecast(request: HttpRequest) -> JsonResponse:
    """Pobiera prognozę zużycia energii dla zadanego horyzontu (24, 72, 168 h)."""
    horizon_param = request.GET.get("horizon", request.GET.get("horyzont", "24"))
    horizon_form = HorizonForm({"horyzont": horizon_param}, lang=selected_language(request))
    if not horizon_form.is_valid():
        return api_error(
            _tr(
                request,
                "Niepoprawny horyzont prognozy. Dopuszczalne wartości to: 24, 72, 168.",
                "Invalid forecast horizon. Allowed values: 24, 72, 168.",
            ),
            code="INVALID_HORIZON",
            status=400,
        )

    horizon_hours = int(horizon_form.cleaned_data["horyzont"])
    data_dir = get_scenario_data_dir(request)
    scen = get_active_scenario(request)
    forecast = data.load_forecast(data_dir)
    weather_forecast = data.load_weather_forecast(data_dir)

    forecast_slice = forecast[:horizon_hours]
    weather_by_time = {w.timestamp: w for w in weather_forecast}
    weather_slice = [
        weather_by_time[r.timestamp] for r in forecast_slice if r.timestamp in weather_by_time
    ]

    total_kwh = sum((r.total for r in forecast_slice), Decimal(0))
    cat_sums = {
        name: _to_float(sum((r.categories[i] for r in forecast_slice), Decimal(0)))
        for i, name in enumerate(household.CATEGORIES)
    }

    # Wyjaśnienia szczytów
    peaks = explain_peaks(forecast_slice, weather_slice, top=3, lang=selected_language(request))
    peaks_payload = [
        {
            "timestamp": p.timestamp.isoformat(),
            "total_kwh": _to_float(p.total),
            "explanation": p.sentence,
        }
        for p in peaks
    ]

    tariff_config, dynamic_prices = _tariff(request)
    items = []
    for r in forecast_slice:
        w = weather_by_time.get(r.timestamp)
        tariff_price, tariff_fallback = tariff_config.price_at(r.timestamp, dynamic_prices)
        items.append(
            {
                "timestamp": r.timestamp.isoformat(),
                "total_kwh": _to_float(r.total),
                "categories": {
                    name: _to_float(r.categories[i]) for i, name in enumerate(household.CATEGORIES)
                },
                "weather": {
                    "temperature_c": w.temperature if w else None,
                    "cloud_cover_percent": w.cloud_cover if w else None,
                    "radiation_w_m2": w.radiation if w else None,
                },
                "tariff_price_eur": _to_float(tariff_price),
                "tariff_is_fallback": tariff_fallback,
            }
        )

    return api_success(
        {
            "scenario": {
                "id": scen["id"],
                "name": scen["name"],
                "city": scen["city"],
            },
            "horizon_hours": horizon_hours,
            "total_kwh": _to_float(total_kwh),
            "categories_totals": cat_sums,
            "peaks": peaks_payload,
            "items": items,
        }
    )


# ----------------------------------------------------------------------
# 6. Taryfy i okna cenowe
# ----------------------------------------------------------------------


@require_http_methods(["GET"])
@require_api_secret
def tariffs_info(request: HttpRequest) -> JsonResponse:
    """Zwraca harmonogram taryfowy, strefy cenowe i aktualne stawki."""
    tariff_config, dynamic_prices = _tariff(request)
    periods = []
    for start_h, end_h, price in tariffs.TARIFF_PERIODS:
        price = tariff_config.price_for_hour(start_h)
        label = _tr(request, "Standardowa dzienna", "Standard day rate")
        if price >= Decimal("0.40"):
            label = _tr(
                request, "Szczyt popołudniowy (najdroższa)", "Afternoon peak (highest rate)"
            )
        elif price <= Decimal("0.18"):
            label = _tr(request, "Dolina nocna (najtańsza)", "Night valley (lowest rate)")
        elif start_h >= 22:
            label = _tr(request, "Strefa wieczorna", "Evening period")

        periods.append(
            {
                "start_hour": start_h,
                "end_hour": end_h,
                "price_per_kwh": _to_float(price),
                "label": label,
            }
        )

    now_moment = datetime.now().replace(minute=0, second=0, microsecond=0)
    now_hour = now_moment.hour
    current_price, current_fallback = tariff_config.price_at(now_moment, dynamic_prices)
    scen = get_active_scenario(request)
    return api_success(
        {
            "scenario": {
                "id": scen["id"],
                "name": scen["name"],
                "city": scen["city"],
            },
            "currency": tariffs.CURRENCY,
            "current_hour": now_hour,
            "current_price_eur": _to_float(current_price),
            "current_price_is_fallback": current_fallback,
            "periods": periods,
            "recommendations": {
                "cheapest_window": {
                    "start_hour": 0,
                    "end_hour": 6,
                    "price_per_kwh": _to_float(tariff_config.price_for_hour(2)),
                },
                "pv_window": {
                    "start_hour": 9,
                    "end_hour": 15,
                    "price_per_kwh": _to_float(tariff_config.price_for_hour(12)),
                },
                "peak_window": {
                    "start_hour": 17,
                    "end_hour": 22,
                    "price_per_kwh": _to_float(tariff_config.price_for_hour(18)),
                },
            },
        }
    )


# ----------------------------------------------------------------------
# 7. Symulator fotowoltaiki (PV) i warianty
# ----------------------------------------------------------------------


@require_http_methods(["GET", "POST"])
@require_api_secret
@handle_data_errors
def pv_simulate_api(request: HttpRequest) -> JsonResponse:
    """Symuluje instalację PV o zadanej mocy kWp z porównaniem wariantów A i B."""
    data_dir = get_scenario_data_dir(request)
    scen = get_active_scenario(request)
    records, weather_annual, events = data.load_annual(data_dir)
    params, err = _parse_params(request)
    if err:
        return api_error(err, code="INVALID_PARAMS", status=400)

    kwp_val = params.get("kwp", "5")
    month_val = str(params.get("month", params.get("miesiac", "6")))
    magazyn_kwh_val = str(params.get("magazyn_kwh", "0"))
    magazyn_moc_kw_val = str(params.get("magazyn_moc_kw", "5"))
    magazyn_koszt_eur_val = str(params.get("magazyn_koszt_eur", "0"))
    include_profile = str(params.get("include_week_profile", "false")).lower() in (
        "1",
        "true",
        "yes",
    )

    form = PvForm(
        {
            "kwp": kwp_val,
            "miesiac": month_val,
            "magazyn_kwh": magazyn_kwh_val,
            "magazyn_moc_kw": magazyn_moc_kw_val,
            "magazyn_koszt_eur": magazyn_koszt_eur_val,
        },
        lang=selected_language(request),
    )
    if not form.is_valid():
        return api_error(
            _tr(request, "Niepoprawne parametry symulacji PV.", "Invalid PV simulation settings."),
            code="INVALID_PV_PARAMS",
            status=400,
            details=form.errors.get_json_data(),
        )

    kwp = form.cleaned_data["kwp"]
    month = int(form.cleaned_data["miesiac"])
    storage = pv.StorageConfig(
        form.cleaned_data["magazyn_kwh"],
        form.cleaned_data["magazyn_moc_kw"],
        form.cleaned_data["magazyn_koszt_eur"],
    )

    sim_result = pv.simulate(records, weather_annual, events, kwp, storage)
    effects = pv.device_effects(records, weather_annual, events, kwp, storage)

    var_a = sim_result.variant_a
    var_b = sim_result.variant_b

    # Różnica / zysk z optymalizacji nawyków
    opt_gain_self_kwh = var_b.self_kwh - var_a.self_kwh
    opt_gain_savings_eur = var_b.savings - var_a.savings
    payback_diff = None
    if var_a.payback_years is not None and var_b.payback_years is not None:
        payback_diff = var_a.payback_years - var_b.payback_years

    response_data: dict[str, Any] = {
        "scenario": {
            "id": scen["id"],
            "name": scen["name"],
            "city": scen["city"],
        },
        "kwp": _to_float(kwp, 1),
        "currency": tariffs.CURRENCY,
        "storage_capacity_kwh": _to_float(storage.capacity_kwh),
        "storage_power_kw": _to_float(storage.power_kw),
        "investment_eur": _to_float(sim_result.investment_eur, 2),
        "annual_consumption_kwh": _to_float(sim_result.consumption_kwh),
        "annual_production_kwh": _to_float(sim_result.production_kwh),
        "variant_a": {
            "name": _tr(request, "Obecne nawyki", "Current routine"),
            "self_consumption_kwh": _to_float(var_a.self_kwh),
            "exported_kwh": _to_float(var_a.exported_kwh),
            "grid_kwh": _to_float(var_a.grid_kwh),
            "coverage_percent": _to_float(sim_result.coverage_a, 2),
            "savings_eur": _to_float(var_a.savings, 2),
            "payback_years": _to_float(var_a.payback_years, 1),
        },
        "variant_b": {
            "name": _tr(
                request,
                "Przesunięcie elastycznych urządzeń (okno 9:00–15:00)",
                "Shift flexible appliances (9:00–15:00 window)",
            ),
            "self_consumption_kwh": _to_float(var_b.self_kwh),
            "exported_kwh": _to_float(var_b.exported_kwh),
            "grid_kwh": _to_float(var_b.grid_kwh),
            "coverage_percent": _to_float(sim_result.coverage_b, 2),
            "savings_eur": _to_float(var_b.savings, 2),
            "payback_years": _to_float(var_b.payback_years, 1),
        },
        "optimization_gain": {
            "additional_self_kwh": _to_float(opt_gain_self_kwh),
            "additional_savings_eur": _to_float(opt_gain_savings_eur, 2),
            "payback_shortened_years": _to_float(payback_diff, 1),
        },
        "device_recommendations": [
            {
                "device": device_name(effect.device, lang=selected_language(request)),
                "moved_kwh": _to_float(effect.moved_kwh),
                "grid_saved_kwh": _to_float(effect.grid_saved_kwh),
                "money_saved_eur": _to_float(effect.money_saved, 2),
            }
            for effect in effects
        ],
    }

    if include_profile:
        try:
            week = pv.representative_week(records, weather_annual, events, kwp, month, storage)
            response_data["week_profile"] = {
                "month": month,
                "timestamps": [t.isoformat() for t in week.timestamps],
                "load_kwh": [_to_float(v) for v in week.load],
                "pv_kwh": [_to_float(v) for v in week.pv],
                "grid_a_kwh": [_to_float(v) for v in week.grid_a],
                "grid_b_kwh": [_to_float(v) for v in week.grid_b],
                "battery_b_kwh": [_to_float(v) for v in week.battery_b],
            }
        except StopIteration:
            response_data["week_profile"] = None
            response_data["week_profile_warning"] = _tr(
                request,
                f"Brak pełnego tygodnia danych dla miesiąca {month}.",
                f"No complete week of data for month {month}.",
            )

    return api_success(response_data)


@require_http_methods(["GET"])
@require_api_secret
@handle_data_errors
def pv_variants_list(request: HttpRequest) -> JsonResponse:
    """Zwraca tabelę porównawczą typowych mocy instalacji PV (2..10 kWp)."""
    data_dir = get_scenario_data_dir(request)
    scen = get_active_scenario(request)
    records, weather_annual, events = data.load_annual(data_dir)
    comparison = pv.compare_variants(records, weather_annual, events)

    items = []
    for item in comparison:
        items.append(
            {
                "kwp": _to_float(item.kwp, 1),
                "annual_production_kwh": _to_float(item.production_kwh),
                "coverage_a_percent": _to_float(item.coverage_a, 2),
                "coverage_b_percent": _to_float(item.coverage_b, 2),
                "savings_a_eur": _to_float(item.variant_a.savings, 2),
                "savings_b_eur": _to_float(item.variant_b.savings, 2),
                "payback_a_years": _to_float(item.variant_a.payback_years, 1),
                "payback_b_years": _to_float(item.variant_b.payback_years, 1),
                "grid_a_kwh": _to_float(item.variant_a.grid_kwh),
                "grid_b_kwh": _to_float(item.variant_b.grid_kwh),
            }
        )

    return api_success(
        {
            "scenario": {
                "id": scen["id"],
                "name": scen["name"],
                "city": scen["city"],
            },
            "currency": tariffs.CURRENCY,
            "variants": items,
        }
    )


# ----------------------------------------------------------------------
# 8. Urządzenia elastyczne i kalkulator przesunięcia (GET/POST)
# ----------------------------------------------------------------------


@require_http_methods(["GET"])
@require_api_secret
@handle_data_errors
def flexible_events_list(request: HttpRequest) -> JsonResponse:
    """Zwraca listę zarejestrowanych cykli pracy urządzeń elastycznych."""
    data_dir = get_scenario_data_dir(request)
    scen = get_active_scenario(request)
    events = data.load_history_events(data_dir)

    device_filter = request.GET.get("device", "").strip()
    if device_filter:
        events = [e for e in events if e.device.lower() == device_filter.lower()]

    page_param = request.GET.get("page", 1)
    page_size_param = request.GET.get("page_size", 25)

    try:
        page_num = int(page_param)
        page_size = int(page_size_param)
        if page_num < 1:
            raise ValueError(
                _tr(
                    request,
                    "Numer strony musi być większy lub równy 1.",
                    "Page number must be at least 1.",
                )
            )
        if page_size < 1 or page_size > 100:
            raise ValueError(
                _tr(
                    request,
                    "Rozmiar strony 'page_size' musi wynosić od 1 do 100.",
                    "Page size must be between 1 and 100.",
                )
            )
    except (ValueError, TypeError) as exc:
        message = (
            str(exc)
            if str(exc).startswith(("Numer strony", "Page number", "Rozmiar strony", "Page size"))
            else _tr(
                request, "Niepoprawne parametry stronicowania.", "Invalid pagination parameters."
            )
        )
        return api_error(message, code="INVALID_PAGINATION", status=400)

    paginator = Paginator(events, page_size)
    try:
        page_obj = paginator.get_page(page_num)
    except (EmptyPage, PageNotAnInteger) as exc:
        return api_error(str(exc), code="INVALID_PAGE", status=400)

    items = [
        {
            "device": device_name(e.device, lang=selected_language(request)),
            "day": e.day.isoformat(),
            "start_hour": e.start_hour,
            "duration_h": e.duration_h,
            "energy_kwh": _to_float(e.energy_kwh),
        }
        for e in page_obj.object_list
    ]

    return api_success(
        {
            "scenario": {
                "id": scen["id"],
                "name": scen["name"],
                "city": scen["city"],
            },
            "pagination": {
                "page": page_obj.number,
                "page_size": page_size,
                "total_items": paginator.count,
                "total_pages": paginator.num_pages,
                "has_next": page_obj.has_next(),
                "has_previous": page_obj.has_previous(),
            },
            "device_filter": device_filter or None,
            "items": items,
        }
    )


@require_http_methods(["GET", "POST"])
@require_api_secret
@handle_data_errors
def shift_simulation(request: HttpRequest) -> JsonResponse:
    """Kalkulator korzyści z przesunięcia pracy urządzenia (dostępny przez prosty GET lub POST)."""
    params, parse_err = _parse_params(request)
    if parse_err:
        return api_error(parse_err, code="INVALID_PARAMS", status=400)

    device = params.get("device", "").strip()
    if device not in household.DEVICE_PROFILES:
        valid_devices = ", ".join(household.DEVICE_PROFILES.keys())
        return api_error(
            _tr(
                request,
                f"Nieobsługiwane urządzenie: '{device}'. Dozwolone: {valid_devices}",
                f"Unsupported device: '{device}'. Allowed identifiers: {valid_devices}",
            ),
            code="INVALID_DEVICE",
            status=400,
        )

    try:
        orig_h = int(params.get("original_hour", 19))
        target_h = int(params.get("target_hour", 12))
        if not (0 <= orig_h <= 23 and 0 <= target_h <= 23):
            raise ValueError(
                _tr(
                    request,
                    "Godziny muszą mieścić się w przedziale 0–23.",
                    "Hours must be between 0 and 23.",
                )
            )
    except (ValueError, TypeError) as exc:
        bound_message = _tr(
            request,
            "Godziny muszą mieścić się w przedziale 0–23.",
            "Hours must be between 0 and 23.",
        )
        message = (
            bound_message
            if str(exc) == bound_message
            else _tr(request, "Niepoprawna wartość godziny.", "Invalid hour value.")
        )
        return api_error(message, code="INVALID_HOURS", status=400)

    # Energia cyklu: podana przez użytkownika lub średnia z profilu urządzenia
    if "energy_kwh" in params and params["energy_kwh"] != "":
        try:
            energy_kwh = Decimal(str(params["energy_kwh"]))
            if energy_kwh <= 0 or energy_kwh > 20:
                raise ValueError(
                    _tr(
                        request,
                        "Energia cyklu musi być dodatnia i nie większa niż 20 kWh.",
                        "Cycle energy must be above zero and at most 20 kWh.",
                    )
                )
        except (TypeError, ValueError, InvalidOperation) as exc:
            allowed = _tr(
                request,
                "Energia cyklu musi być dodatnia i nie większa niż 20 kWh.",
                "Cycle energy must be above zero and at most 20 kWh.",
            )
            return api_error(
                allowed
                if str(exc) == allowed
                else _tr(
                    request, "Niepoprawna wartość 'energy_kwh'.", "Invalid 'energy_kwh' value."
                ),
                code="INVALID_ENERGY",
                status=400,
            )
    else:
        profile = household.DEVICE_PROFILES[device]
        min_e, max_e = profile["energy"]
        energy_kwh = Decimal(str((min_e + max_e) / 2))

    tariff_config, dynamic_prices = _tariff(request)
    today = datetime.now().replace(minute=0, second=0, microsecond=0)
    orig_price, _ = tariff_config.price_at(today.replace(hour=orig_h), dynamic_prices)
    target_price, _ = tariff_config.price_at(today.replace(hour=target_h), dynamic_prices)

    orig_cost = orig_price * energy_kwh
    target_cost = target_price * energy_kwh
    savings_per_cycle = orig_cost - target_cost

    data_dir = get_scenario_data_dir(request)
    scen = get_active_scenario(request)
    _, _, annual_events = data.load_annual(data_dir)
    annual_cycles = sum(event.device == device for event in annual_events)
    annual_savings = savings_per_cycle * annual_cycles

    in_pv_window = target_h in pv.PV_WINDOW
    in_night_valley = target_h in range(0, 6)

    return api_success(
        {
            "scenario": {
                "id": scen["id"],
                "name": scen["name"],
                "city": scen["city"],
            },
            "device": device,
            "energy_kwh": _to_float(energy_kwh),
            "original_hour": orig_h,
            "original_price_eur": _to_float(orig_price),
            "original_cost_eur": _to_float(orig_cost),
            "target_hour": target_h,
            "target_price_eur": _to_float(target_price),
            "target_cost_eur": _to_float(target_cost),
            "savings_per_cycle_eur": _to_float(savings_per_cycle),
            "estimated_annual_cycles": annual_cycles,
            "estimated_annual_savings_eur": _to_float(annual_savings, 2),
            "annual_cycles_source": _tr(
                request, "liczba zdarzeń w roku modelowym", "number of events in the modeled year"
            ),
            "in_pv_window": in_pv_window,
            "in_night_valley": in_night_valley,
            "recommendation": _tr(
                request,
                f"Koszt jednego cyklu według taryfy: {_to_float(orig_cost, 3)} EUR "
                f"o {orig_h}:00 i {_to_float(target_cost, 3)} EUR o {target_h}:00. "
                "Porównanie nie uwzględnia produkcji PV w konkretnej godzinie.",
                f"Tariff cost per cycle: {_to_float(orig_cost, 3)} EUR at {orig_h}:00 "
                f"and {_to_float(target_cost, 3)} EUR at {target_h}:00. "
                "This comparison excludes PV production at those hours.",
            ),
        }
    )


# ----------------------------------------------------------------------
# 9. Założenia i metryki systemu
# ----------------------------------------------------------------------


@require_http_methods(["GET"])
@require_api_secret
@handle_data_errors
def system_assumptions(request: HttpRequest) -> JsonResponse:
    """Zwraca parametry symulacji, urządzeń i koszty taryfowe."""
    data_dir = get_scenario_data_dir(request)
    scen = get_active_scenario(request)
    history = data.load_history(data_dir)
    forecast = data.load_forecast(data_dir)
    records, _, _ = data.load_annual(data_dir)

    household_info = scen.get("household")
    if household_info:
        household_payload = {
            "residents_count": household_info["residents_count"],
            "profile": household_info["profile"],
            "heating_type": household_info["heating_type"],
        }
    else:
        household_payload = {
            "residents_count": 6,
            "profile": _tr(
                request,
                (
                    "Trzypokoleniowy dom: dziadkowie w ciągu dnia, "
                    "pracujący rodzice, dzieci po szkole"
                ),
                (
                    "Three-generation home: grandparents at home during the day, "
                    "working parents, children after school"
                ),
            ),
            "heating_type": _tr(
                request,
                "Pompa ciepła (reaguje na temperaturę zewnętrzną)",
                "Heat pump (responds to outdoor temperature)",
            ),
        }

    return api_success(
        {
            "scenario": {
                "id": scen["id"],
                "name": scen["name"],
                "city": scen["city"],
                "country_code": scen.get("country_code", "DK"),
                "flag": scen.get("flag_emoji", "🇩🇰"),
            },
            "location": scen["city"],
            "household": household_payload,
            "device_profiles": {
                name: {
                    "energy_range_kwh": profile["energy"],
                    "duration_range_h": profile["duration"],
                }
                for name, profile in household.DEVICE_PROFILES.items()
            },
            "pv_assumptions": {
                "installation_cost_per_kwp_eur": _to_float(tariffs.PV_COST_PER_KWP),
                "export_price_per_kwh_eur": _to_float(tariffs.EXPORT_PRICE),
                "annual_opex_rate": _to_float(tariffs.PV_OPEX_RATE),
                "performance_ratio": _to_float(tariffs.PV_PERFORMANCE_RATIO),
                "recommended_window": "9:00 - 15:00",
            },
            "spans": {
                "history_hours": len(history),
                "history_start": history[0].timestamp.isoformat(),
                "history_end": history[-1].timestamp.isoformat(),
                "forecast_hours": len(forecast),
                "forecast_start": forecast[0].timestamp.isoformat(),
                "forecast_end": forecast[-1].timestamp.isoformat(),
                "annual_hours": len(records),
            },
        }
    )


@require_http_methods(["GET"])
@require_api_secret
@handle_data_errors
def system_metrics(request: HttpRequest) -> JsonResponse:
    """Zwraca metryki dokładności modelu prognostycznego wobec baseline'u."""
    data_dir = get_scenario_data_dir(request)
    scen = get_active_scenario(request)
    metrics_data = data.load_metrics(data_dir)
    return api_success(
        {
            "scenario": {
                "id": scen["id"],
                "name": scen["name"],
                "city": scen["city"],
            },
            **metrics_data,
        }
    )


# ----------------------------------------------------------------------
# 10. Scenariusze symulacji
# ----------------------------------------------------------------------


@require_http_methods(["GET"])
@require_api_secret
def scenarios_list(request: HttpRequest) -> JsonResponse:
    """Zwraca listę wszystkich 5 dostępnych scenariuszy symulacji."""
    active = get_active_scenario(request)
    items = [
        {
            "id": s["id"],
            "name": s["name"],
            "title": s.get("title", ""),
            "city": s["city"],
            "city_short": s.get("city_short", ""),
            "country_code": s.get("country_code", ""),
            "flag": s.get("flag_emoji", ""),
            "lat": s["lat"],
            "lon": s["lon"],
            "timezone": s["timezone"],
            "household": s.get("household", {}),
            "is_active": s["id"] == active["id"],
        }
        for s in SCENARIOS.values()
    ]
    return api_success({"active_scenario_id": active["id"], "scenarios": items})


@require_http_methods(["GET"])
@require_api_secret
def active_scenario_info(request: HttpRequest) -> JsonResponse:
    """Zwraca metadane aktualnie wybranego scenariusza symulacji."""
    active = get_active_scenario(request)
    return api_success(
        {
            "id": active["id"],
            "name": active["name"],
            "title": active.get("title", ""),
            "city": active["city"],
            "city_short": active.get("city_short", ""),
            "country_code": active.get("country_code", ""),
            "flag": active.get("flag_emoji", ""),
            "lat": active["lat"],
            "lon": active["lon"],
            "timezone": active["timezone"],
            "household": active.get("household", {}),
        }
    )
