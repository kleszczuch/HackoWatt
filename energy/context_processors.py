from django.http import HttpRequest

from energy.language import selected_language
from energy.scenarios import SCENARIOS, get_active_scenario, localized_scenario


def language_context(request: HttpRequest) -> dict:
    lang = selected_language(request)
    active_scenario = localized_scenario(get_active_scenario(request), lang)
    return {
        "current_lang": lang,
        "is_pl": lang == "pl",
        "is_en": lang == "en",
        "active_scenario": active_scenario,
        "all_scenarios": [localized_scenario(scenario, lang) for scenario in SCENARIOS.values()],
    }
