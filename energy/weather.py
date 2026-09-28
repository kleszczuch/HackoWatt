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


@dataclass(frozen=True, slots=True)
class WeatherHour:
    """Reprezentuje jedną godzinę danych pogodowych dla konkretnego momentu czasu."""

    timestamp: datetime
    temperature: float
    cloud_cover: float
    radiation: float


def local_now(timezone: str = TIMEZONE) -> datetime:
    """Zwraca bieżący czas lokalny zaokrąglony do pełnej godziny."""
    return datetime.now(ZoneInfo(timezone)).replace(tzinfo=None, minute=0, second=0, microsecond=0)


def _get_json(url: str, params: dict) -> dict:
    """Pobiera i dekoduje odpowiedź JSON z API Open-Meteo, zgłaszając błąd w razie problemu."""
    full_url = f"{url}?{urlencode(params)}"
    try:
        with urlopen(full_url, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise WeatherFetchError(f"Nie udało się pobrać pogody z Open-Meteo: {exc}") from exc


def parse_hourly(payload: dict) -> list[WeatherHour]:
    """Konwertuje surowy payload API na listę obiektów WeatherHour z walidacją danych."""
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
    """Dzieli serię pogodową na część historyczną i prognostyczną względem bieżącej godziny."""
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    history = [r for r in records if r.timestamp < current_hour][-history_days * 24 :]
    forecast = [r for r in records if r.timestamp >= current_hour][: forecast_days * 24]
    if len(history) < history_days * 24:
        raise WeatherFetchError("Open-Meteo zwróciło za mało godzin historycznych.")
    if len(forecast) < forecast_days * 24:
        raise WeatherFetchError("Open-Meteo zwróciło za mało godzin prognozy.")
    return history, forecast


def fetch_weather_series(
    past_days: int = HISTORY_DAYS + 1,
    forecast_days: int = FORECAST_DAYS + 1,
    latitude: float = LATITUDE,
    longitude: float = LONGITUDE,
    timezone: str = TIMEZONE,
) -> list[WeatherHour]:
    """Pobiera pełną serię godzinową z historią i prognozą z jednego zapytania do API.

    Dni skrajne są częściowe (bieżąca godzina), więc pobieramy po jednym
    dniu zapasu z każdej strony i tniemy w `split_history_forecast`.
    """
    payload = _get_json(
        FORECAST_URL,
        {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": ",".join(HOURLY_VARIABLES),
            "timezone": timezone,
            "past_days": past_days,
            "forecast_days": forecast_days,
        },
    )
    return parse_hourly(payload)


def fetch_year_weather(
    reference: datetime | None = None,
    latitude: float = LATITUDE,
    longitude: float = LONGITUDE,
    timezone: str = TIMEZONE,
) -> list[WeatherHour]:
    """Pobiera archiwalne dane pogodowe za ostatnie 365 dni z uwzględnieniem opóźnienia API."""
    today = (reference or local_now(timezone)).date()
    end = today - timedelta(days=ARCHIVE_DELAY_DAYS)
    start = end - timedelta(days=YEAR_DAYS - 1)
    payload = _get_json(
        ARCHIVE_URL,
        {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": ",".join(HOURLY_VARIABLES),
            "timezone": timezone,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
    )
    return parse_hourly(payload)


def write_weather_csv(records: list[WeatherHour], path: Path | str) -> None:
    """Zapisuje listę rekordów pogodowych do pliku CSV w formacie używanym przez aplikację."""
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
    """Wczytuje dane pogodowe z CSV i zwraca je jako listę obiektów WeatherHour."""
    file_path = Path(path)
    records = []
    with file_path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source)
        try:
            headers = next(reader)
        except StopIteration:
            raise WeatherFetchError(f"Plik {file_path.name} jest pusty.")
        h_map = {name: i for i, name in enumerate(headers)}
        if not set(WEATHER_COLUMNS).issubset(h_map):
            raise WeatherFetchError(f"Plik {file_path.name} nie ma wymaganych kolumn pogody.")
        ts_idx = h_map["Data_Czas"]
        temp_idx = h_map["Temperatura_C"]
        cloud_idx = h_map["Zachmurzenie_proc"]
        rad_idx = h_map["Promieniowanie_W_m2"]
        for row in reader:
            if not row:
                continue
            records.append(
                WeatherHour(
                    datetime.fromisoformat(row[ts_idx]),
                    float(row[temp_idx]),
                    float(row[cloud_idx]),
                    float(row[rad_idx]),
                )
            )
    if not records:
        raise WeatherFetchError(f"Plik {file_path.name} nie zawiera godzin pogody.")
    return records
