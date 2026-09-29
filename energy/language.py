"""Language selection shared by HTML views and the mobile API."""

from django.utils import translation


def selected_language(request) -> str:
    if request.path.startswith("/api/"):
        explicit = request.GET.get("lang")
        if explicit in {"pl", "en"}:
            return explicit
        for choice in request.headers.get("Accept-Language", "").split(","):
            code = choice.split(";", 1)[0].strip().split("-", 1)[0].lower()
            if code in {"pl", "en"}:
                return code
        return "pl"
    lang = request.session.get("django_language") or request.COOKIES.get("django_language")
    return lang if lang in {"pl", "en"} else "pl"


class LanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from energy.scenarios import set_current_request

        set_current_request(request)
        lang = selected_language(request)
        previous = translation.get_language()
        translation.activate(lang)
        request.LANGUAGE_CODE = lang
        try:
            return self.get_response(request)
        finally:
            set_current_request(None)
            translation.activate(previous)
