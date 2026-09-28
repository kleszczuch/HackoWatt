from django.http import HttpRequest


def language_context(request: HttpRequest) -> dict:
    lang = request.session.get("django_language") or request.COOKIES.get("django_language") or "pl"
    if lang not in ("pl", "en"):
        lang = "pl"
    return {
        "current_lang": lang,
        "is_pl": lang == "pl",
        "is_en": lang == "en",
    }
