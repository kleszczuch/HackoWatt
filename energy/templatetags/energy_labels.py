from django import template

from energy.currency import from_eur
from energy.presentation import event_names

register = template.Library()


@register.filter
def display_currency(value, currency: str = "EUR"):
    """Przelicza wartość EUR wyłącznie do prezentacji w szablonie."""
    if value is None:
        return None
    return from_eur(value, currency)


@register.filter
def english_events(value: str) -> str:
    return event_names(value, lang="en")


@register.filter
def localized_events(value: str, lang: str = "pl") -> str:
    return event_names(value, lang=lang)
