from pathlib import Path
from django.conf import settings

SCENARIOS = {
    1: {
        "id": 1,
        "name": "Warszawa · Aleksandra",
        "title": "Always on the Move (Singielka)",
        "city": "Warszawa, Polska",
        "lat": 52.2297,
        "lon": 21.0122,
        "folder": "scenario_1",
    },
    2: {
        "id": 2,
        "name": "Katowice · Marek i Ania",
        "title": "A Silesian Family Home (Praca zmianowa)",
        "city": "Katowice, Polska",
        "lat": 50.2649,
        "lon": 19.0238,
        "folder": "scenario_2",
    },
    3: {
        "id": 3,
        "name": "Barcelona · Anna i Robert",
        "title": "Luxury Under Control (Sauna, Basen, EV)",
        "city": "Barcelona, Hiszpania",
        "lat": 41.3879,
        "lon": 2.1699,
        "folder": "scenario_3",
    },
    4: {
        "id": 4,
        "name": "Kopenhaga · Dom Pokoleń",
        "title": "A House Full of Generations (3 pokolenia)",
        "city": "Kopenhaga, Dania",
        "lat": 55.6761,
        "lon": 12.5683,
        "folder": "scenario_4",
    },
    5: {
        "id": 5,
        "name": "Lizbona · Ola i Tomek",
        "title": "Home Alone – But Not Really (Z psem)",
        "city": "Lizbona, Portugalia",
        "lat": 38.7223,
        "lon": -9.1393,
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
    path = settings.BASE_DIR / "data" / scen["folder"]
    path.mkdir(parents=True, exist_ok=True)
    return path