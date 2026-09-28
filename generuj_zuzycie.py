"""Powtarzalne syntetyczne zużycie energii dla każdej godziny 2026 roku."""

from pathlib import Path

import numpy as np
import pandas as pd

CATEGORIES = (
    "Baza_kWh",
    "Ogrzewanie_kWh",
    "Oswietlenie_kWh",
    "Gotowanie_kWh",
    "RTV_PC_kWh",
    "Duze_AGD_kWh",
)
HISTORY_FILENAME = "zuzycie_energii_barbara_jan.csv"


def generate_consumption(
    output_path: Path | str = HISTORY_FILENAME, seed: int = 78
) -> pd.DataFrame:
    """Wygeneruj oryginalny profil godzinowy i zapisz go do CSV."""
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2026-01-01 00:00:00", "2026-12-31 23:00:00", freq="h")
    rows = []

    for dt in dates:
        hour = dt.hour
        month = dt.month
        heating_factor = max(0.05, 1.0 + 1.4 * np.cos((month - 1) * 2 * np.pi / 12))

        base = round(rng.uniform(0.08, 0.15), 3)
        if hour <= 5 or hour == 23:
            base_heating = rng.uniform(0.30, 0.45)
        elif hour <= 8:
            base_heating = rng.uniform(0.65, 0.85)
        else:
            base_heating = rng.uniform(0.60, 0.88)
        heating = round(base_heating * heating_factor, 3)

        lighting = 0.0
        if 6 <= hour <= 8 and month in (1, 2, 3, 10, 11, 12):
            lighting = round(rng.uniform(0.08, 0.24), 3)
        dusk = 16 if month in (11, 12, 1, 2) else 20 if month in (6, 7, 8) else 18
        if dusk <= hour <= 22:
            lighting = round(rng.uniform(0.07, 0.24), 3)

        cooking = 0.0
        if 6 <= hour <= 8:
            cooking = round(rng.uniform(0.20, 0.48), 3)
        elif 13 <= hour <= 15 and rng.rand() > 0.15:
            cooking = round(rng.uniform(0.55, 1.70), 3)
        elif 18 <= hour <= 20 and rng.rand() > 0.3:
            cooking = round(rng.uniform(0.12, 0.38), 3)

        media = 0.0
        if 9 <= hour <= 14 and rng.rand() > 0.4:
            media = round(rng.uniform(0.05, 0.15), 3)
        elif 15 <= hour <= 22:
            media = round(rng.uniform(0.11, 0.35), 3)

        appliances = 0.0
        if 11 <= hour <= 16 and rng.rand() < 0.07:
            appliances = round(rng.uniform(0.65, 1.45), 3)

        values = (base, heating, lighting, cooking, media, appliances)
        rows.append(
            {
                "Data_Czas": dt.strftime("%Y-%m-%d %H:%M:%S"),
                "Dzien_Tygodnia": dt.day_name(),
                "Godzina": hour,
                **dict(zip(CATEGORIES, values, strict=True)),
                "Calkowite_Zuzycie_kWh": round(sum(values), 3),
            }
        )

    frame = pd.DataFrame(rows)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return frame


if __name__ == "__main__":
    result = generate_consumption()
    print(f"Wygenerowano {len(result)} godzin do pliku {HISTORY_FILENAME}")
