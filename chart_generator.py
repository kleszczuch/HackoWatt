"""Trening modeli z oryginalnego generatora wykresów i zapis prognozy CSV."""

from decimal import Decimal
from pathlib import Path

import pandas as pd
import xgboost as xgb

from generuj_zuzycie import CATEGORIES, HISTORY_FILENAME

FORECAST_FILENAME = "prognoza_energii_barbara_jan.csv"


def _features(dates: pd.Series) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Godzina": dates.dt.hour,
            "Miesiac": dates.dt.month,
            "Dzien_Tyg_Nr": dates.dt.dayofweek,
        }
    )


def generate_forecast(
    history_path: Path | str = HISTORY_FILENAME,
    output_path: Path | str = FORECAST_FILENAME,
    days: int = 90,
) -> pd.DataFrame:
    """Wytrenuj sześć modeli XGBoost i zapisz kolejne pełne godziny."""
    if days < 1:
        raise ValueError("Liczba dni prognozy musi być dodatnia.")

    history = pd.read_csv(history_path)
    missing = (set(CATEGORIES) | {"Data_Czas"}) - set(history.columns)
    if missing:
        raise ValueError(f"W historii brakuje kolumn: {', '.join(sorted(missing))}")
    if history.empty:
        raise ValueError("Historia jest pusta.")

    history_dates = pd.to_datetime(history["Data_Czas"], format="%Y-%m-%d %H:%M:%S")
    future_dates = pd.Series(
        pd.date_range(history_dates.max() + pd.Timedelta(hours=1), periods=days * 24, freq="h")
    )
    historical_features = _features(history_dates)
    future_features = _features(future_dates)

    forecast = pd.DataFrame({"Data_Czas": future_dates.dt.strftime("%Y-%m-%d %H:%M:%S")})
    forecast["Dzien_Tygodnia"] = future_dates.dt.day_name()
    forecast["Godzina"] = future_dates.dt.hour

    for category in CATEGORIES:
        model = xgb.XGBRegressor(
            n_estimators=100,
            learning_rate=0.1,
            max_depth=4,
            n_jobs=4,
            random_state=78,
            tree_method="hist",
        )
        model.fit(historical_features, history[category])
        forecast[category] = model.predict(future_features).clip(min=0).round(6)

    forecast["Calkowite_Zuzycie_kWh"] = forecast[list(CATEGORIES)].apply(
        lambda row: f"{sum(Decimal(str(value)) for value in row):.6f}", axis=1
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    forecast.to_csv(path, index=False, float_format="%.6f")
    return forecast


if __name__ == "__main__":
    result = generate_forecast()
    print(f"Wygenerowano {len(result)} godzin prognozy do pliku {FORECAST_FILENAME}")
