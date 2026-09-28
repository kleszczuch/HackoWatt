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
COLORS = ("#6b7280", "#e45d47", "#e6a23b", "#3d9b75", "#4e83c2", "#8b70b3")
TEMPERATURE_COLOR = "#2f6f8f"


def _base_layout(figure: go.Figure, height: int) -> go.Figure:
    figure.update_layout(
        template="plotly_white",
        margin={"l": 45, "r": 20, "t": 20, "b": 45},
        height=height,
        hovermode="x unified",
        legend={"orientation": "h", "y": 1.14, "x": 0},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return figure


def _consumption_with_temperature(
    records: list[ConsumptionHour], weather: list[WeatherHour], height: int
) -> go.Figure:
    figure = make_subplots(specs=[[{"secondary_y": True}]])
    for index, (category, label, color) in enumerate(
        zip(CATEGORIES, CATEGORY_LABELS, COLORS, strict=True)
    ):
        figure.add_trace(
            go.Scatter(
                x=[record.timestamp for record in records],
                y=[float(record.categories[index]) for record in records],
                mode="lines",
                name=label,
                stackgroup="zuzycie",
                line={"color": color, "width": 1.2},
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
                marker={"color": "#c2571f", "size": 6, "symbol": "diamond"},
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
            line={"color": TEMPERATURE_COLOR, "width": 1.8, "dash": "dot"},
            hovertemplate="%{x|%d.%m %H:%M}: %{y:.1f} °C<extra>Temperatura</extra>",
        ),
        secondary_y=True,
    )
    figure.update_yaxes(title_text="kWh", rangemode="tozero", secondary_y=False)
    figure.update_yaxes(title_text="°C", secondary_y=True)
    return _base_layout(figure, height)


def build_history_chart(records: list[ConsumptionHour], weather: list[WeatherHour]) -> go.Figure:
    return _consumption_with_temperature(records, weather, 400)


def build_forecast_chart(records: list[ConsumptionHour], weather: list[WeatherHour]) -> go.Figure:
    figure = _consumption_with_temperature(records, weather, 340)
    figure.update_traces(patch={"line": {"dash": "dash"}}, selector={"stackgroup": "zuzycie"})
    return figure


def build_backtest_chart(rows: list[BacktestRow]) -> go.Figure:
    figure = go.Figure()
    for values, label, color, dash in (
        ([row.actual for row in rows], "Rzeczywiste (symulacja)", "#218a72", "solid"),
        ([row.model for row in rows], "Model XGBoost", "#e59b44", "dash"),
        ([row.baseline for row in rows], "Baseline: tydzień temu", "#8b70b3", "dot"),
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
        (week.pv, f"Produkcja PV ({kwp} kWp)", "#e6a23b", "solid", "tozeroy"),
        (week.load, "Zużycie domu", "#4e83c2", "solid", None),
        (week.grid_a, "Zakup z sieci — obecne nawyki", "#e45d47", "solid", None),
        (week.grid_b, "Zakup z sieci — po przesunięciu", "#218a72", "dash", None),
    )
    for values, label, color, dash, fill in traces:
        figure.add_trace(
            go.Scatter(
                x=week.timestamps,
                y=[float(value) for value in values],
                mode="lines",
                name=label,
                fill=fill,
                line={"color": color, "width": 2, "dash": dash},
                hovertemplate="%{x|%d.%m %H:%M}: %{y:.3f} kWh<extra>%{fullData.name}</extra>",
            )
        )
    figure.update_yaxes(title_text="kWh", rangemode="tozero")
    return _base_layout(figure, 380)
