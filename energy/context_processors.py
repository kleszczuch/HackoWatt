from django.http import HttpRequest

from energy.currency import SYMBOLS, selected_currency
from energy.language import selected_language
from energy.scenarios import SCENARIOS, capture_scenario, localized_scenario


def language_context(request: HttpRequest) -> dict:
    lang = selected_language(request)
    active_scenario = localized_scenario(capture_scenario(request), lang)
    currency = selected_currency(request)
    return {
        "current_lang": lang,
        "is_pl": lang == "pl",
        "is_en": lang == "en",
        "current_currency": currency,
        "currency_symbol": SYMBOLS[currency],
        "active_scenario": active_scenario,
        "all_scenarios": [localized_scenario(scenario, lang) for scenario in SCENARIOS.values()],
    }
