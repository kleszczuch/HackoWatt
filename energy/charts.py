"""Wykresy Plotly: historia z temperaturą, prognoza, backtest i symulator PV."""

from decimal import Decimal

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from energy.forecasting import BacktestRow
from energy.household import CATEGORIES, ConsumptionHour
from energy.pv import WeekProfile
from energy.weather import WeatherHour

CATEGORY_LABELS = (
    "Baza",
    "Ogrzewanie",
    "Oświetlenie",
    "Gotowanie",
    "RTV / PC",
    "Duże AGD",
)
CHARCOAL = "#545454"
SLATE = "#69747C"
SAGE = "#6BAA75"
GRASS = "#84DD63"
CHARTREUSE = "#CBFF4D"
CATEGORY_FILLS = (
    "rgba(84,84,84,0.50)",
    "rgba(105,116,124,0.55)",
    "rgba(107,170,117,0.65)",
    "rgba(132,221,99,0.65)",
    "rgba(203,255,77,0.85)",
    "rgba(107,170,117,0.38)",
)
CATEGORY_DASHES = ("solid", "solid", "dash", "solid", "dot", "dashdot")


def _base_layout(figure: go.Figure, height: int) -> go.Figure:
    # 1. Automatycznie znajdujemy początek i koniec osi czasu w danych tego wykresu:
    all_x = []
    for trace in figure.data:
        if hasattr(trace, "x") and trace.x is not None and len(trace.x) > 0:
            # Ponieważ dane są posortowane chronologicznie, bierzemy pierwszy i ostatni punkt
            all_x.extend([trace.x[0], trace.x[-1]])

    min_x = min(all_x) if all_x else None
    max_x = max(all_x) if all_x else None

    # 2. Główny layout wykresu
    figure.update_layout(
        template="plotly_white",
        margin={"l": 45, "r": 20, "t": 20, "b": 45},
        height=height,
        hovermode="x unified",
        dragmode="pan",  # <-- ZMIANA: włączamy chwytanie i przesuwanie "łapką"
        legend={"orientation": "h", "y": 1.14, "x": 0},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": CHARCOAL},
        hoverlabel={"bgcolor": "#FFFFFF", "font_color": CHARCOAL},
    )

    # 3. OŚ X: Odblokowujemy przesuwanie (fixedrange=False) i nakładamy TWARDE GRANICE
    figure.update_xaxes(
        fixedrange=False,       # Pozwala na zoom i przesuwanie
        minallowed=min_x,       # TWARDY LIMIT W LEWO (koniec z nieskończonością!)
        maxallowed=max_x,       # TWARDY LIMIT W PRAWO
        linecolor=SLATE, 
        gridcolor="rgba(84,84,84,0.12)"
    )

    # 4. OŚ Y: Pozostaje ZABLOKOWANA (fixedrange=True) - piki nigdy się nie utną!
    figure.update_yaxes(
        fixedrange=True, 
        linecolor=SLATE, 
        gridcolor="rgba(84,84,84,0.12)"
    )
    
    return figure


def _consumption_with_temperature(
    records: list[ConsumptionHour], weather: list[WeatherHour], height: int
) -> go.Figure:
    figure = make_subplots(specs=[[{"secondary_y": True}]])
    for index, (category, label) in enumerate(zip(CATEGORIES, CATEGORY_LABELS, strict=True)):
        figure.add_trace(
            go.Scatter(
                x=[record.timestamp for record in records],
                y=[float(record.categories[index]) for record in records],
                mode="lines",
                name=label,
                stackgroup="zuzycie",
                line={
                    "color": CHARCOAL if index % 2 == 0 else SLATE,
                    "width": 1.4,
                    "dash": CATEGORY_DASHES[index],
                },
                fillcolor=CATEGORY_FILLS[index],
                hovertemplate="%{x|%d.%m %H:%M}: %{y:.3f} kWh<extra>%{fullData.name}</extra>",
            ),
            secondary_y=False,
        )
    event_points = [record for record in records if record.events]
    if event_points:
        figure.add_trace(
            go.Scatter(
                x=[record.timestamp for record in event_points],
                y=[float(record.total) for record in event_points],
                mode="markers",
                name="Zdarzenia",
                marker={
                    "color": CHARTREUSE,
                    "size": 7,
                    "symbol": "diamond",
                    "line": {"color": CHARCOAL, "width": 1.2},
                },
                text=[record.events for record in event_points],
                hovertemplate="%{x|%d.%m %H:%M}: %{text}<extra>Zdarzenia</extra>",
            ),
            secondary_y=False,
        )
    figure.add_trace(
        go.Scatter(
            x=[record.timestamp for record in weather],
            y=[record.temperature for record in weather],
            mode="lines",
            name="Temperatura",
            line={"color": SLATE, "width": 2, "dash": "dot"},
            hovertemplate="%{x|%d.%m %H:%M}: %{y:.1f} °C<extra>Temperatura</extra>",
        ),
        secondary_y=True,
    )
    figure.update_yaxes(title_text="kWh", rangemode="tozero", secondary_y=False)
    figure.update_yaxes(title_text="°C", secondary_y=True)
    return _base_layout(figure, height)


def build_history_chart(records: list[ConsumptionHour], weather: list[WeatherHour]) -> go.Figure:
    return _consumption_with_temperature(records, weather, 400)


def build_overview_chart(
    records: list[ConsumptionHour], weather: list[WeatherHour], *, forecast: bool = False
) -> go.Figure:
    """Zwarty trend całkowitego zużycia i temperatury na pulpit."""
    figure = make_subplots(specs=[[{"secondary_y": True}]])
    figure.add_trace(
        go.Scatter(
            x=[record.timestamp for record in records],
            y=[float(record.total) for record in records],
            name="Zużycie · prognoza" if forecast else "Zużycie · symulacja",
            mode="lines",
            line={
                "color": CHARCOAL if not forecast else SLATE,
                "width": 2.5,
                "dash": "solid" if not forecast else "dash",
            },
            fill="tozeroy",
            fillcolor="rgba(107,170,117,0.26)" if not forecast else "rgba(132,221,99,0.28)",
            hovertemplate="%{x|%d.%m %H:%M}: %{y:.3f} kWh<extra>%{fullData.name}</extra>",
        ),
        secondary_y=False,
    )
    figure.add_trace(
        go.Scatter(
            x=[record.timestamp for record in weather],
            y=[record.temperature for record in weather],
            name="Temperatura",
            mode="lines",
            line={"color": SLATE, "width": 1.8, "dash": "dot"},
            hovertemplate="%{x|%d.%m %H:%M}: %{y:.1f} °C<extra>Temperatura</extra>",
        ),
        secondary_y=True,
    )
    figure.update_yaxes(title_text="kWh", rangemode="tozero", secondary_y=False)
    figure.update_yaxes(title_text="°C", secondary_y=True)
    return _base_layout(figure, 250)


def build_forecast_chart(records: list[ConsumptionHour], weather: list[WeatherHour]) -> go.Figure:
    figure = _consumption_with_temperature(records, weather, 340)
    figure.update_traces(patch={"line": {"dash": "dash"}}, selector={"stackgroup": "zuzycie"})
    return figure


def build_backtest_chart(rows: list[BacktestRow]) -> go.Figure:
    figure = go.Figure()
    for values, label, color, dash in (
        ([row.actual for row in rows], "Rzeczywiste (symulacja)", CHARCOAL, "solid"),
        ([row.model for row in rows], "Model XGBoost", SLATE, "dash"),
        ([row.baseline for row in rows], "Baseline: tydzień temu", CHARCOAL, "dot"),
    ):
        figure.add_trace(
            go.Scatter(
                x=[row.timestamp for row in rows],
                y=[float(value) for value in values],
                mode="lines",
                name=label,
                line={"color": color, "width": 2, "dash": dash},
                hovertemplate="%{x|%d.%m %H:%M}: %{y:.3f} kWh<extra>%{fullData.name}</extra>",
            )
        )
    figure.update_yaxes(title_text="kWh", rangemode="tozero")
    return _base_layout(figure, 320)


def build_pv_chart(week: WeekProfile, kwp: Decimal) -> go.Figure:
    figure = go.Figure()
    traces = (
        (week.pv, f"Produkcja PV ({kwp} kWp)", CHARCOAL, "solid", "tozeroy"),
        (week.load, "Zużycie domu", SLATE, "solid", None),
        (week.grid_a, "Zakup z sieci – obecne nawyki", CHARCOAL, "dash", None),
        (week.grid_b, "Zakup z sieci – po przesunięciu", SLATE, "dot", None),
    )
    for values, label, color, dash, fill in traces:
        figure.add_trace(
            go.Scatter(
                x=week.timestamps,
                y=[float(value) for value in values],
                mode="lines",
                name=label,
                fill=fill,
                fillcolor="rgba(203,255,77,0.42)" if fill else None,
                line={"color": color, "width": 2, "dash": dash},
                hovertemplate="%{x|%d.%m %H:%M}: %{y:.3f} kWh<extra>%{fullData.name}</extra>",
            )
        )
    if any(value > 0 for value in week.battery_b):
        figure.add_trace(
            go.Scatter(
                x=week.timestamps,
                y=[float(value) for value in week.battery_b],
                mode="lines",
                name="Z magazynu do domu · B",
                line={"color": CHARCOAL, "width": 2, "dash": "dashdot"},
                hovertemplate="%{x|%d.%m %H:%M}: %{y:.3f} kWh<extra>%{fullData.name}</extra>",
            )
        )
    figure.update_yaxes(title_text="kWh", rangemode="tozero")
    return _base_layout(figure, 380)
