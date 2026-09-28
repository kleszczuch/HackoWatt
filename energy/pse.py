"""Pobieranie cen RCE z API PSE (rynek polski) — wyłącznie dla komend offline.

Aplikacja nigdy nie pobiera cen podczas obsługi HTTP; ten moduł używa komenda
`fetch_tariff_prices`, a wyniki trafiają do `data/tariff_prices.json`.
"""

import json
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

RCE_URL = "https://api.raporty.pse.pl/api/rce-pln"
PRICES_FILENAME = "tariff_prices.json"
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
SOURCE_LABEL = "PSE RCE (api.raporty.pse.pl)"
PAGE_SIZE = 5000


class PseFetchError(RuntimeError):
    """Pobieranie cen RCE z API PSE nie powiodło się."""


def _get_page(url: str) -> dict:
    """Pobiera jedną stronę JSON z API PSE, zgłaszając PseFetchError w razie problemu."""
    try:
        with urlopen(url, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise PseFetchError(f"Nie udało się pobrać cen RCE z PSE: {exc}") from exc


def fetch_rce(start: date, end: date) -> list[dict]:
    """Pobiera rekordy RCE (15-minutowe lub godzinowe) dla zakresu dat biznesowych."""
    date_filter = f"business_date ge '{start.isoformat()}' and business_date le '{end.isoformat()}'"
    url = f"{RCE_URL}?{urlencode({'$filter': date_filter, '$first': PAGE_SIZE})}"
    rows: list[dict] = []
    while url:
        payload = _get_page(url)
        value = payload.get("value")
        if not isinstance(value, list):
            raise PseFetchError("Odpowiedź PSE nie ma oczekiwanej listy „value”.")
        rows.extend(value)
        url = payload.get("nextLink")
    if not rows:
        raise PseFetchError(f"PSE nie zwróciło cen RCE dla zakresu {start} – {end}.")
    return rows


def parse_rce_rows(rows: list[dict]) -> dict[datetime, Decimal]:
    """Mapuje rekordy PSE na {pełna godzina: średnia cena PLN/MWh}.

    Godzinę wyznacza początek okresu z pola „period” (np. „00:15 - 00:30”),
    bo „dtime” wskazuje koniec okresu. Rekordy 15-minutowe agreguje średnią.
    """
    hourly: dict[datetime, list[Decimal]] = {}
    try:
        for row in rows:
            start_label = row["period"].split(" - ")[0].strip()
            # Przy zmianie czasu PSE dopisuje literę do godziny („02a:15”, „02b:00”).
            start_label = re.sub(r"[^0-9:]", "", start_label)
            moment = datetime.strptime(f"{row['business_date']} {start_label}", "%Y-%m-%d %H:%M")
            hour = moment.replace(minute=0, second=0, microsecond=0)
            hourly.setdefault(hour, []).append(Decimal(str(row["rce_pln"])))
    except (KeyError, TypeError, ValueError) as exc:
        raise PseFetchError(f"Rekord PSE nie ma oczekiwanych pól: {exc}") from exc
    return {hour: sum(values) / len(values) for hour, values in sorted(hourly.items()) if values}


def pln_mwh_to_eur_kwh(price_pln_mwh: Decimal, eurpln: Decimal) -> Decimal:
    """Przelicza cenę z PLN/MWh na €/kWh stałym kursem."""
    return (price_pln_mwh / Decimal(1000) / eurpln).quantize(Decimal("0.00001"))


def hourly_prices_eur(rows: list[dict], eurpln: Decimal) -> dict[datetime, Decimal]:
    """Zwraca godzinowe ceny €/kWh z rekordów PSE."""
    return {hour: pln_mwh_to_eur_kwh(price, eurpln) for hour, price in parse_rce_rows(rows).items()}


def write_prices_json(prices: dict[datetime, Decimal], path: Path | str) -> None:
    """Zapisuje godzinowe ceny €/kWh do pliku JSON czytanego przez aplikację."""
    payload = {
        "source": SOURCE_LABEL,
        "fetched_at": datetime.now().strftime(TIMESTAMP_FORMAT),
        "unit": "EUR/kWh",
        "prices": {
            moment.strftime(TIMESTAMP_FORMAT): str(price)
            for moment, price in sorted(prices.items())
        },
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
