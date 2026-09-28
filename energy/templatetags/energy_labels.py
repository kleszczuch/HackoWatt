from django import template

from energy.presentation import event_names

register = template.Library()


@register.filter
def english_events(value: str) -> str:
    return event_names(value)
