from django import template

from energy.presentation import event_names

register = template.Library()


@register.filter
def english_events(value: str) -> str:
    return event_names(value, lang="en")


@register.filter
def localized_events(value: str, lang: str = "pl") -> str:
    return event_names(value, lang=lang)
