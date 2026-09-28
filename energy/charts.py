"""Wykresy Plotly: historia z temperaturą, prognoza, backtest i symulator PV.
Plik odpowiada za generowanie wykresów i wizualizacji danych energetycznych."""

from datetime import timedelta
from decimal import Decimal

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from energy.forecasting import BacktestRow
from energy.household import CATEGORIES, ConsumptionHour
from energy.presentation import event_names
from energy.pv import WeekProfile
from energy.weather import WeatherHour

CATEGORY_LABELS = (
    "Base load",
    "Heating",
    "Lighting",
    "Cooking",
    "TV / computers",
    "Major appliances",
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
    """Ustawia wspólny styl i właściwości osi dla wszystkich wykresów Plotly."""
    # 1. Automatycznie znajdujemy początek i koniec osi czasu w danych tego wykresu:
    all_x = []
    for trace in figure.data:
        if hasattr(trace, "x") and trace.x is not None and len(trace.x) > 0:
            # Ponieważ dane są posortowane chronologicznie, bierzemy pierwszy i ostatni punkt
            all_x.extend([trace.x[0], trace.x[-1]])

    min_x = min(all_x) if all_x else None
    max_x = max(all_x) if all_x else None
    if min_x is not None and min_x == max_x:
        min_x -= timedelta(minutes=30)
        max_x += timedelta(minutes=30)

    # 2. Główny layout wykresu
    figure.update_layout(
        template="plotly_white",
        margin={"l": 45, "r": 20, "t": 20, "b": 45},
        height=height,
        hovermode="x unified",
        dragmode=False,
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": CHARCOAL},
        hoverlabel={"bgcolor": "#FFFFFF", "bordercolor": SLATE, "font_color": CHARCOAL},
    )

    # 3. OŚ X: Odblokowujemy przesuwanie (fixedrange=False) i nakładamy TWARDE GRANICE
    xaxis_options = {
        "fixedrange": False,
        "linecolor": SLATE,
        "gridcolor": "rgba(84,84,84,0.12)",
    }
    if min_x is not None:
        xaxis_options.update(range=[min_x, max_x], minallowed=min_x, maxallowed=max_x)
    figure.update_xaxes(**xaxis_options)

    # 4. OŚ Y: Pozostaje ZABLOKOWANA (fixedrange=True) - piki nigdy się nie utną!
    figure.update_yaxes(fixedrange=True, linecolor=SLATE, gridcolor="rgba(84,84,84,0.12)")

    return figure


def _consumption_with_temperature(
    records: list[ConsumptionHour], weather: list[WeatherHour], height: int
) -> go.Figure:
    """Buduje wykres zużycia według kategorii wraz z temperaturą na drugiej osi."""
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
                hovertemplate="%{fullData.name}: %{y:.5~r} kWh<extra></extra>",
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
                name="Events",
                marker={
                    "color": CHARTREUSE,
                    "size": 7,
                    "symbol": "diamond",
                    "line": {"color": CHARCOAL, "width": 1.2},
                },
                text=[event_names(record.events) for record in event_points],
                hovertemplate="Events: %{text}<extra></extra>",
            ),
            secondary_y=False,
        )
    figure.add_trace(
        go.Scatter(
            x=[record.timestamp for record in weather],
            y=[record.temperature for record in weather],
            mode="lines",
            name="Temperature",
            line={"color": SLATE, "width": 2, "dash": "dot"},
            hovertemplate="Temperature: %{y:.1f} °C<extra></extra>",
        ),
        secondary_y=True,
    )
    figure.update_yaxes(title_text="kWh", rangemode="tozero", secondary_y=False)
    figure.update_yaxes(title_text="°C", secondary_y=True)
    return _base_layout(figure, height)


def build_history_chart(records: list[ConsumptionHour], weather: list[WeatherHour]) -> go.Figure:
    """Tworzy wykres historii zużycia z temperaturą do szczegółowej analizy czasu."""
    return _consumption_with_temperature(records, weather, 400)


def build_overview_chart(
    records: list[ConsumptionHour], weather: list[WeatherHour], *, forecast: bool = False
) -> go.Figure:
    """Tworzy zwięzły wykres podsumowania zużycia i temperatury dla pulpitu."""
    figure = make_subplots(specs=[[{"secondary_y": True}]])
    figure.add_trace(
        go.Scatter(
            x=[record.timestamp for record in records],
            y=[float(record.total) for record in records],
            name="Energy use · forecast" if forecast else "Energy use · simulation",
            mode="lines",
            line={
                "color": CHARCOAL if not forecast else SLATE,
                "width": 2.5,
                "dash": "solid" if not forecast else "dash",
            },
            fill="tozeroy",
            fillcolor="rgba(107,170,117,0.26)" if not forecast else "rgba(132,221,99,0.28)",
            hovertemplate="%{fullData.name}: %{y:.5~r} kWh<extra></extra>",
        ),
        secondary_y=False,
    )
    figure.add_trace(
        go.Scatter(
            x=[record.timestamp for record in weather],
            y=[record.temperature for record in weather],
            name="Temperature",
            mode="lines",
            line={"color": SLATE, "width": 1.8, "dash": "dot"},
            hovertemplate="Temperature: %{y:.1f} °C<extra></extra>",
        ),
        secondary_y=True,
    )
    figure.update_yaxes(title_text="kWh", rangemode="tozero", secondary_y=False)
    figure.update_yaxes(title_text="°C", secondary_y=True)
    return _base_layout(figure, 250)


def build_forecast_chart(records: list[ConsumptionHour], weather: list[WeatherHour]) -> go.Figure:
    """Generuje wersję wykresu prognozy z liniami stylizowanymi pod przewidywanie."""
    figure = _consumption_with_temperature(records, weather, 340)
    figure.update_traces(patch={"line": {"dash": "dash"}}, selector={"stackgroup": "zuzycie"})
    return figure


def build_backtest_chart(rows: list[BacktestRow]) -> go.Figure:
    """Porównuje rzeczywiste zużycie z modelem i baseline'em w ramach testu backtest."""
    figure = go.Figure()
    for values, label, color, dash in (
        ([row.actual for row in rows], "Actual (simulation)", CHARCOAL, "solid"),
        ([row.model for row in rows], "Model XGBoost", SLATE, "dash"),
        ([row.baseline for row in rows], "Baseline: last week", CHARCOAL, "dot"),
    ):
        figure.add_trace(
            go.Scatter(
                x=[row.timestamp for row in rows],
                y=[float(value) for value in values],
                mode="lines",
                name=label,
                line={"color": color, "width": 2, "dash": dash},
                hovertemplate="%{fullData.name}: %{y:.5~r} kWh<extra></extra>",
            )
        )
    figure.update_yaxes(title_text="kWh", rangemode="tozero")
    return _base_layout(figure, 320)


def build_pv_chart(week: WeekProfile, kwp: Decimal) -> go.Figure:
    """Rysuje prototyp wykresu PV pokazujący produkcję, obciążenie i zakupy z sieci."""
    figure = go.Figure()
    traces = (
        (week.pv, f"PV output ({kwp} kWp)", CHARCOAL, "solid", "tozeroy"),
        (week.load, "Household use", SLATE, "solid", None),
        (week.grid_a, "Grid purchases – current schedule", CHARCOAL, "dash", None),
        (week.grid_b, "Grid purchases – shifted appliances", SLATE, "dot", None),
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
                hovertemplate="%{fullData.name}: %{y:.5~r} kWh<extra></extra>",
            )
        )
    if any(value > 0 for value in week.battery_b):
        figure.add_trace(
            go.Scatter(
                x=week.timestamps,
                y=[float(value) for value in week.battery_b],
                mode="lines",
                name="Battery to household · B",
                line={"color": CHARCOAL, "width": 2, "dash": "dashdot"},
                hovertemplate="%{fullData.name}: %{y:.5~r} kWh<extra></extra>",
            )
        )
    figure.update_yaxes(title_text="kWh", rangemode="tozero")
    return _base_layout(figure, 380)
