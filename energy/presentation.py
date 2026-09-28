"""Labels for identifiers stored in demo CSV files in Polish and English."""

DEVICE_NAMES_EN = {
    "Zmywarka": "Dishwasher",
    "Pralka": "Washing machine",
    "Suszarka": "Tumble dryer",
}
DEVICE_NAMES_PL = {
    "Zmywarka": "Zmywarka",
    "Pralka": "Pralka",
    "Suszarka": "Suszarka",
}

EVENT_NAMES_EN = {
    "goście": "guests",
    "wyjazd rodziny": "family trip",
    "dziadkowie poza domem": "grandparents out",
    "praca zdalna": "working from home",
    "zmywarka": "dishwasher",
    "pralka": "washing machine",
    "suszarka": "tumble dryer",
}

DEVICE_NAMES = DEVICE_NAMES_EN
EVENT_NAMES = EVENT_NAMES_EN

DEVICE_NAMES = DEVICE_NAMES_EN
EVENT_NAMES = EVENT_NAMES_EN


def device_name(name: str, lang: str = "en") -> str:
    if lang == "en":
        return DEVICE_NAMES_EN.get(name, name)
    return DEVICE_NAMES_PL.get(name, name)


def event_names(events: str, lang: str = "en") -> str:
    if lang == "en":
        return "; ".join(
            EVENT_NAMES_EN.get(item.strip(), item.strip())
            for item in events.split(";")
            if item.strip()
        )
    return events
