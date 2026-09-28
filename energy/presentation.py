"""English labels for Polish identifiers stored in demo CSV files."""

DEVICE_NAMES = {
    "Zmywarka": "Dishwasher",
    "Pralka": "Washing machine",
    "Suszarka": "Tumble dryer",
}
EVENT_NAMES = {
    "goście": "guests",
    "wyjazd rodziny": "family trip",
    "dziadkowie poza domem": "grandparents out",
    "praca zdalna": "working from home",
    "zmywarka": "dishwasher",
    "pralka": "washing machine",
    "suszarka": "tumble dryer",
}


def device_name(name: str) -> str:
    return DEVICE_NAMES.get(name, name)


def event_names(events: str) -> str:
    return "; ".join(
        EVENT_NAMES.get(item.strip(), item.strip()) for item in events.split(";") if item.strip()
    )
