import json
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from django.conf import settings

FLAG_SVGS = {
    "PL": (
        '<svg class="scenario-flag-svg" viewBox="0 0 20 14" width="20" height="14" '
        'aria-hidden="true" xmlns="http://www.w3.org/2000/svg">'
        '<rect width="20" height="14" fill="#ffffff" rx="2"/>'
        '<rect y="7" width="20" height="7" fill="#dc143c"/>'
        '<rect width="20" height="14" fill="none" stroke="rgba(0,0,0,0.18)" '
        'stroke-width="1" rx="2"/>'
        "</svg>"
    ),
    "ES": (
        '<svg class="scenario-flag-svg" viewBox="0 0 20 14" width="20" height="14" '
        'aria-hidden="true" xmlns="http://www.w3.org/2000/svg">'
        '<rect width="20" height="3.5" fill="#c60b1e" rx="2"/>'
        '<rect y="3.5" width="20" height="7" fill="#ffc400"/>'
        '<rect y="10.5" width="20" height="3.5" fill="#c60b1e"/>'
        '<circle cx="5.5" cy="7" r="1.8" fill="#c60b1e" opacity="0.85"/>'
        '<rect width="20" height="14" fill="none" stroke="rgba(0,0,0,0.18)" '
        'stroke-width="1" rx="2"/>'
        "</svg>"
    ),
    "DK": (
        '<svg class="scenario-flag-svg" viewBox="0 0 20 14" width="20" height="14" '
        'aria-hidden="true" xmlns="http://www.w3.org/2000/svg">'
        '<rect width="20" height="14" fill="#c8102e" rx="2"/>'
        '<rect x="6" width="2.5" height="14" fill="#ffffff"/>'
        '<rect y="5.75" width="20" height="2.5" fill="#ffffff"/>'
        '<rect width="20" height="14" fill="none" stroke="rgba(0,0,0,0.18)" '
        'stroke-width="1" rx="2"/>'
        "</svg>"
    ),
    "PT": (
        '<svg class="scenario-flag-svg" viewBox="0 0 20 14" width="20" height="14" '
        'aria-hidden="true" xmlns="http://www.w3.org/2000/svg">'
        '<rect width="8" height="14" fill="#006600" rx="2"/>'
        '<rect x="8" width="12" height="14" fill="#ff0000"/>'
        '<circle cx="8" cy="7" r="2.6" fill="#ffd700" stroke="#003366" stroke-width="0.5"/>'
        '<rect x="7" y="5.5" width="2" height="3" fill="#ffffff"/>'
        '<rect width="20" height="14" fill="none" stroke="rgba(0,0,0,0.18)" '
        'stroke-width="1" rx="2"/>'
        "</svg>"
    ),
}

SCENARIOS = {
    1: {
        "id": 1,
        "name": "Warszawa · Aleksandra",
        "title_pl": "Zawsze w ruchu (singielka)",
        "title_en": "Always on the Move (Single Woman)",
        "city": "Warszawa, Polska",
        "city_en": "Warsaw, Poland",
        "city_short": "Warszawa",
        "city_short_en": "Warsaw",
        "name_en": "Warsaw · Aleksandra",
        "country_code": "PL",
        "flag_emoji": "🇵🇱",
        "flag_svg": FLAG_SVGS["PL"],
        "lat": 52.2297,
        "lon": 21.0122,
        "timezone": "Europe/Warsaw",
        "folder": "scenario_1",
        "household": {
            "residents_count": 1,
            "profile": "Singielka w Warszawie: praca zdalna, aktywny tryb życia",
            "heating_type": "Klimatyzacja / sieć ciepłownicza",
        },
    },
    2: {
        "id": 2,
        "name": "Katowice · Marek i Ania",
        "title_pl": "Śląski dom rodzinny (praca zmianowa)",
        "title_en": "A Silesian Family Home (Shift Work)",
        "city": "Katowice, Polska",
        "city_en": "Katowice, Poland",
        "city_short": "Katowice",
        "city_short_en": "Katowice",
        "name_en": "Katowice · Marek and Ania",
        "country_code": "PL",
        "flag_emoji": "🇵🇱",
        "flag_svg": FLAG_SVGS["PL"],
        "lat": 50.2649,
        "lon": 19.0238,
        "timezone": "Europe/Warsaw",
        "folder": "scenario_2",
        "household": {
            "residents_count": 4,
            "profile": "Śląski dom rodzinny: 4 osoby, praca zmianowa, stabilne obciążenie",
            "heating_type": "Kocioł gazowy / pompa ciepła",
        },
    },
    3: {
        "id": 3,
        "name": "Barcelona · Anna i Robert",
        "title_pl": "Luksus pod kontrolą (sauna, basen, auto elektryczne)",
        "title_en": "Luxury Under Control (Sauna, Pool, EV)",
        "city": "Barcelona, Hiszpania",
        "city_en": "Barcelona, Spain",
        "city_short": "Barcelona",
        "city_short_en": "Barcelona",
        "name_en": "Barcelona · Anna and Robert",
        "country_code": "ES",
        "flag_emoji": "🇪🇸",
        "flag_svg": FLAG_SVGS["ES"],
        "lat": 41.3879,
        "lon": 2.1699,
        "timezone": "Europe/Madrid",
        "folder": "scenario_3",
        "household": {
            "residents_count": 2,
            "profile": "Luxury Under Control: 2 osoby, willa z basenem, sauną i ładowarką EV",
            "heating_type": "Klimatyzacja inwerterowa / pompa ciepła",
        },
    },
    4: {
        "id": 4,
        "name": "Kopenhaga · Dom Pokoleń",
        "title_pl": "Dom pełen pokoleń (trzy pokolenia)",
        "title_en": "A House Full of Generations (Three Generations)",
        "city": "Kopenhaga, Dania",
        "city_en": "Copenhagen, Denmark",
        "city_short": "Kopenhaga",
        "city_short_en": "Copenhagen",
        "name_en": "Copenhagen · Multigenerational Home",
        "country_code": "DK",
        "flag_emoji": "🇩🇰",
        "flag_svg": FLAG_SVGS["DK"],
        "lat": 55.6761,
        "lon": 12.5683,
        "timezone": "Europe/Copenhagen",
        "folder": "scenario_4",
        "household": {
            "residents_count": 6,
            "profile": (
                "Trzypokoleniowy dom: dziadkowie w ciągu dnia, pracujący rodzice, dzieci po szkole"
            ),
            "heating_type": "Pompa ciepła (reaguje na temperaturę zewnętrzną)",
        },
    },
    5: {
        "id": 5,
        "name": "Lizbona · Ola i Tomek",
        "title_pl": "Nigdy sami w domu (z psem)",
        "title_en": "Never Home Alone (With a Dog)",
        "city": "Lizbona, Portugalia",
        "city_en": "Lisbon, Portugal",
        "city_short": "Lizbona",
        "city_short_en": "Lisbon",
        "name_en": "Lisbon · Ola and Tomek",
        "country_code": "PT",
        "flag_emoji": "🇵🇹",
        "flag_svg": FLAG_SVGS["PT"],
        "lat": 38.7223,
        "lon": -9.1393,
        "timezone": "Europe/Lisbon",
        "folder": "scenario_5",
        "household": {
            "residents_count": 2,
            "profile": "Home Alone – But Not Really: 2 osoby pracujące zdalnie z psem",
            "heating_type": "Klimatyzacja / ogrzewanie elektryczne",
        },
    },
}


def localized_scenario(scenario: dict, lang: str) -> dict:
    """Return display labels without changing the source scenario definition."""
    result = scenario.copy()
    result["title"] = scenario[f"title_{lang}"]
    if lang == "en":
        result["name"] = scenario["name_en"]
        result["city"] = scenario["city_en"]
        result["city_short"] = scenario["city_short_en"]
    return result


_CURRENT_REQUEST: ContextVar = ContextVar("current_request", default=None)
_ACTIVE_SCENARIO_OVERRIDE: ContextVar = ContextVar("active_scenario_override", default=None)


def set_current_request(request) -> None:
    _CURRENT_REQUEST.set(request)


def get_current_request():
    return _CURRENT_REQUEST.get()


def set_active_scenario_id(scenario_id: int | None) -> None:
    _ACTIVE_SCENARIO_OVERRIDE.set(scenario_id)


def get_active_scenario_id_override() -> int | None:
    return _ACTIVE_SCENARIO_OVERRIDE.get()


def extract_scenario_id(
    request: Any = None,
    scenario: int | str | dict | None = None,
    params: dict | None = None,
) -> int:
    """Przechwytuje ID scenariusza ze wszystkich źródeł:

    argumentu, parametrów, GET, POST, JSON body, nagłówków, sesji, ciasteczek lub ContextVar.
    """
    # 1. Bezpośrednio przekazany scenariusz
    if isinstance(scenario, dict) and "id" in scenario:
        try:
            scen_id = int(scenario["id"])
            if scen_id in SCENARIOS:
                return scen_id
        except (ValueError, TypeError):
            pass
    elif scenario is not None:
        try:
            scen_id = int(scenario)
            if scen_id in SCENARIOS:
                return scen_id
        except (ValueError, TypeError):
            pass

    # 2. Słownik params (np. sparsowany payload z API)
    if isinstance(params, dict):
        val = params.get("scenario") or params.get("scenario_id") or params.get("scenariusz")
        if val is not None:
            try:
                scen_id = int(val)
                if scen_id in SCENARIOS:
                    return scen_id
            except (ValueError, TypeError):
                pass

    # 3. Z żądania HTTP
    req = request if request is not None else get_current_request()
    if req is not None:
        # A. Query params GET
        get_params = getattr(req, "GET", {})
        val = (
            get_params.get("scenario")
            or get_params.get("scenario_id")
            or get_params.get("scenariusz")
        )
        if val is not None:
            try:
                scen_id = int(val)
                if scen_id in SCENARIOS:
                    return scen_id
            except (ValueError, TypeError):
                pass

        # B. POST params (formularze)
        post_params = getattr(req, "POST", {})
        val = (
            post_params.get("scenario")
            or post_params.get("scenario_id")
            or post_params.get("scenariusz")
        )
        if val is not None:
            try:
                scen_id = int(val)
                if scen_id in SCENARIOS:
                    return scen_id
            except (ValueError, TypeError):
                pass

        # C. JSON body (żądania POST/PUT typu application/json)
        content_type = getattr(req, "content_type", "") or ""
        if "json" in content_type:
            try:
                cached = getattr(req, "_cached_json_dict", None)
                if cached is None:
                    raw = getattr(req, "body", b"")
                    if raw:
                        parsed = json.loads(raw.decode("utf-8"))
                        cached = parsed if isinstance(parsed, dict) else {}
                    else:
                        cached = {}
                    req._cached_json_dict = cached
                if isinstance(cached, dict):
                    val = (
                        cached.get("scenario")
                        or cached.get("scenario_id")
                        or cached.get("scenariusz")
                    )
                    if val is not None:
                        scen_id = int(val)
                        if scen_id in SCENARIOS:
                            return scen_id
            except Exception:
                pass

        # D. Nagłówki HTTP (np. X-Scenario-ID, X-Scenario)
        headers = getattr(req, "headers", {})
        header_val = headers.get("X-Scenario-ID") or headers.get("X-Scenario")
        if header_val is not None:
            try:
                scen_id = int(header_val)
                if scen_id in SCENARIOS:
                    return scen_id
            except (ValueError, TypeError):
                pass

        # E. Sesja Django
        if hasattr(req, "session"):
            scen_id = req.session.get("active_scenario")
            if scen_id in SCENARIOS:
                return scen_id

        # F. Ciasteczka przeglądarki
        cookies = getattr(req, "COOKIES", {})
        cookie_val = cookies.get("active_scenario")
        if cookie_val is not None:
            try:
                scen_id = int(cookie_val)
                if scen_id in SCENARIOS:
                    return scen_id
            except (ValueError, TypeError):
                pass

    # 4. ContextVar override (np. ustawiony programistycznie)
    override = get_active_scenario_id_override()
    if override in SCENARIOS:
        return override

    # 5. Globalny aktywny scenariusz serwera (zsynchronizowany z wyborem w UI / pliku stanu)
    return get_server_active_scenario()


_STATE_FILENAME = ".active_scenario"


def _state_file_path() -> Path:
    return settings.DEMO_DATA_DIR / _STATE_FILENAME


def set_server_active_scenario(scenario_id: int) -> None:
    """Ustawia aktywny scenariusz globalnie na serwerze i zapisuje w pliku stanu."""
    if scenario_id in SCENARIOS:
        try:
            path = _state_file_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(scenario_id), encoding="utf-8")
        except OSError:
            pass


def get_server_active_scenario() -> int:
    """Zwraca aktywny scenariusz serwera (z pliku stanu lub domyślny 4)."""
    try:
        path = _state_file_path()
        if path.is_file():
            val = int(path.read_text(encoding="utf-8").strip())
            if val in SCENARIOS:
                return val
    except Exception:
        pass
    return 4


def capture_scenario(
    request: Any = None,
    scenario: int | str | dict | None = None,
    params: dict | None = None,
) -> dict:
    """Przechwytuje scenariusz ze wszystkich źródeł i zwraca jego definicję."""
    scen_id = extract_scenario_id(request, scenario, params)
    return SCENARIOS.get(scen_id, SCENARIOS[4])


def capture_scenario_data_dir(
    request: Any = None,
    scenario: int | str | dict | None = None,
    params: dict | None = None,
) -> Path:
    """Przechwytuje dany scenariusz i zwraca ścieżkę do jego katalogu danych (data_dir)."""
    scen = capture_scenario(request, scenario, params)
    path = settings.DEMO_DATA_DIR / scen["folder"]
    if scen["id"] == 4 and not path.exists():
        return settings.DEMO_DATA_DIR
    return path


def capture_scenario_context(
    request: Any = None,
    scenario: int | str | dict | None = None,
    params: dict | None = None,
) -> tuple[dict, Path]:
    """Zwraca krotkę (scenariusz, data_dir) przechwyconą z żądania lub parametrów."""
    scen = capture_scenario(request, scenario, params)
    path = settings.DEMO_DATA_DIR / scen["folder"]
    if scen["id"] == 4 and not path.exists():
        path = settings.DEMO_DATA_DIR
    return scen, path


# Aliasy zapewniające pełną kompatybilność:
get_active_scenario = capture_scenario
get_scenario_data_dir = capture_scenario_data_dir
