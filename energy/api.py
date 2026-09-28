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
from energy.charts import CATEGORY_LABELS
from energy.explanations import explain_peaks
from energy.forms import DateRangeForm, HorizonForm, PvForm


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
                "Wymagana autoryzacja za pomocą tokenu Bearer "
                "(nagłówek: Authorization: Bearer <token>).",
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
        except (FileNotFoundError, data.DemoDataError) as exc:
            return api_error(
                f"Błąd danych demonstracyjnych: {exc}",
                code="DATA_NOT_FOUND",
                status=503,
            )

    return _wrapped_view


def _to_float(val: Decimal | float | int | None, round_digits: int = 3) -> float | None:
    if val is None:
        return None
    return round(float(val), round_digits)


def _parse_params(request: HttpRequest) -> tuple[dict, str | None]:
    """Pobiera parametry z query string (GET) lub z ciała JSON / formularza (POST)."""
    if request.method == "GET":
        return request.GET.dict(), None
    if not request.body:
        return request.POST.dict(), None
    try:
        data_dict = json.loads(request.body.decode("utf-8"))
        if not isinstance(data_dict, dict):
            return {}, "Ciało żądania musi być obiektem JSON."
        return data_dict, None
    except json.JSONDecodeError as exc:
        return {}, f"Niepoprawny format JSON: {exc}"


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
    now_hour = datetime.now().hour

    def band(price: Decimal) -> tuple[str, str]:
        if price == low:
            return "green", "Najniższa stawka"
        if price == high:
            return "red", "Najwyższa stawka"
        return "yellow", "Stawka pośrednia"

    current_code, current_title = band(prices[now_hour])
    timeline = [
        {
            "hour": hour,
            "hour_label": f"{hour:02d}:00 – {(hour + 1):02d}:00",
            "status_code": band(price)[0],
            "badge": band(price)[1],
            "price_per_kwh": _to_float(price),
            "is_current": hour == now_hour,
        }
        for hour, price in enumerate(prices)
    ]
    return api_success(
        {
            "current_hour": {
                "hour": now_hour,
                "status_code": current_code,
                "status_title": current_title,
                "price_per_kwh": _to_float(prices[now_hour]),
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
def devices_guidance(request: HttpRequest) -> JsonResponse:
    """Rzeczywiste liczby cykli i energii w wygenerowanym roku modelowym."""
    records, _, events = data.load_annual()
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
                "device": display_name,
                "annual_events": len(selected),
                "annual_energy_kwh": _to_float(total),
                "energy_per_cycle_kwh": _to_float(total / len(selected)) if selected else None,
                "energy_started_outside_pv_window_kwh": _to_float(outside),
            }
        )
    for label, index in (("Komputery i RTV", 4), ("Gotowanie", 3)):
        total = sum((record.categories[index] for record in records), Decimal(0))
        devices.append({"device": label, "annual_energy_kwh": _to_float(total)})
    return api_success({"devices": devices, "pv_window": "09:00–15:00"})


# ----------------------------------------------------------------------
# 3. Pulpit mobilny / Status bieżący
# ----------------------------------------------------------------------


@require_http_methods(["GET"])
@require_api_secret
@handle_data_errors
def dashboard_summary(request: HttpRequest) -> JsonResponse:
    """Zwraca skonsolidowany status na ekran główny aplikacji mobilnej."""
    history = data.load_history()
    forecast = data.load_forecast()
    weather_history = data.load_weather_history()
    weather_forecast = data.load_weather_forecast()

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
    peaks = explain_peaks(forecast_24h, weather_24h, top=1)
    next_peak = None
    if peaks:
        peak = peaks[0]
        next_peak = {
            "timestamp": peak.timestamp.isoformat(),
            "total_kwh": _to_float(peak.total),
            "explanation": peak.sentence,
        }

    # Bieżąca taryfa i prosta ocena
    current_hour_idx = datetime.now().hour
    current_price = tariffs.price_for_hour(current_hour_idx)
    if current_price >= Decimal("0.40"):
        period_label = "Szczyt popołudniowy (drogo)"
        period_color = "red"
    elif current_price <= Decimal("0.18"):
        period_label = "Dolina nocna (bardzo tanio)"
        period_color = "green"
    elif 9 <= current_hour_idx < 15:
        period_label = "Taryfa dzienna (okno modelu PV)"
        period_color = "green"
    else:
        period_label = "Standardowa stawka dzienna"
        period_color = "yellow"

    annual_records, annual_weather, annual_events = data.load_annual()
    pv_preview = pv.simulate(annual_records, annual_weather, annual_events, Decimal(5))

    # Dominująca kategoria w ostatniej godzinie
    max_cat_idx = max(range(len(last_hour.categories)), key=lambda i: last_hour.categories[i])
    category_key = household.CATEGORIES[max_cat_idx]
    category_label = (
        CATEGORY_LABELS[max_cat_idx] if max_cat_idx < len(CATEGORY_LABELS) else category_key
    )
    dominant_category = {
        "key": category_key,
        "label": category_label,
        "kwh": _to_float(last_hour.categories[max_cat_idx]),
    }

    return api_success(
        {
            "last_reading": {
                "timestamp": last_hour.timestamp.isoformat(),
                "total_kwh": _to_float(last_hour.total),
                "temperature_c": last_weather.temperature if last_weather else None,
                "dominant_category": dominant_category,
                "events": last_hour.events,
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
    history = data.load_history()
    weather_history = data.load_weather_history()
    weather_by_time = {w.timestamp: w for w in weather_history}

    start_param = request.GET.get("start")
    end_param = request.GET.get("end")

    if start_param or end_param:
        form = DateRangeForm(request.GET)
        if not form.is_valid():
            return api_error(
                "Niepoprawny zakres dat.",
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
            raise ValueError("Numer strony musi być większy lub równy 1.")
        if page_size < 1 or page_size > 168:
            raise ValueError("Rozmiar strony 'page_size' musi wynosić od 1 do 168.")
    except (ValueError, TypeError) as exc:
        return api_error(str(exc), code="INVALID_PAGINATION", status=400)

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
                "events": r.events,
            }
        )

    return api_success(
        {
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
    horizon_form = HorizonForm({"horyzont": horizon_param})
    if not horizon_form.is_valid():
        return api_error(
            "Niepoprawny horyzont prognozy. Dopuszczalne wartości to: 24, 72, 168.",
            code="INVALID_HORIZON",
            status=400,
        )

    horizon_hours = int(horizon_form.cleaned_data["horyzont"])
    forecast = data.load_forecast()
    weather_forecast = data.load_weather_forecast()

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
    peaks = explain_peaks(forecast_slice, weather_slice, top=3)
    peaks_payload = [
        {
            "timestamp": p.timestamp.isoformat(),
            "total_kwh": _to_float(p.total),
            "explanation": p.sentence,
        }
        for p in peaks
    ]

    items = []
    for r in forecast_slice:
        w = weather_by_time.get(r.timestamp)
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
                "tariff_price_eur": _to_float(tariffs.price_for_hour(r.timestamp.hour)),
            }
        )

    return api_success(
        {
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
    periods = []
    for start_h, end_h, price in tariffs.TARIFF_PERIODS:
        label = "Standardowa dzienna"
        if price >= Decimal("0.40"):
            label = "Szczyt popołudniowy (najdroższa)"
        elif price <= Decimal("0.18"):
            label = "Dolina nocna (najtańsza)"
        elif start_h >= 22:
            label = "Strefa wieczorna"

        periods.append(
            {
                "start_hour": start_h,
                "end_hour": end_h,
                "price_per_kwh": _to_float(price),
                "label": label,
            }
        )

    now_hour = datetime.now().hour
    current_price = tariffs.price_for_hour(now_hour)

    return api_success(
        {
            "currency": tariffs.CURRENCY,
            "current_hour": now_hour,
            "current_price_eur": _to_float(current_price),
            "periods": periods,
            "recommendations": {
                "cheapest_window": {
                    "start_hour": 0,
                    "end_hour": 6,
                    "price_per_kwh": 0.18,
                },
                "pv_window": {
                    "start_hour": 9,
                    "end_hour": 15,
                    "price_per_kwh": 0.28,
                },
                "peak_window": {
                    "start_hour": 17,
                    "end_hour": 22,
                    "price_per_kwh": 0.40,
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
    records, weather_annual, events = data.load_annual()
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
        }
    )
    if not form.is_valid():
        return api_error(
            "Niepoprawne parametry symulacji PV.",
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
    storage = pv.StorageConfig(
        form.cleaned_data["magazyn_kwh"],
        form.cleaned_data["magazyn_moc_kw"],
        form.cleaned_data["magazyn_koszt_eur"],
    )

    sim_result = pv.simulate(records, weather_annual, events, kwp, storage)
    effects = pv.device_effects(records, weather_annual, events, kwp, storage)
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
        "kwp": _to_float(kwp, 1),
        "currency": tariffs.CURRENCY,
        "storage_capacity_kwh": _to_float(storage.capacity_kwh),
        "storage_power_kw": _to_float(storage.power_kw),
        "investment_eur": _to_float(sim_result.investment_eur, 2),
        "annual_consumption_kwh": _to_float(sim_result.consumption_kwh),
        "annual_production_kwh": _to_float(sim_result.production_kwh),
        "variant_a": {
            "name": "Obecne nawyki",
            "self_consumption_kwh": _to_float(var_a.self_kwh),
            "exported_kwh": _to_float(var_a.exported_kwh),
            "grid_kwh": _to_float(var_a.grid_kwh),
            "coverage_percent": _to_float(sim_result.coverage_a, 2),
            "savings_eur": _to_float(var_a.savings, 2),
            "payback_years": _to_float(var_a.payback_years, 1),
        },
        "variant_b": {
            "name": "Przesunięcie elastycznych urządzeń (okno 9:00–15:00)",
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
                "device": effect.device,
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
            response_data["week_profile_warning"] = (
                f"Brak pełnego tygodnia danych dla miesiąca {month}."
            )

    return api_success(response_data)


@require_http_methods(["GET"])
@require_api_secret
@handle_data_errors
def pv_variants_list(request: HttpRequest) -> JsonResponse:
    """Zwraca tabelę porównawczą typowych mocy instalacji PV (2..10 kWp)."""
    records, weather_annual, events = data.load_annual()
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

    return api_success({"currency": tariffs.CURRENCY, "variants": items})


# ----------------------------------------------------------------------
# 8. Urządzenia elastyczne i kalkulator przesunięcia (GET/POST)
# ----------------------------------------------------------------------


@require_http_methods(["GET"])
@require_api_secret
@handle_data_errors
def flexible_events_list(request: HttpRequest) -> JsonResponse:
    """Zwraca listę zarejestrowanych cykli pracy urządzeń elastycznych."""
    events = data.load_history_events()

    device_filter = request.GET.get("device", "").strip()
    if device_filter:
        events = [e for e in events if e.device.lower() == device_filter.lower()]

    page_param = request.GET.get("page", 1)
    page_size_param = request.GET.get("page_size", 25)

    try:
        page_num = int(page_param)
        page_size = int(page_size_param)
        if page_num < 1:
            raise ValueError("Numer strony musi być większy lub równy 1.")
        if page_size < 1 or page_size > 100:
            raise ValueError("Rozmiar strony 'page_size' musi wynosić od 1 do 100.")
    except (ValueError, TypeError) as exc:
        return api_error(str(exc), code="INVALID_PAGINATION", status=400)

    paginator = Paginator(events, page_size)
    try:
        page_obj = paginator.get_page(page_num)
    except (EmptyPage, PageNotAnInteger) as exc:
        return api_error(str(exc), code="INVALID_PAGE", status=400)

    items = [
        {
            "device": e.device,
            "day": e.day.isoformat(),
            "start_hour": e.start_hour,
            "duration_h": e.duration_h,
            "energy_kwh": _to_float(e.energy_kwh),
        }
        for e in page_obj.object_list
    ]

    return api_success(
        {
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
def shift_simulation(request: HttpRequest) -> JsonResponse:
    """Kalkulator korzyści z przesunięcia pracy urządzenia (dostępny przez prosty GET lub POST)."""
    params, parse_err = _parse_params(request)
    if parse_err:
        return api_error(parse_err, code="INVALID_PARAMS", status=400)

    device = params.get("device", "").strip()
    if device not in household.DEVICE_PROFILES:
        valid_devices = ", ".join(household.DEVICE_PROFILES.keys())
        return api_error(
            f"Nieobsługiwane urządzenie: '{device}'. Dozwolone: {valid_devices}",
            code="INVALID_DEVICE",
            status=400,
        )

    try:
        orig_h = int(params.get("original_hour", 19))
        target_h = int(params.get("target_hour", 12))
        if not (0 <= orig_h <= 23 and 0 <= target_h <= 23):
            raise ValueError("Godziny muszą mieścić się w przedziale 0–23.")
    except (ValueError, TypeError) as exc:
        return api_error(str(exc), code="INVALID_HOURS", status=400)

    # Energia cyklu: podana przez użytkownika lub średnia z profilu urządzenia
    if "energy_kwh" in params and params["energy_kwh"] != "":
        try:
            energy_kwh = Decimal(str(params["energy_kwh"]))
            if energy_kwh <= 0 or energy_kwh > 20:
                raise ValueError("Energia cyklu musi być dodatnia i nie większa niż 20 kWh.")
        except (TypeError, ValueError, InvalidOperation) as exc:
            return api_error(
                f"Niepoprawna wartość 'energy_kwh': {exc}",
                code="INVALID_ENERGY",
                status=400,
            )
    else:
        profile = household.DEVICE_PROFILES[device]
        min_e, max_e = profile["energy"]
        energy_kwh = Decimal(str((min_e + max_e) / 2))

    orig_price = tariffs.price_for_hour(orig_h)
    target_price = tariffs.price_for_hour(target_h)

    orig_cost = orig_price * energy_kwh
    target_cost = target_price * energy_kwh
    savings_per_cycle = orig_cost - target_cost

    _, _, annual_events = data.load_annual()
    annual_cycles = sum(event.device == device for event in annual_events)
    annual_savings = savings_per_cycle * annual_cycles

    in_pv_window = target_h in pv.PV_WINDOW
    in_night_valley = target_h in range(0, 6)

    return api_success(
        {
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
            "annual_cycles_source": "liczba zdarzeń w roku modelowym",
            "in_pv_window": in_pv_window,
            "in_night_valley": in_night_valley,
            "recommendation": (
                f"Koszt jednego cyklu według taryfy: {_to_float(orig_cost, 3)} EUR "
                f"o {orig_h}:00 i {_to_float(target_cost, 3)} EUR o {target_h}:00. "
                "Porównanie nie uwzględnia produkcji PV w konkretnej godzinie."
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
    history = data.load_history()
    forecast = data.load_forecast()
    records, _, _ = data.load_annual()

    return api_success(
        {
            "location": "Kopenhaga, Dania",
            "household": {
                "residents_count": 6,
                "profile": (
                    "Trzypokoleniowy dom: dziadkowie w ciągu dnia, "
                    "pracujący rodzice, dzieci po szkole"
                ),
                "heating_type": "Pompa ciepła (reaguje na temperaturę zewnętrzną)",
            },
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
    metrics_data = data.load_metrics()
    return api_success(metrics_data)
