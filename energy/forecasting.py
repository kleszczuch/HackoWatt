"""Trening modeli prognozy, ocena wobec baseline'u i zapis wyników.

Trening odbywa się wyłącznie w komendzie `prepare_demo_data`; aplikacja
odczytuje gotowe pliki. Baseline to „ta sama godzina poprzedniego tygodnia”.
"""

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import xgboost as xgb

from energy.household import CATEGORIES, ConsumptionHour
from energy.weather import WeatherHour

FORECAST_FILENAME = "prognoza_zuzycie.csv"
BACKTEST_FILENAME = "backtest.csv"
METRICS_FILENAME = "metryki.json"
BACKTEST_HOURS = 168
HORIZONS = {"24h": 24, "3d": 72, "7d": 168}
BACKTEST_COLUMNS = ("Data_Czas", "Rzeczywiste_kWh", "Model_kWh", "Baseline_kWh")


@dataclass(frozen=True)
class BacktestRow:
    timestamp: datetime
    actual: Decimal
    model: Decimal
    baseline: Decimal


def _q3(value: float) -> Decimal:
    return Decimal(str(round(float(value), 3)))


def _features(timestamps: list[datetime], temperatures: list[float]) -> pd.DataFrame:
    stamps = pd.Series(pd.to_datetime(timestamps))
    return pd.DataFrame(
        {
            "Godzina": stamps.dt.hour,
            "Dzien_Tyg_Nr": stamps.dt.dayofweek,
            "Weekend": (stamps.dt.dayofweek >= 5).astype(int),
            "Miesiac": stamps.dt.month,
            "Temperatura": temperatures,
        }
    )


def _temperature_lookup(weather: list[WeatherHour]) -> dict[datetime, float]:
    return {record.timestamp: record.temperature for record in weather}


def _train_models(features: pd.DataFrame, consumption: list[ConsumptionHour]) -> dict:
    models = {}
    for index, category in enumerate(CATEGORIES):
        model = xgb.XGBRegressor(
            n_estimators=100,
            learning_rate=0.1,
            max_depth=4,
            n_jobs=4,
            random_state=78,
            tree_method="hist",
        )
        model.fit(features, [float(record.categories[index]) for record in consumption])
        models[category] = model
    return models


def _predict(models: dict, features: pd.DataFrame) -> list[tuple[Decimal, ...]]:
    predicted = {
        category: models[category].predict(features).clip(min=0) for category in CATEGORIES
    }
    return [
        tuple(_q3(predicted[category][row]) for category in CATEGORIES)
        for row in range(len(features))
    ]


def _mae(actual: list[Decimal], predicted: list[Decimal]) -> Decimal:
    return sum((abs(a - p) for a, p in zip(actual, predicted, strict=True)), Decimal(0)) / len(
        actual
    )


def _mape(actual: list[Decimal], predicted: list[Decimal]) -> Decimal:
    terms = [abs(a - p) / a for a, p in zip(actual, predicted, strict=True) if a > 0]
    return sum(terms, Decimal(0)) / len(terms) * 100


def _daily_totals(rows: list[BacktestRow], attribute: str) -> list[Decimal]:
    """Sumy dobowe – MAPE na godzinach jest psuty przez dni wyjazdu (małe mianowniki)."""
    totals: dict = {}
    for row in rows:
        key = row.timestamp.date()
        totals[key] = totals.get(key, Decimal(0)) + getattr(row, attribute)
    return list(totals.values())


def backtest(
    consumption: list[ConsumptionHour], history_weather: list[WeatherHour]
) -> tuple[list[BacktestRow], dict]:
    """Oceń model i baseline na ostatnich 7 dniach historii."""
    if len(consumption) < 2 * BACKTEST_HOURS:
        raise ValueError("Historia jest za krótka do oceny błędu (min. 14 dni).")
    temperatures = _temperature_lookup(history_weather)
    train, test = consumption[:-BACKTEST_HOURS], consumption[-BACKTEST_HOURS:]
    for record in consumption:
        if record.timestamp not in temperatures:
            raise ValueError(f"Brak temperatury dla godziny {record.timestamp}.")

    models = _train_models(
        _features([r.timestamp for r in train], [temperatures[r.timestamp] for r in train]), train
    )
    predictions = _predict(
        models, _features([r.timestamp for r in test], [temperatures[r.timestamp] for r in test])
    )

    rows = []
    for offset, record in enumerate(test):
        baseline_total = consumption[-2 * BACKTEST_HOURS + offset].total
        rows.append(
            BacktestRow(
                record.timestamp,
                record.total,
                sum(predictions[offset], Decimal(0)),
                baseline_total,
            )
        )

    actual = [row.actual for row in rows]
    daily_actual = _daily_totals(rows, "actual")
    metrics = {
        "okres_od": rows[0].timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "okres_do": rows[-1].timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "godzin": len(rows),
        "mae_model": float(_mae(actual, [row.model for row in rows]).quantize(Decimal("0.0001"))),
        "mape_model": float(
            _mape(daily_actual, _daily_totals(rows, "model")).quantize(Decimal("0.01"))
        ),
        "mae_baseline": float(
            _mae(actual, [row.baseline for row in rows]).quantize(Decimal("0.0001"))
        ),
        "mape_baseline": float(
            _mape(daily_actual, _daily_totals(rows, "baseline")).quantize(Decimal("0.01"))
        ),
    }
    return rows, metrics


def forecast(
    consumption: list[ConsumptionHour],
    history_weather: list[WeatherHour],
    forecast_weather: list[WeatherHour],
) -> list[ConsumptionHour]:
    """Wytrenuj na pełnej historii i prognozuj na godziny prognozy pogody."""
    temperatures = _temperature_lookup(history_weather)
    models = _train_models(
        _features(
            [r.timestamp for r in consumption], [temperatures[r.timestamp] for r in consumption]
        ),
        consumption,
    )
    predictions = _predict(
        models,
        _features(
            [r.timestamp for r in forecast_weather], [r.temperature for r in forecast_weather]
        ),
    )
    return [
        ConsumptionHour(record.timestamp, predictions[index], "")
        for index, record in enumerate(forecast_weather)
    ]


def write_backtest_csv(rows: list[BacktestRow], path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    with target.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(BACKTEST_COLUMNS)
        for row in rows:
            writer.writerow(
                [
                    row.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    f"{row.actual:.3f}",
                    f"{row.model:.3f}",
                    f"{row.baseline:.3f}",
                ]
            )


def write_metrics_json(metrics: dict, path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
