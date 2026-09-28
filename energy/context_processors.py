from django.http import HttpRequest

from energy.scenarios import SCENARIOS, get_active_scenario


def language_context(request: HttpRequest) -> dict:
    lang = request.session.get("django_language") or request.COOKIES.get("django_language") or "pl"
    if lang not in ("pl", "en"):
        lang = "pl"
    active_scenario = get_active_scenario(request)
    return {
        "current_lang": lang,
        "is_pl": lang == "pl",
        "is_en": lang == "en",
        "active_scenario": active_scenario,
        "all_scenarios": list(SCENARIOS.values()),
    }
