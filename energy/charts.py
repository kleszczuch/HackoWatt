"""Wykresy Plotly dla danych syntetycznych i prognozy."""

from collections import defaultdict
from decimal import Decimal

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from energy.data import EnergyRecord
from generuj_zuzycie import CATEGORIES

CATEGORY_LABELS = (
    "Baza",
    "Ogrzewanie",
    "Oświetlenie",
    "Gotowanie",
    "RTV / PC",
    "Duże AGD",
)
COLORS = ("#6b7280", "#e45d47", "#e6a23b", "#3d9b75", "#4e83c2", "#8b70b3")


def build_overview(history: list[EnergyRecord], forecast: list[EnergyRecord]) -> go.Figure:
    figure = go.Figure()
    for records, label, color, dash in (
        (history, "Symulacja 2026", "#218a72", "solid"),
        (forecast, "Prognoza XGBoost", "#e59b44", "dash"),
    ):
        daily = defaultdict(Decimal)
        for record in records:
            daily[record.date] += record.total_decimal
        figure.add_trace(
            go.Scatter(
                x=list(daily),
                y=[float(value) for value in daily.values()],
                mode="lines",
                name=label,
                line={"color": color, "width": 2.3, "dash": dash},
                hovertemplate="%{x}: %{y:.3f} kWh<extra>%{fullData.name}</extra>",
            )
        )
    figure.add_vline(x=forecast[0].date.isoformat(), line_dash="dot", line_color="#536777")
    figure.update_layout(
        template="plotly_white",
        margin={"l": 45, "r": 20, "t": 20, "b": 45},
        height=310,
        hovermode="x unified",
        legend={"orientation": "h", "y": 1.17, "x": 0},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    figure.update_yaxes(title_text="kWh / dzień", rangemode="tozero")
    return figure


def build_details(history: list[EnergyRecord], forecast: list[EnergyRecord]) -> go.Figure:
    figure = make_subplots(rows=3, cols=2, subplot_titles=CATEGORY_LABELS, vertical_spacing=0.12)
    for index, (category, color) in enumerate(zip(CATEGORIES, COLORS, strict=True)):
        row, col = divmod(index, 2)
        for records, label, dash in (
            (history, "Symulacja", "solid"),
            (forecast, "Prognoza", "dash"),
        ):
            if not records:
                continue
            figure.add_trace(
                go.Scatter(
                    x=[record.timestamp for record in records],
                    y=[float(Decimal(record.categories[index])) for record in records],
                    mode="lines",
                    name=label,
                    legendgroup=label,
                    showlegend=index == 0,
                    line={"color": color, "width": 1.7, "dash": dash},
                    hovertemplate="%{x|%d.%m %H:%M}: %{y:.3f} kWh<extra>%{fullData.name}</extra>",
                ),
                row=row + 1,
                col=col + 1,
            )
    figure.update_layout(
        template="plotly_white",
        height=770,
        margin={"l": 42, "r": 20, "t": 55, "b": 35},
        hovermode="x unified",
        legend={"orientation": "h", "y": 1.1},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    figure.update_xaxes(matches="x")
    figure.update_yaxes(rangemode="tozero")
    return figure
