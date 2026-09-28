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
        "title": "Always on the Move (Singielka)",
        "city": "Warszawa, Polska",
        "city_short": "Warszawa",
        "country_code": "PL",
        "flag_emoji": "🇵🇱",
        "flag_svg": FLAG_SVGS["PL"],
        "lat": 52.2297,
        "lon": 21.0122,
        "timezone": "Europe/Warsaw",
        "folder": "scenario_1",
    },
    2: {
        "id": 2,
        "name": "Katowice · Marek i Ania",
        "title": "A Silesian Family Home (Praca zmianowa)",
        "city": "Katowice, Polska",
        "city_short": "Katowice",
        "country_code": "PL",
        "flag_emoji": "🇵🇱",
        "flag_svg": FLAG_SVGS["PL"],
        "lat": 50.2649,
        "lon": 19.0238,
        "timezone": "Europe/Warsaw",
        "folder": "scenario_2",
    },
    3: {
        "id": 3,
        "name": "Barcelona · Anna i Robert",
        "title": "Luxury Under Control (Sauna, Basen, EV)",
        "city": "Barcelona, Hiszpania",
        "city_short": "Barcelona",
        "country_code": "ES",
        "flag_emoji": "🇪🇸",
        "flag_svg": FLAG_SVGS["ES"],
        "lat": 41.3879,
        "lon": 2.1699,
        "timezone": "Europe/Madrid",
        "folder": "scenario_3",
    },
    4: {
        "id": 4,
        "name": "Kopenhaga · Dom Pokoleń",
        "title": "A House Full of Generations (3 pokolenia)",
        "city": "Kopenhaga, Dania",
        "city_short": "Kopenhaga",
        "country_code": "DK",
        "flag_emoji": "🇩🇰",
        "flag_svg": FLAG_SVGS["DK"],
        "lat": 55.6761,
        "lon": 12.5683,
        "timezone": "Europe/Copenhagen",
        "folder": "scenario_4",
    },
    5: {
        "id": 5,
        "name": "Lizbona · Ola i Tomek",
        "title": "Home Alone – But Not Really (Z psem)",
        "city": "Lizbona, Portugalia",
        "city_short": "Lizbona",
        "country_code": "PT",
        "flag_emoji": "🇵🇹",
        "flag_svg": FLAG_SVGS["PT"],
        "lat": 38.7223,
        "lon": -9.1393,
        "timezone": "Europe/Lisbon",
        "folder": "scenario_5",
    },
}


def get_active_scenario(request):
    """Pobiera aktywny scenariusz z sesji użytkownika (domyślnie 4 - Kopenhaga)."""
    scen_id = request.session.get("active_scenario", 4)
    return SCENARIOS.get(scen_id, SCENARIOS[4])


def get_scenario_data_dir(request):
    """Zwraca ścieżkę do folderu data wybranego scenariusza."""
    scen = get_active_scenario(request)
    path = settings.DEMO_DATA_DIR / scen["folder"]
    if scen["id"] == 4 and not path.exists():
        return settings.DEMO_DATA_DIR
    return path
