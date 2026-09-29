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
from energy.tariffs import price_for_hour
from energy.weather import WeatherHour

CATEGORY_LABELS_PL = (
    "Baza",
    "Ogrzewanie",
    "Oświetlenie",
    "Gotowanie",
    "RTV / PC",
    "Duże AGD",
)
CATEGORY_LABELS_EN = (
    "Base load",
    "Heating",
    "Lighting",
    "Cooking",
    "TV / computers",
    "Major appliances",
)

CATEGORY_LABELS = CATEGORY_LABELS_EN

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


def _add_price_traces(
    figure: go.Figure,
    timestamps: list,
    rce_prices: dict | None,
    *,
    lang: str,
    third_axis: bool,
) -> None:
    """Dodaje serie ceny RCE i taryfy na dodatkowej osi Y w €/kWh.

    third_axis=True stosuje się, gdy wykres ma już oś temperatury (y2);
    wtedy cena ląduje na wolnej osi y3 po prawej stronie.
    """
    if lang == "en":
        rce_name = "Price · RCE"
        tariff_name = "Price · tariff"
        price_hover = "Price: %{y:.4f} €/kWh<extra></extra>"
    else:
        rce_name = "Cena · RCE"
        tariff_name = "Cena · taryfa"
        price_hover = "Cena: %{y:.4f} €/kWh<extra></extra>"

    rce_values = []
    tariff_values = []
    for ts in timestamps:
        hour_key = ts.replace(minute=0, second=0, microsecond=0)
        rce_price = rce_prices.get(hour_key) if rce_prices else None
        rce_values.append(float(rce_price) if rce_price is not None else None)
        tariff_values.append(None if rce_price is not None else float(price_for_hour(ts.hour)))

    axis_ref = "y3" if third_axis else "y2"
    if any(value is not None for value in rce_values):
        figure.add_trace(
            go.Scatter(
                x=timestamps,
                y=rce_values,
                mode="lines",
                name=rce_name,
                line={"color": SAGE, "width": 1.6},
                hovertemplate=price_hover,
                yaxis=axis_ref,
            )
        )
    if any(value is not None for value in tariff_values):
        figure.add_trace(
            go.Scatter(
                x=timestamps,
                y=tariff_values,
                mode="lines",
                name=tariff_name,
                line={"color": GRASS, "width": 1.6, "dash": "dash"},
                hovertemplate=price_hover,
                yaxis=axis_ref,
            )
        )

    axis_options = {
        "overlaying": "y",
        "side": "right",
        "title_text": "€/kWh",
        "fixedrange": True,
        "showgrid": False,
        "linecolor": SLATE,
        "automargin": True,
    }
    if third_axis:
        axis_options.update(anchor="free", position=1.0)
        figure.update_layout(yaxis2={"anchor": "free", "position": 0.92, "automargin": True})
        figure.update_layout(yaxis3=axis_options, margin={"r": 60})
    else:
        figure.update_layout(yaxis2=axis_options, margin={"r": 55})


def _base_layout(figure: go.Figure, height: int, lang: str = "en") -> go.Figure:
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
        separators=", " if lang == "pl" else ".,",
    )

    # 3. OŚ X: Odblokowujemy przesuwanie (fixedrange=False) i nakładamy TWARDE GRANICE
    xaxis_options = {
        "fixedrange": False,
        "linecolor": SLATE,
        "gridcolor": "rgba(84,84,84,0.12)",
    }
    if min_x is not None:
        xaxis_options.update(range=[min_x, max_x], minallowed=min_x, maxallowed=max_x)
    if lang == "pl":
        xaxis_options.update(tickformat="%H:%M<br>%d.%m.%Y", hoverformat="%d.%m.%Y %H:%M")
    figure.update_xaxes(**xaxis_options)

    # 4. OŚ Y: Pozostaje ZABLOKOWANA (fixedrange=True) - piki nigdy się nie utną!
    figure.update_yaxes(fixedrange=True, linecolor=SLATE, gridcolor="rgba(84,84,84,0.12)")

    return figure


def _consumption_with_temperature(
    records: list[ConsumptionHour],
    weather: list[WeatherHour],
    height: int,
    prices: dict | None = None,
    lang: str = "en",
) -> go.Figure:
    category_labels = CATEGORY_LABELS_EN if lang == "en" else CATEGORY_LABELS_PL
    events_label = "Events" if lang == "en" else "Zdarzenia"
    events_hover = (
        "Events: %{text}<extra></extra>" if lang == "en" else "Zdarzenia: %{text}<extra></extra>"
    )
    temp_label = "Temperature" if lang == "en" else "Temperatura"
    temp_hover = (
        "Temperature: %{y:.1f} °C<extra></extra>"
        if lang == "en"
        else "Temperatura: %{y:.1f} °C<extra></extra>"
    )

    figure = make_subplots(specs=[[{"secondary_y": True}]])
    for index, (category, label) in enumerate(zip(CATEGORIES, category_labels, strict=True)):
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
                name=events_label,
                marker={
                    "color": CHARTREUSE,
                    "size": 7,
                    "symbol": "diamond",
                    "line": {"color": CHARCOAL, "width": 1.2},
                },
                text=[event_names(record.events, lang=lang) for record in event_points],
                hovertemplate=events_hover,
            ),
            secondary_y=False,
        )
    figure.add_trace(
        go.Scatter(
            x=[record.timestamp for record in weather],
            y=[record.temperature for record in weather],
            mode="lines",
            name=temp_label,
            line={"color": SLATE, "width": 2, "dash": "dot"},
            hovertemplate=temp_hover,
        ),
        secondary_y=True,
    )
    figure.update_yaxes(title_text="kWh", rangemode="tozero", secondary_y=False)
    figure.update_yaxes(title_text="°C", secondary_y=True)
    figure = _base_layout(figure, height, lang=lang)
    if prices is not None:
        _add_price_traces(
            figure, [record.timestamp for record in records], prices, lang=lang, third_axis=True
        )
    return figure


def build_history_chart(
    records: list[ConsumptionHour],
    weather: list[WeatherHour],
    *,
    prices: dict | None = None,
    lang: str = "en",
) -> go.Figure:
    return _consumption_with_temperature(records, weather, 400, prices=prices, lang=lang)


def build_overview_chart(
    records: list[ConsumptionHour],
    weather: list[WeatherHour],
    *,
    prices: dict | None = None,
    forecast: bool = False,
    lang: str = "en",
) -> go.Figure:
    """Zwarty trend całkowitego zużycia i temperatury na pulpit."""
    if lang == "en":
        usage_name = "Energy use · forecast" if forecast else "Energy use · simulation"
        temp_name = "Temperature"
        temp_hover = "Temperature: %{y:.1f} °C<extra></extra>"
    else:
        usage_name = "Zużycie · prognoza" if forecast else "Zużycie · symulacja"
        temp_name = "Temperatura"
        temp_hover = "Temperatura: %{y:.1f} °C<extra></extra>"

    figure = make_subplots(specs=[[{"secondary_y": True}]])
    figure.add_trace(
        go.Scatter(
            x=[record.timestamp for record in records],
            y=[float(record.total) for record in records],
            name=usage_name,
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
            name=temp_name,
            mode="lines",
            line={"color": SLATE, "width": 1.8, "dash": "dot"},
            hovertemplate=temp_hover,
        ),
        secondary_y=True,
    )
    figure.update_yaxes(title_text="kWh", rangemode="tozero", secondary_y=False)
    figure.update_yaxes(title_text="°C", secondary_y=True)
    figure = _base_layout(figure, 250, lang=lang)
    if prices is not None:
        _add_price_traces(
            figure, [record.timestamp for record in records], prices, lang=lang, third_axis=True
        )
    return figure


def build_forecast_chart(
    records: list[ConsumptionHour],
    weather: list[WeatherHour],
    prices: dict | None = None,
    lang: str = "en",
) -> go.Figure:
    figure = _consumption_with_temperature(records, weather, 340, prices=prices, lang=lang)
    figure.update_traces(patch={"line": {"dash": "dash"}}, selector={"stackgroup": "zuzycie"})
    return figure


def build_backtest_chart(
    rows: list[BacktestRow], *, prices: dict | None = None, lang: str = "en"
) -> go.Figure:
    figure = go.Figure()
    if lang == "en":
        trace_defs = (
            ([row.actual for row in rows], "Simulated consumption", CHARCOAL, "solid"),
            ([row.model for row in rows], "Model XGBoost", SLATE, "dash"),
            ([row.baseline for row in rows], "Reference: last week", CHARCOAL, "dot"),
        )
    else:
        trace_defs = (
            ([row.actual for row in rows], "Zużycie symulowane", CHARCOAL, "solid"),
            ([row.model for row in rows], "Model XGBoost", SLATE, "dash"),
            ([row.baseline for row in rows], "Odniesienie: tydzień temu", CHARCOAL, "dot"),
        )
    for values, label, color, dash in trace_defs:
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
    figure = _base_layout(figure, 320, lang=lang)
    if prices is not None:
        _add_price_traces(
            figure, [row.timestamp for row in rows], prices, lang=lang, third_axis=False
        )
    return figure


def build_pv_chart(
    week: WeekProfile, kwp: Decimal, *, prices: dict | None = None, lang: str = "en"
) -> go.Figure:
    figure = go.Figure()
    if lang == "en":
        traces = (
            (week.pv, f"PV output ({kwp} kWp)", CHARCOAL, "solid", "tozeroy"),
            (week.load, "Household use", SLATE, "solid", None),
            (week.grid_a, "Grid purchases – current schedule", CHARCOAL, "dash", None),
            (week.grid_b, "Grid purchases – shifted appliances", SLATE, "dot", None),
        )
        battery_name = "Battery to household · B"
    else:
        traces = (
            (week.pv, f"Produkcja PV ({kwp} kWp)", CHARCOAL, "solid", "tozeroy"),
            (week.load, "Zużycie domu", SLATE, "solid", None),
            (week.grid_a, "Zakup z sieci – obecne nawyki", CHARCOAL, "dash", None),
            (week.grid_b, "Zakup z sieci – po przesunięciu", SLATE, "dot", None),
        )
        battery_name = "Z magazynu do domu · B"

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
                name=battery_name,
                line={"color": CHARCOAL, "width": 2, "dash": "dashdot"},
                hovertemplate="%{fullData.name}: %{y:.5~r} kWh<extra></extra>",
            )
        )
    figure.update_yaxes(title_text="kWh", rangemode="tozero")
    figure = _base_layout(figure, 380, lang=lang)
    if prices is not None:
        _add_price_traces(figure, week.timestamps, prices, lang=lang, third_axis=False)
    return figure
