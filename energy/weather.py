"""Pobieranie rzeczywistej pogody godzinowej z Open-Meteo dla Kopenhagi."""

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

LATITUDE = 55.6761
LONGITUDE = 12.5683
TIMEZONE = "Europe/Copenhagen"
LOCATION_LABEL = "Kopenhaga, Dania"
HISTORY_DAYS = 35
FORECAST_DAYS = 7
YEAR_DAYS = 365
ARCHIVE_DELAY_DAYS = 6

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HOURLY_VARIABLES = ("temperature_2m", "cloud_cover", "shortwave_radiation")

WEATHER_COLUMNS = ("Data_Czas", "Temperatura_C", "Zachmurzenie_proc", "Promieniowanie_W_m2")
HISTORY_WEATHER_FILENAME = "pogoda_historia.csv"
FORECAST_WEATHER_FILENAME = "pogoda_prognoza.csv"
YEAR_WEATHER_FILENAME = "pogoda_roczna.csv"

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


class WeatherFetchError(RuntimeError):
    """Pobieranie pogody z Open-Meteo nie powiodło się."""


@dataclass(frozen=True)
class WeatherHour:
    timestamp: datetime
    temperature: float
    cloud_cover: float
    radiation: float


def local_now() -> datetime:
    return datetime.now(ZoneInfo(TIMEZONE)).replace(tzinfo=None, minute=0, second=0, microsecond=0)


def _get_json(url: str, params: dict) -> dict:
    full_url = f"{url}?{urlencode(params)}"
    try:
        with urlopen(full_url, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise WeatherFetchError(f"Nie udało się pobrać pogody z Open-Meteo: {exc}") from exc


def parse_hourly(payload: dict) -> list[WeatherHour]:
    try:
        hourly = payload["hourly"]
        times = hourly["time"]
        temperatures = hourly["temperature_2m"]
        clouds = hourly["cloud_cover"]
        radiations = hourly["shortwave_radiation"]
    except (KeyError, TypeError) as exc:
        raise WeatherFetchError(f"Odpowiedź Open-Meteo nie ma oczekiwanych pól: {exc}") from exc
    if not (len(times) == len(temperatures) == len(clouds) == len(radiations)):
        raise WeatherFetchError("Odpowiedź Open-Meteo ma nierówne długości szeregów.")
    records = []
    for index, label in enumerate(times):
        values = (temperatures[index], clouds[index], radiations[index])
        if any(value is None for value in values):
            continue
        records.append(
            WeatherHour(
                datetime.strptime(label, "%Y-%m-%dT%H:%M"),
                float(values[0]),
                float(values[1]),
                float(values[2]),
            )
        )
    if not records:
        raise WeatherFetchError("Odpowiedź Open-Meteo nie zawiera żadnej pełnej godziny.")
    return records


def split_history_forecast(
    records: list[WeatherHour],
    now: datetime,
    history_days: int = HISTORY_DAYS,
    forecast_days: int = FORECAST_DAYS,
) -> tuple[list[WeatherHour], list[WeatherHour]]:
    """Podziel szereg na historię kończącą się przed `now` i prognozę od `now`."""
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    history = [r for r in records if r.timestamp < current_hour][-history_days * 24 :]
    forecast = [r for r in records if r.timestamp >= current_hour][: forecast_days * 24]
    if len(history) < history_days * 24:
        raise WeatherFetchError("Open-Meteo zwróciło za mało godzin historycznych.")
    if len(forecast) < forecast_days * 24:
        raise WeatherFetchError("Open-Meteo zwróciło za mało godzin prognozy.")
    return history, forecast


def fetch_weather_series(
    past_days: int = HISTORY_DAYS + 1, forecast_days: int = FORECAST_DAYS + 1
) -> list[WeatherHour]:
    """Jedno zapytanie: ciągły szereg godzinowy od przeszłości po prognozę.

    Dni skrajne są częściowe (bieżąca godzina), więc pobieramy po jednym
    dniu zapasu z każdej strony i tniemy w `split_history_forecast`.
    """
    payload = _get_json(
        FORECAST_URL,
        {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "hourly": ",".join(HOURLY_VARIABLES),
            "timezone": TIMEZONE,
            "past_days": past_days,
            "forecast_days": forecast_days,
        },
    )
    return parse_hourly(payload)


def fetch_year_weather(reference: datetime | None = None) -> list[WeatherHour]:
    """Archiwum za ostatnie pełne 12 miesięcy (archiwum ma kilkudniowe opóźnienie)."""
    today = (reference or local_now()).date()
    end = today - timedelta(days=ARCHIVE_DELAY_DAYS)
    start = end - timedelta(days=YEAR_DAYS - 1)
    payload = _get_json(
        ARCHIVE_URL,
        {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "hourly": ",".join(HOURLY_VARIABLES),
            "timezone": TIMEZONE,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
    )
    return parse_hourly(payload)


def write_weather_csv(records: list[WeatherHour], path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(WEATHER_COLUMNS)
        for record in records:
            writer.writerow(
                [
                    record.timestamp.strftime(TIMESTAMP_FORMAT),
                    f"{record.temperature:.1f}",
                    f"{record.cloud_cover:.0f}",
                    f"{record.radiation:.1f}",
                ]
            )


def read_weather_csv(path: Path | str) -> list[WeatherHour]:
    records = []
    with Path(path).open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None or not set(WEATHER_COLUMNS).issubset(reader.fieldnames):
            raise WeatherFetchError(f"Plik {Path(path).name} nie ma wymaganych kolumn pogody.")
        for row in reader:
            records.append(
                WeatherHour(
                    datetime.strptime(row["Data_Czas"], TIMESTAMP_FORMAT),
                    float(row["Temperatura_C"]),
                    float(row["Zachmurzenie_proc"]),
                    float(row["Promieniowanie_W_m2"]),
                )
            )
    if not records:
        raise WeatherFetchError(f"Plik {Path(path).name} nie zawiera godzin pogody.")
    return records
