"""Formularze: zakres dat, horyzont prognozy i parametry symulatora PV.
Plik definiuje formularze Django używane w aplikacji do obsługi wejścia
użytkownika i walidacji danych."""

from decimal import ROUND_HALF_UP, Decimal

from django import forms

from energy.currency import SYMBOLS, from_eur, to_eur
from energy.tariffs import MODE_DYNAMIC, MODE_FIXED, PROVIDERS, TARIFF_PERIODS

HORIZON_CHOICES_PL = (("24", "24 godziny"), ("72", "3 dni"), ("168", "7 dni"))
HORIZON_CHOICES_EN = (("24", "24 hours"), ("72", "3 days"), ("168", "7 days"))

MONTH_NAMES_PL = (
    "styczeń",
    "luty",
    "marzec",
    "kwiecień",
    "maj",
    "czerwiec",
    "lipiec",
    "sierpień",
    "wrzesień",
    "październik",
    "listopad",
    "grudzień",
)
MONTH_NAMES_EN = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

MONTH_CHOICES_PL = tuple((str(num), name) for num, name in enumerate(MONTH_NAMES_PL, start=1))
MONTH_CHOICES_EN = tuple((str(num), name) for num, name in enumerate(MONTH_NAMES_EN, start=1))

HORIZON_CHOICES = HORIZON_CHOICES_EN
MONTH_CHOICES = MONTH_CHOICES_EN


class DateRangeForm(forms.Form):
    start = forms.DateField(label="Od", widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(label="Do", widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, lang: str = "pl", **kwargs):
        super().__init__(*args, **kwargs)
        self.lang = lang
        if lang == "en":
            self.fields["start"].label = "From"
            self.fields["end"].label = "To"
        else:
            self.fields["start"].label = "Od"
            self.fields["end"].label = "Do"

    def clean(self):
        """Sprawdza, czy data końcowa nie jest wcześniejsza od początkowej."""
        cleaned = super().clean()
        start = cleaned.get("start")
        end = cleaned.get("end")
        if start and end and end < start:
            msg = (
                "The end date cannot be earlier than the start date."
                if self.lang == "en"
                else "Data końcowa nie może być wcześniejsza niż początkowa."
            )
            raise forms.ValidationError(msg)
        return cleaned


class HorizonForm(forms.Form):
    """Formularz do wyboru długości horyzontu prognozy."""

    horyzont = forms.ChoiceField(
        label="Horyzont prognozy",
        choices=HORIZON_CHOICES_PL,
        widget=forms.Select(),
    )

    def __init__(self, *args, lang: str = "pl", **kwargs):
        super().__init__(*args, **kwargs)
        self.lang = lang
        if lang == "en":
            self.fields["horyzont"].label = "Forecast horizon"
            self.fields["horyzont"].choices = HORIZON_CHOICES_EN
        else:
            self.fields["horyzont"].label = "Horyzont prognozy"
            self.fields["horyzont"].choices = HORIZON_CHOICES_PL


PERIOD_LABELS_PL = ("Noc 0–6", "Dzień 6–17", "Szczyt 17–22", "Wieczór 22–24")
PERIOD_LABELS_EN = ("Night 0–6", "Day 6–17", "Peak 17–22", "Evening 22–24")
PRICE_FIELDS = ("price_0", "price_1", "price_2", "price_3")


def _provider_choices(lang: str, currency: str) -> tuple[tuple[str, str], ...]:
    choices = []
    for provider in PROVIDERS:
        name = provider.name_en if lang == "en" else provider.name_pl
        margin = (
            provider.margin_pln
            if currency == "PLN"
            else from_eur(provider.margin, currency).quantize(Decimal("0.00001"))
        )
        choices.append((provider.id, f"{name} (+{margin} {SYMBOLS[currency]}/kWh)"))
    return tuple(choices)


class TariffSettingsForm(forms.Form):
    """Formularz wyboru taryfy energii: stała z edytowalnymi kwotami albo dynamiczna."""

    mode = forms.ChoiceField(label="Taryfa", widget=forms.RadioSelect())
    provider = forms.ChoiceField(label="Dostawca")
    price_0 = forms.DecimalField(min_value=0, max_digits=8, decimal_places=5)
    price_1 = forms.DecimalField(min_value=0, max_digits=8, decimal_places=5)
    price_2 = forms.DecimalField(min_value=0, max_digits=8, decimal_places=5)
    price_3 = forms.DecimalField(min_value=0, max_digits=8, decimal_places=5)

    def __init__(self, *args, lang: str = "pl", currency: str = "EUR", config=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.lang = lang
        self.currency = currency
        if lang == "en":
            self.fields["mode"].label = "Tariff"
            self.fields["mode"].choices = (
                (MODE_FIXED, "Fixed hourly tariff"),
                (MODE_DYNAMIC, "Dynamic tariff (PSE market prices + provider margin)"),
            )
            self.fields["provider"].label = "Provider"
            self.fields["provider"].choices = _provider_choices(lang, currency)
            period_labels = PERIOD_LABELS_EN
        else:
            self.fields["mode"].label = "Taryfa"
            self.fields["mode"].choices = (
                (MODE_FIXED, "Stała taryfa godzinowa"),
                (MODE_DYNAMIC, "Dynamiczna (ceny giełdowe PSE + marża dostawcy)"),
            )
            self.fields["provider"].label = "Dostawca"
            self.fields["provider"].choices = _provider_choices(lang, currency)
            period_labels = PERIOD_LABELS_PL
        for field_name, period_label in zip(PRICE_FIELDS, period_labels, strict=True):
            self.fields[field_name].label = f"{period_label} [{SYMBOLS[currency]}/kWh]"

        if config is not None and not self.is_bound:
            defaults = [price for _, _, price in TARIFF_PERIODS]
            prices = config.fixed_prices if config.fixed_prices is not None else defaults
            self.initial["mode"] = config.mode
            self.initial["provider"] = config.provider_id
            for field_name, price in zip(PRICE_FIELDS, prices, strict=True):
                self.initial[field_name] = from_eur(price, currency).quantize(
                    Decimal("0.00001"), rounding=ROUND_HALF_UP
                )

    def clean(self):
        cleaned = super().clean()
        for field_name in PRICE_FIELDS:
            price = cleaned.get(field_name)
            if price is not None and to_eur(price, self.currency) > 10:
                message = (
                    "Maximum price is 10 EUR/kWh."
                    if self.lang == "en"
                    else "Maksymalna cena to 10 EUR/kWh."
                )
                self.add_error(field_name, message)
        return cleaned

    def fixed_prices(self) -> tuple[Decimal, ...]:
        """Zwraca cztery kwoty okresów stałych po walidacji."""
        if self.currency == "EUR":
            return tuple(self.cleaned_data[field_name] for field_name in PRICE_FIELDS)
        return tuple(
            to_eur(self.cleaned_data[field_name], self.currency).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
            for field_name in PRICE_FIELDS
        )


class PvForm(forms.Form):
    """Formularz parametrów symulatora PV i magazynu energii."""

    kwp = forms.DecimalField(
        label="Moc instalacji [kWp]",
        min_value=1,
        max_value=150,
        max_digits=4,
        decimal_places=1,
    )
    miesiac = forms.ChoiceField(label="Miesiąc wykresu", choices=MONTH_CHOICES_PL)
    magazyn_kwh = forms.DecimalField(
        label="Pojemność magazynu [kWh]",
        min_value=0,
        max_value=5000,
        max_digits=5,
        decimal_places=1,
    )
    magazyn_moc_kw = forms.DecimalField(
        label="Moc magazynu [kW]",
        min_value=Decimal("0.1"),
        max_value=150,
        max_digits=4,
        decimal_places=1,
    )
    magazyn_koszt_eur = forms.DecimalField(
        label="Cena magazynu [EUR]",
        min_value=0,
        max_value=10000000,
        max_digits=10,
        decimal_places=2,
    )

    def __init__(self, *args, lang: str = "pl", currency: str = "EUR", **kwargs):
        super().__init__(*args, **kwargs)
        self.lang = lang
        self.currency = currency
        self.fields["magazyn_koszt_eur"].max_value = from_eur(Decimal("10000000"), currency)
        self.fields["magazyn_koszt_eur"].max_digits = 11
        if lang == "en":
            self.fields["kwp"].label = "PV capacity [kWp]"
            self.fields["miesiac"].label = "Chart month"
            self.fields["miesiac"].choices = MONTH_CHOICES_EN
            self.fields["magazyn_kwh"].label = "Battery capacity [kWh]"
            self.fields["magazyn_moc_kw"].label = "Battery power [kW]"
            self.fields["magazyn_koszt_eur"].label = f"Purchase price [{SYMBOLS[currency]}]"
        else:
            self.fields["kwp"].label = "Moc instalacji [kWp]"
            self.fields["miesiac"].label = "Miesiąc wykresu"
            self.fields["miesiac"].choices = MONTH_CHOICES_PL
            self.fields["magazyn_kwh"].label = "Pojemność magazynu [kWh]"
            self.fields["magazyn_moc_kw"].label = "Moc magazynu [kW]"
            self.fields["magazyn_koszt_eur"].label = f"Cena zakupu [{SYMBOLS[currency]}]"

    def clean(self):
        """Waliduje ceny i pojemność magazynu, aby zapobiec sprzecznym parametrom."""
        cleaned = super().clean()
        capacity = cleaned.get("magazyn_kwh")
        cost = cleaned.get("magazyn_koszt_eur")
        if capacity is not None and cost is not None:
            if capacity > 0 and cost <= 0:
                err = (
                    "Enter a battery purchase price above zero."
                    if self.lang == "en"
                    else "Podaj dodatnią cenę zakupu magazynu."
                )
                self.add_error("magazyn_koszt_eur", err)
            elif capacity == 0 and cost > 0:
                err = (
                    "With 0 kWh capacity, the price must be zero."
                    if self.lang == "en"
                    else "Przy pojemności 0 kWh cena musi wynosić 0."
                )
                self.add_error("magazyn_koszt_eur", err)
        return cleaned
